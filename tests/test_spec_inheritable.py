"""E1: 상속 허용 표시(spec_attribute.inheritable), 단위 표, 사양 DB 점검 스크립트(읽기 전용)."""
import hashlib
import importlib.util
import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from entity.spec_units import read_number, to_attribute_unit
from repository.repo_connect import Database
from repository.spec_repository import SpecRepository

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def repo(tmp_path):
    return SpecRepository(Database(str(tmp_path / "spec.db")))


# ---------- inheritable 컬럼과 수정 규칙 ----------

def test_new_attribute_is_not_inheritable(repo):
    attribute = repo.create_attribute("ram_max_gb", "메모리 최대 용량", "memory", "number", "GB")
    assert attribute["inheritable"] == 0


def test_inheritable_can_be_turned_on_and_off(repo):
    repo.create_attribute("ram_max_gb", "메모리 최대 용량", "memory", "number", "GB")
    assert repo.update_attribute("ram_max_gb", inheritable=True)["inheritable"] == 1
    # 다른 칸만 고쳐도 켠 값은 그대로다
    assert repo.update_attribute("ram_max_gb", description="최대")["inheritable"] == 1
    assert repo.update_attribute("ram_max_gb", inheritable=False)["inheritable"] == 0


def test_cert_attribute_cannot_be_inheritable(repo):
    repo.create_attribute("kc_safety", "KC 안전확인", "cert", "text")
    with pytest.raises(ValueError):
        repo.update_attribute("kc_safety", inheritable=True)
    assert repo.get_attribute("kc_safety")["inheritable"] == 0
    # 물려받기가 켜진 속성을 인증 분류로 옮기는 것도 막는다
    repo.create_attribute("weight_kg", "무게", "body", "number", "kg")
    repo.update_attribute("weight_kg", inheritable=True)
    with pytest.raises(ValueError):
        repo.update_attribute("weight_kg", category="cert")
    assert repo.get_attribute("weight_kg")["category"] == "body"


def test_api_put_inheritable_and_cert_400(repo, monkeypatch):
    from app.routers import specs

    monkeypatch.setattr(specs, "spec_repo", repo)
    app = FastAPI()
    app.include_router(specs.router)
    client = TestClient(app)
    repo.create_attribute("ram_max_gb", "메모리 최대 용량", "memory", "number", "GB")
    repo.create_attribute("kc_emc", "KC 전자파", "cert", "text")

    ok = client.put("/specs/attributes/ram_max_gb", json={"inheritable": True})
    refused = client.put("/specs/attributes/kc_emc", json={"inheritable": True})

    assert ok.status_code == 200 and ok.json()["inheritable"] == 1
    assert refused.status_code == 400 and "인증" in refused.json()["detail"]
    assert client.get("/specs/attributes").json()[0].keys() >= {"inheritable"}


def test_migrate_adds_inheritable_to_old_db(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            """CREATE TABLE spec_attribute (
                key TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL DEFAULT 'other',
                data_type TEXT NOT NULL DEFAULT 'text', unit TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '',
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT current_timestamp, updated_at TEXT NOT NULL DEFAULT current_timestamp)"""
        )
        conn.execute("INSERT INTO spec_attribute (key, name) VALUES ('os', '운영체제')")

    Database(str(path))
    Database(str(path))  # 두 번 열어도 컬럼은 한 번만

    with sqlite3.connect(path) as conn:
        columns = [r[1] for r in conn.execute("PRAGMA table_info(spec_attribute)")]
        rows = conn.execute("SELECT key, inheritable FROM spec_attribute").fetchall()
    assert columns.count("inheritable") == 1
    assert rows == [("os", 0)]


# ---------- 단위 표 ----------

