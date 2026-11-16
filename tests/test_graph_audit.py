"""GR0: 그래프 점검 스크립트(읽기 전용)와 식별자·정식 이름 맞춤 키 규칙."""
import sqlite3
import sys
from pathlib import Path

import pytest

if not hasattr(sys.modules.get("parser"), "__path__"):
    sys.modules.pop("parser", None)

from graph_rag.rules import has_identifier, spec_match_key, spec_match_keys  # noqa: E402
from repository.repo_connect import Database  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import audit_graph  # noqa: E402


@pytest.mark.parametrize("name", ["N5800", "GeForce RTX 5070", "Samsung PM9C1b", "R-R-TGE-N5800", "A650-GA70-PU02"])
def test_identifier_present(name):
    assert has_identifier(name)


@pytest.mark.parametrize("name", ["Tensor 코어", "RT 코어", "Blackwell 아키텍처", "Radeon", "Ryzen", "XDNA", "XDNA 2", "안전확인 신고"])
def test_identifier_absent(name):
    assert not has_identifier(name)


def test_identifier_checks_aliases_too():
    assert has_identifier(["엔비디아 그래픽", "RTX 5070"])


def test_spec_match_key_strips_marks_parens_nouns_and_vendor():
    assert spec_match_keys("AMD Ryzen™ AI 7 350 프로세서") == ["amdryzenai7350", "ryzenai7350"]
    assert spec_match_key("NVIDIA GeForce RTX 5070 (105W)") == spec_match_key("NVIDIA GeForce RTX 5070")
    assert "geforcertx5070" in spec_match_keys("NVIDIA GeForce RTX 5070 (105W)")
    assert spec_match_key("Intel Core Ultra 7 155H Processor") == "intelcoreultra7155h"
    assert spec_match_keys("SK hynix PC801") == ["skhynixpc801", "pc801"]
    # 단어 중간의 GPU는 떼지 않는다
    assert spec_match_key("eGPU") == "egpu"
    # ™는 TM이 되지 않는다
    assert "tm" not in spec_match_key("Ryzen™ 7")


def _graph_db(path: Path) -> None:
    Database(str(path))
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO product (id, model) VALUES ('p1', 'A650'), ('p2', 'A650-GA70-PU02')")
        conn.execute("UPDATE product SET parent_id='p1' WHERE id='p2'")
        conn.execute("INSERT INTO component (id, kind, model) VALUES ('c1', 'gpu', 'NVIDIA GeForce RTX 5070')")
        conn.executemany("INSERT INTO graph_entity (id, type, name, norm) VALUES (?,?,?,?)", [
            (1, "concept", "KC 인증", "kc인증"), (2, "certification", "안전확인 신고", "안전확인신고"),
            (3, "component", "GeForce RTX 5070", "geforcertx5070"), (4, "organization", "NVIDIA", "nvidia"),
            (5, "component", "Tensor 코어", "tensor코어"), (6, "product", "A650", "a650"),
        ])
        conn.executemany("INSERT INTO graph_alias (entity_id, alias, alias_norm) SELECT id, name, norm FROM graph_entity WHERE id=?",
                         [(i,) for i in range(1, 7)])
        conn.executemany("INSERT INTO graph_relation (src_id, dst_id, type, origin) VALUES (?,?,?,?)", [
            (2, 1, "part_of", "seed"), (3, 4, "issued_by", "extract"), (6, 3, "has_component", "extract"),
        ])


def test_audit_reports_concepts_violations_and_spec_mismatch(tmp_path):
    path = tmp_path / "g.db"
    _graph_db(path)
    with audit_graph.connect_readonly(path) as conn:
        text = "\n".join(audit_graph.audit(conn))
    assert "| 1 | KC 인증 |" in text
    assert "안전확인 신고 | KC 인증 | seed" in text
    assert "GeForce RTX 5070(component) | NVIDIA(organization)" in text  # issued_by 출발 종류 위반
    assert "| 5 | component | Tensor 코어 |" in text  # 식별자 없음
    assert "| 6 | product | A650 | product_line |" in text  # 하위 모델이 있는 제품은 제품군
    assert "## 6. 관계도 등장 위치도 없는 개체\n\n1개" in text  # Tensor 코어


def test_audit_opens_read_only(tmp_path):
    path = tmp_path / "g.db"
    _graph_db(path)
    with audit_graph.connect_readonly(path) as conn:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("DELETE FROM graph_entity")


def test_audit_script_does_not_import_repository():
    source = (ROOT / "scripts" / "audit_graph.py").read_text(encoding="utf-8")
    rules = (ROOT / "graph_rag" / "rules.py").read_text(encoding="utf-8")
    assert "from repository" not in source and "import repository" not in source
    assert "repository" not in rules.split('"""', 2)[2] and "import config" not in rules
