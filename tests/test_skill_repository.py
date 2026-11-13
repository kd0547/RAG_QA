"""I2: 문의 유형·문의 분석·DB 절차 저장 구조."""
import sqlite3

import pytest

from agent import skills
from repository.repo_connect import Database
from repository.skill_repository import SEED_TYPES, SkillRepository


@pytest.fixture
def repo(tmp_path):
    return SkillRepository(Database(str(tmp_path / "skill.db")))


@pytest.fixture(autouse=True)
def restore_skills():
    yield
    skills.set_db_source(None)
    skills.reload_skills()


def approve(repo, doc_id):
    """승인 API 없이 상태만 바꾼다 (I2 판정 규칙 확인용)."""
    with repo.db.transaction() as conn:
        conn.execute("UPDATE skill_doc SET status = 'approved' WHERE doc_id = ?", (doc_id,))


def add(repo, name, version, status="draft"):
    doc_id = repo.insert_doc(name=name, version=version, status="draft", origin="generated",
                             description=f"{name} v{version}", body=f"본문 v{version}")
    if status == "approved":
        approve(repo, doc_id)
    elif status != "draft":
        with repo.db.transaction() as conn:
            conn.execute("UPDATE skill_doc SET status = ? WHERE doc_id = ?", (status, doc_id))
    return doc_id


def test_existing_db_gets_tables_and_seed_types_once(tmp_path):
    path = tmp_path / "old.db"
    # 지시서 I 이전 DB: 새 테이블 없음
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE tasks (task_id TEXT PRIMARY KEY, mail_uid TEXT, status TEXT, created_at TEXT, updated_at TEXT)")
    conn.commit()
    conn.close()

    repo = SkillRepository(Database(str(path)))
    assert repo.ensure_seed_types() == 3
    assert SkillRepository(Database(str(path))).ensure_seed_types() == 0

    types = repo.list_types()
    assert [(t["label"], t["skill_name"], t["state"], t["origin"]) for t in sorted(types, key=lambda t: t["type_id"])] == [
        (s["label"], s["skill_name"], s["state"], "seed") for s in SEED_TYPES
    ]
    with repo.db.get_conn() as c:
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"request_type", "request_analysis", "skill_doc"} <= tables


def test_active_version_rule(repo):
    v1 = add(repo, "warranty-terms", 1, "approved")
    add(repo, "warranty-terms", 2, "draft")
    assert [(d["name"], d["version"]) for d in repo.active_skill_docs()] == [("warranty-terms", 1)]

    approve(repo, repo.history("warranty-terms")[1]["doc_id"])
    assert [(d["name"], d["version"]) for d in repo.active_skill_docs()] == [("warranty-terms", 2)]

    add(repo, "warranty-terms", 3, "retired")
    assert repo.active_skill_docs() == []
    assert repo.latest_approved("warranty-terms")["version"] == 2
    assert [d["version"] for d in repo.history("warranty-terms")] == [1, 2, 3]
    assert repo.get_doc(v1)["body"] == "본문 v1"  # 이전 버전은 이력에 그대로


def test_unapproved_rows_are_never_active(repo):
    for status in ("draft", "error", "rejected"):
        add(repo, f"only-{status}", 1, status)
    repo.create_generating(type_id=1)

    assert repo.active_skill_docs() == []


def test_loader_reads_active_db_skill_through_repository(repo, monkeypatch):
    import repository

    monkeypatch.setattr(repository, "skill_repo", repo)
    skills.set_db_source(None)
    add(repo, "warranty-terms", 1, "draft")
    assert "warranty-terms" not in skills.get_skills()

    approve(repo, repo.history("warranty-terms")[0]["doc_id"])
    skill = skills.get_skills()["warranty-terms"]
    assert (skill.origin, skill.version, skill.body) == ("db", 1, "본문 v1")

    add(repo, "warranty-terms", 2, "retired")
    assert "warranty-terms" not in skills.get_skills()


def test_type_helpers(repo):
    repo.ensure_seed_types()
    cert = repo.find_type_by_label(" 인증자료 요청 ")
    assert cert["skill_name"] == "certification-bundle"

    created = repo.create_type("보증\n기간  문의" + "가" * 40, "보증 기간을\n묻는다")
    assert "\n" not in created["label"] and len(created["label"]) == 30 and created["origin"] == "model"
    assert created["description"] == "보증 기간을 묻는다"
    assert repo.create_type(created["label"].upper(), "다른 설명")["type_id"] == created["type_id"]

    with repo.db.transaction() as conn:
        conn.execute("UPDATE request_type SET state = 'merged', merged_into = ? WHERE type_id = ?",
                     (cert["type_id"], created["type_id"]))
    assert repo.resolve_type(created["type_id"])["type_id"] == cert["type_id"]
    assert repo.resolve_type(9999) is None