@pytest.mark.parametrize("value, unit, attribute_unit, category, expected", [
    (1.5, "kg", "g", None, 1500.0),
    (1500, "g", "kg", None, 1.5),
    (1, "TB", "GB", "storage", 1000.0),
    (1, "GB", "MB", "memory", 1024.0),
    (1, "GB", "MB", "storage", 1000.0),
    (3.5, "GHz", "MHz", None, 3500.0),
    (1, "inch", "mm", None, 25.4),
    (2, "cm", "mm", None, 20.0),
    (1, "GB/s", "MB/s", None, 1000.0),
    (1, "K IOPS", "IOPS", None, 1000.0),
    (16, "", "GB", "memory", 16.0),
    (16, "GB", "GHz", None, None),        # 다른 차원
    (80, "Wh", "mAh", None, None),        # 전력·용량은 환산하지 않는다
    (65, "W", "Wh", None, None),
])
def test_to_attribute_unit(value, unit, attribute_unit, category, expected):
    assert to_attribute_unit(value, unit, attribute_unit, category) == expected


@pytest.mark.parametrize("text, attribute_unit, category, value, problem", [
    ("5,000MB/s", "MB/s", "storage", 5000.0, False),
    ("1TB", "GB", "storage", 1000.0, False),
    ("600T", "TB", "storage", 600.0, False),
    ("545K", "K IOPS", "storage", 545.0, False),
    ("8 GDDR7", "GB", "graphics", 8.0, False),     # 띄어 쓴 설명은 단위가 아니다
    ("1500g", "kg", "body", 1.5, False),
    ("5년", "년", "other", 5.0, False),
    ("16", "GB", "memory", 16.0, False),
    ("16XB", "GB", "memory", None, True),          # 모르는 단위
    ("3.2GHz", "GB", "memory", None, True),        # 다른 차원
    ("미정", "GB", "memory", None, True),          # 숫자 없음
])
def test_read_number(text, attribute_unit, category, value, problem):
    result = read_number(text, attribute_unit, category)
    assert result.value == value
    assert (result.problem is not None) == problem


# ---------- 점검 스크립트 ----------

def _load_audit():
    spec = importlib.util.spec_from_file_location("audit_spec_values", PROJECT_ROOT / "scripts" / "audit_spec_values.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_audit_reports_findings_and_does_not_write(tmp_path, capsys):
    path = tmp_path / "fixture.db"
    repo = SpecRepository(Database(str(path)))
    repo.create_attribute("ssd_tbw", "총 쓰기 용량(TBW)", "storage", "number", "TB")
    repo.create_attribute("tbw", "TBW", "other", "text")
    repo.create_attribute("ssd_gb", "SSD 용량", "storage", "number", "GB")
    repo.create_attribute("cpu_max_ghz", "CPU 최대 클럭", "cpu", "number", "GHz")
    product = repo.create_product("N5800")
    repo.create_product("A650")  # 값 없는 제품
    ssd = repo.create_component("ssd", "Samsung 980 1TB")
    repo.add_spec("component", ssd["id"], "ssd_gb", "1TB")            # GB 속성에 TB → 환산 가능
    repo.add_spec("product", product["id"], "cpu_max_ghz", "5.1GB")   # 다른 차원 → 확인 필요
    repo.add_spec("component", ssd["id"], "ssd_tbw", "600TB")
    with sqlite3.connect(path) as conn:  # 옛 데이터처럼 value_num이 빈 행
        conn.execute("UPDATE spec_value SET value_num = NULL WHERE attribute_key = 'ssd_tbw'")
    before = _digest(path)

    module = _load_audit()
    assert module.main(["--db", str(path)]) == 0
    report = capsys.readouterr().out

    assert _digest(path) == before  # 읽기만 했다
    assert "1TB → 1000GB" in report
    assert "5.1GB" in report and "단위 확인 필요" in report
    assert "| ssd_tbw (총 쓰기 용량(TBW), number, TB) | tbw (TBW, text) |" in report
    assert "## 3. number 속성인데 value_num이 NULL인 값 (1건)" in report
    assert "| A650 |" in report and "제품-부품 연결: 0건" in report


def test_audit_script_does_not_import_repository():
    source = (PROJECT_ROOT / "scripts" / "audit_spec_values.py").read_text(encoding="utf-8")
    assert "import repository" not in source and "from repository" not in source
    assert "mode=ro" in source
    units = (PROJECT_ROOT / "entity" / "spec_units.py").read_text(encoding="utf-8")
    assert "import repository" not in units and "from repository" not in units
