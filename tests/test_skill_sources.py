"""I1: 작성 절차(author 채널)와 DB 승인본을 합치는 로더."""
import logging

import pytest
from langchain_core.messages import AIMessage, SystemMessage

from agent import skills
from agent.evidence_context import Owner, owner_scope
from test_skills import write_skill


@pytest.fixture(autouse=True)
def restore_skills():
    yield
    skills.set_db_source(None)
    skills.reload_skills()


def db_row(name, description="생성된 절차 설명", body="# 절차\n1. 순서", version=1) -> dict:
    return {"name": name, "version": version, "description": description, "body": body}


def call_load_skill(name: str, owner: Owner) -> str:
    from tools.tool import load_skill
    with owner_scope(owner):
        return load_skill.invoke({"name": name})


def make_repo(tmp_path, with_author=True):
    write_skill(tmp_path, "mail-reply-style", channels="mail", body="문체")
    write_skill(tmp_path, "revise-after-reject", channels="mail", body="반려")
    write_skill(tmp_path, "spec-compare", body="대조")
    if with_author:
        write_skill(tmp_path, "create-skill", channels="author", body="절차를 이렇게 쓴다")
    return skills.reload_skills(tmp_path)


def test_author_skill_is_not_listed_or_loadable_in_answer_channels(tmp_path):
    make_repo(tmp_path)

    assert skills.author_skill().body == "절차를 이렇게 쓴다"
    assert skills.author_skill_status()["available"] is True
    for channel in ("mail", "web"):
        assert "create-skill" not in [s.name for s in skills.selectable_skills(channel)]
    assert skills.selectable_skills("author") == []
    for owner in (Owner("task", "t1"), Owner("session", "s1")):
        out = call_load_skill("create-skill", owner)
        assert out.startswith("오류:") and "절차를 이렇게 쓴다" not in out


def test_author_channel_mixed_with_answer_channels_is_author_only(tmp_path):
    write_skill(tmp_path, "create-skill", channels="author,mail", body="섞임")

    loaded = skills.reload_skills(tmp_path)

    # 작성 SKILL이 답변 채널에 섞여 모델에 읽히지 않게 author로만 쓴다
    assert loaded["create-skill"].channels == ("author",)
    assert skills.author_skill().body == "섞임"
    assert skills.selectable_skills("mail") == []


def test_missing_create_skill_disables_author_only(tmp_path):
    make_repo(tmp_path, with_author=False)

    assert skills.author_skill() is None
    assert skills.author_skill_status() == {
        "available": False, "name": "create-skill", "digest": None,
        "reason": "skills/create-skill/SKILL.md가 없습니다",
    }
    assert [s.name for s in skills.selectable_skills("web")] == ["spec-compare"]


def test_db_skill_appears_and_disappears_without_reload(tmp_path):
    make_repo(tmp_path)
    rows = []
    skills.set_db_source(lambda: rows)

    assert [s.name for s in skills.selectable_skills("mail")] == ["mail-reply-style", "revise-after-reject", "spec-compare"]
    rows.append(db_row("warranty-terms", version=2))

    listed = {s.name: s for s in skills.selectable_skills("mail")}
    assert set(listed) == {"mail-reply-style", "revise-after-reject", "spec-compare", "warranty-terms"}
    db = listed["warranty-terms"]
    assert (db.origin, db.version, db.channels) == ("db", 2, ("mail", "web"))
    assert db.digest == skills.body_digest(db.body)
    assert [s.name for s in skills.selectable_skills("web")] == ["spec-compare", "warranty-terms"]
    assert call_load_skill("warranty-terms", Owner("session", "s1")).startswith("[업무 절차 warranty-terms")
    assert skills.repo_skills()["spec-compare"].origin == "repo" and skills.repo_skills()["spec-compare"].version is None

    rows.clear()  # 사용 중지
    assert "warranty-terms" not in skills.get_skills()
    assert call_load_skill("warranty-terms", Owner("task", "t1")).startswith("오류:")


def test_db_skill_with_repo_or_reserved_name_is_ignored(tmp_path, caplog):
    make_repo(tmp_path)
    skills.set_db_source(lambda: [
        db_row("spec-compare", body="DB가 덮으려는 본문"),
        db_row("create-skill", body="작성 절차 덮기"),
        db_row("drafts"),
        db_row("Bad_Name"),
        db_row("empty-body", body="   "),
        db_row("long-body", body="가" * 50000),  # 길이 제한은 없다
    ])

    with caplog.at_level(logging.ERROR):
        merged = skills.get_skills()
        skills.get_skills()  # 두 번째 조회에서는 같은 오류를 다시 남기지 않는다

    assert merged["spec-compare"].body == "대조" and merged["spec-compare"].origin == "repo"
    assert skills.author_skill().body == "절차를 이렇게 쓴다"
    assert set(merged) == {"mail-reply-style", "revise-after-reject", "spec-compare", "create-skill", "long-body"}
    assert len([r for r in caplog.records if "DB 업무 절차를 읽지 않음" in r.getMessage()]) == 5


def test_db_skill_cannot_take_a_repository_name(tmp_path):
    """저장소 SKILL과 같은 이름의 DB 절차는 읽지 않는다 (저장소 것이 그대로 쓰인다)."""
    make_repo(tmp_path)
    skills.set_db_source(lambda: [db_row("mail-reply-style", body="DB 문체"), db_row("revise-after-reject")])

    assert skills.get_skills()["mail-reply-style"].body == "문체"
    assert all(s.origin == "repo" for s in skills.selectable_skills("mail"))


def test_db_failure_falls_back_to_repository(tmp_path):
    make_repo(tmp_path)

    def broken():
        raise RuntimeError("DB 잠김")

    skills.set_db_source(broken)

    assert [s.name for s in skills.selectable_skills("web")] == ["spec-compare"]
    assert [s.name for s in skills.selectable_skills("mail")] == ["mail-reply-style", "revise-after-reject", "spec-compare"]


def test_approved_db_skill_is_listed_in_agent_prompt_not_body(agent_env, tmp_path):
    from agent import agent as agent_module

    make_repo(tmp_path)
    skills.set_db_source(lambda: [db_row("warranty-terms", description="보증 조건 문의", body="보증 본문 비밀")])
    model = agent_env.install([AIMessage(content="답\n근거: 없음")])

    agent_module.run_agent_temp_attachments("보증", mode="local", owner=Owner("task", "t1"))

    prompt = next(m.content for m in model.calls[0] if isinstance(m, SystemMessage))
    assert "- warranty-terms: 보증 조건 문의" in prompt and "보증 본문 비밀" not in prompt
    assert "create-skill" not in prompt and "절차를 이렇게 쓴다" not in prompt
    assert "- mail-reply-style: 설명" in prompt  # 메일 SKILL도 목록으로만 보인다
    run = agent_env.evidence_repo.runs_for_owner("task", "t1")[0]
    assert run["skills"] == []  # 서버가 강제로 붙이는 SKILL은 없다
