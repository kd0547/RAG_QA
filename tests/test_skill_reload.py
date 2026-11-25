"""저장소 절차를 재시작 없이 다시 읽기, 실행 단위 목록, search_skills, 참고 파일, 끄기."""
import logging
import os
import shutil

import pytest
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

from agent import skills
from agent.evidence_context import Owner, owner_scope
from conftest import tool_call
from test_skills import write_skill

REPO_ANSWER_SKILLS = ("certification-bundle", "mail-reply-style", "revise-after-reject", "spec-compare")


@pytest.fixture(autouse=True)
def always_check(monkeypatch):
    """폴더 서명을 매번 보게 한다 (실서버는 1초 간격). 끝나면 저장소 절차·꺼진 목록을 원래대로."""
    monkeypatch.setattr(skills, "CHECK_INTERVAL_SECONDS", 0)
    skills.set_disabled_source(lambda: set())
    yield
    skills.set_disabled_source(None)
    skills.reload_skills()


def bump(path):
    """같은 크기로 고쳐도 서명이 바뀌게 수정 시각을 앞으로 민다 (파일 시스템 시각 단위가 거칠 수 있다)."""
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 2_000_000_000))


def load(name, file=None, owner=Owner("session", "s1")) -> str:
    from tools.tool import load_skill
    args = {"name": name} if file is None else {"name": name, "file": file}
    with owner_scope(owner):
        return load_skill.invoke(args)


def search(query, owner=Owner("session", "s1")) -> str:
    from tools.tool import search_skills
    with owner_scope(owner):
        return search_skills.invoke({"query": query})


# ---------------------------------------------------------------- 재시작 없이 반영

def test_added_changed_removed_documents_are_picked_up_without_restart(tmp_path, caplog):
    write_skill(tmp_path, "first", body="첫 본문")
    assert list(skills.reload_skills(tmp_path)) == ["first"]

    write_skill(tmp_path, "second", description="두 번째 절차")
    assert sorted(skills.repo_skills()) == ["first", "second"]

    path = write_skill(tmp_path, "first", body="고친 본문")
    bump(path)
    with caplog.at_level(logging.INFO, logger="agent.skills"):
        assert skills.repo_skills()["first"].body == "고친 본문"
    assert any("다시 읽음" in r.getMessage() for r in caplog.records)

    shutil.rmtree(tmp_path / "second")
    assert list(skills.repo_skills()) == ["first"]


def test_broken_document_is_reported_and_fixed_document_returns(tmp_path):
    skills.reload_skills(tmp_path)
    broken = tmp_path / "later" / "SKILL.md"
    broken.parent.mkdir()
    broken.write_text("---\nname: [깨진 YAML\n---\n본문\n", encoding="utf-8")
    assert "later" not in skills.repo_skills() and "later" in skills.repo_errors()

    bump(write_skill(tmp_path, "later"))
    assert "later" in skills.repo_skills() and skills.repo_errors() == {}


def test_signature_is_not_rechecked_within_interval(tmp_path, monkeypatch):
    skills.reload_skills(tmp_path)
    monkeypatch.setattr(skills, "CHECK_INTERVAL_SECONDS", 3600)
    write_skill(tmp_path, "late")
    assert skills.repo_skills() == {}  # 간격 안에서는 다시 보지 않는다
    monkeypatch.setattr(skills, "CHECK_INTERVAL_SECONDS", 0)
    assert list(skills.repo_skills()) == ["late"]


def test_run_keeps_the_catalog_it_started_with(tmp_path, agent_env):
    from agent import agent as agent_module

    write_skill(tmp_path, "warranty", description="보증 기간 문의에 읽는다", body="옛 본문")
    skills.reload_skills(tmp_path)

    def change_then_load(_messages):
        """실행 도중 파일을 바꾼다. 같은 실행의 load_skill은 실행 시작 때의 본문을 읽어야 한다."""
        bump(write_skill(tmp_path, "warranty", description="보증 기간 문의에 읽는다", body="새 본문"))
        return tool_call("load_skill", {"name": "warranty"}, "k")

    model = agent_env.install([change_then_load, AIMessage(content="답\n근거: 없음")])
    agent_module.run_agent_temp_attachments("보증은?", mode="local", owner=Owner("session", "s1"))

    contents = {m.tool_call_id: m.content for m in model.calls[-1] if isinstance(m, ToolMessage)}
    assert contents["k"].endswith("옛 본문")
    assert load("warranty").endswith("새 본문")  # 다음 실행부터는 새 본문


# ---------------------------------------------------------------- 끄기

def test_disabled_repository_skill_is_left_out_but_keeps_its_name(tmp_path):
    write_skill(tmp_path, "keep")
    write_skill(tmp_path, "off-one")
    skills.reload_skills(tmp_path)
    skills.set_disabled_source(lambda: {"off-one"})

    assert sorted(skills.repo_skills()) == ["keep", "off-one"]
    assert [s.name for s in skills.selectable_skills("web")] == ["keep"]
    assert load("off-one").startswith("오류:")
    assert skills.db_skill_problem("off-one", "설명", "본문") == "저장소 절차와 이름이 같습니다"


def test_disabled_or_missing_server_skill_is_skipped_quietly(tmp_path, caplog):
    write_skill(tmp_path, "mail-reply-style", channels="mail")
    skills.reload_skills(tmp_path)
    skills.set_disabled_source(lambda: {"mail-reply-style"})
    with caplog.at_level(logging.WARNING, logger="agent.skills"):
        assert skills.applied_skills("mail", rejecting=True) == []
        skills.applied_skills("mail", rejecting=True)
    messages = [r.getMessage() for r in caplog.records]
    assert not [r for r in caplog.records if r.levelname == "ERROR"]
    # 꺼진 mail-reply-style은 말없이, 파일이 없는 revise-after-reject는 경고 한 번
    assert len([m for m in messages if "revise-after-reject" in m]) == 1
    assert not [m for m in messages if "mail-reply-style" in m]


def test_disabled_lookup_failure_keeps_everything_on(tmp_path):
    write_skill(tmp_path, "keep")
    skills.reload_skills(tmp_path)

    def broken():
        raise RuntimeError("no table")

    skills.set_disabled_source(broken)
    assert [s.name for s in skills.selectable_skills("web")] == ["keep"]


# ---------------------------------------------------------------- 검색

def test_search_ranks_repository_skills_by_question_words():
    skills.reload_skills()
    web = skills.selectable_skills("web")

    top = skills.search_skills("입찰 사양서 조건에 맞는 모델", web)
    assert top[0][0].name == "spec-compare"
    assert skills.search_skills("KC 인증서 보내 주세요", web)[0][0].name == "certification-bundle"
    assert skills.search_skills("", web) == []
    # 메일 채널 전용·서버 적용 절차는 검색되지 않는다
    assert all(s.name not in skills.SERVER_CHOSEN for s, _ in skills.search_skills("메일 답장 문체", web))


def test_search_skills_tool_output():
    skills.reload_skills()
    found = search("입찰 사양 대조")
    assert found.startswith("[절차 검색") and "- spec-compare (점수" in found
    none = search("zzzz")
    assert "맞는 절차가 없습니다" in none and "spec-compare" in none


def test_prompt_mentions_search_skills(agent_env):
    skills.reload_skills()
    model = agent_env.install([AIMessage(content="답\n근거: 없음")])
    from agent import agent as agent_module
    agent_module.run_agent("질문", mode="local", owner=Owner("session", "s1"))
    prompt = next(m.content for m in model.calls[0] if isinstance(m, SystemMessage))
    assert "search_skills" in prompt


# ---------------------------------------------------------------- 참고 파일

def test_support_files_are_listed_and_readable(tmp_path):
    """SKILL 폴더의 다른 파일은 폴더·종류와 관계없이 목록에 오르고 읽힌다 (표준 형식의 agents/·scripts/·assets/ 등)."""
    write_skill(tmp_path, "big", body="본문. 모델 목록은 references/models.md를 본다.")
    folder = tmp_path / "big"
    for relative, text in {"references/models.md": "# 모델 목록\nA-100\n", "scripts/run.py": "print(1)\n",
                           "agents/grader.md": "채점", "eval-viewer/viewer.html": "<p>보기</p>"}.items():
        (folder / relative).parent.mkdir(parents=True, exist_ok=True)
        (folder / relative).write_text(text, encoding="utf-8")
    (folder / "assets").mkdir()
    (folder / "assets" / "logo.png").write_bytes(b"\x89PNG\r\n\x00\x00binary")
    (folder / "__pycache__").mkdir()
    (folder / "__pycache__" / "x.pyc").write_bytes(b"\x00")
    (folder / ".git").mkdir()
    (folder / ".git" / "HEAD").write_text("ref", encoding="utf-8")
    (tmp_path / "secret.md").write_text("폴더 밖", encoding="utf-8")
    skills.reload_skills(tmp_path)

    assert skills.repo_skills()["big"].files == (
        "agents/grader.md", "assets/logo.png", "eval-viewer/viewer.html", "references/models.md", "scripts/run.py")
    body = load("big")
    assert "[참고 파일]" in body and "- references/models.md" in body
    assert load("big", "references/models.md").endswith("# 모델 목록\nA-100\n")
    assert load("big", "references\\models.md").startswith("[업무 절차 big 참고 파일")
    assert load("big", "scripts/run.py").endswith("print(1)\n")
    assert "글자가 아닌 파일" in load("big", "assets/logo.png")
    for bad in ("../secret.md", "SKILL.md", "__pycache__/x.pyc", ".git/HEAD", "/etc/passwd"):
        assert load("big", bad).startswith("오류:"), bad


def test_skill_can_be_loaded_by_folder_name(tmp_path):
    write_skill(tmp_path, "folder-name", name="declared-name", body="본문")
    skills.reload_skills(tmp_path)
    assert load("declared-name").endswith("본문") and load("folder-name").endswith("본문")


def test_new_support_file_is_picked_up(tmp_path):
    write_skill(tmp_path, "big")
    skills.reload_skills(tmp_path)
    assert skills.repo_skills()["big"].files == ()
    (tmp_path / "big" / "references").mkdir()
    (tmp_path / "big" / "references" / "a.md").write_text("자료", encoding="utf-8")
    assert skills.repo_skills()["big"].files == ("references/a.md",)


def test_long_support_file_is_read_whole(tmp_path):
    write_skill(tmp_path, "big")
    (tmp_path / "big" / "references").mkdir()
    (tmp_path / "big" / "references" / "long.txt").write_text("가" * 100000, encoding="utf-8")
    skills.reload_skills(tmp_path)
    assert load("big", "references/long.txt").endswith("가" * 100000)


def test_standard_skill_folder_loads():
    """저장소의 skill-creator(표준 Agent Skills, 본문 3만 자대)도 읽힌다."""
    loaded = skills.reload_skills()
    assert "skill-creator" in loaded and len(loaded["skill-creator"].body) > 6000
    assert "references/schemas.md" in loaded["skill-creator"].files and skills.repo_errors() == {}


def test_repository_answer_skills_still_load():
    loaded = skills.reload_skills()
    assert set(REPO_ANSWER_SKILLS) <= set(loaded)
