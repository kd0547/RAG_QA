"""C2: 맥락 예산 미들웨어 (오래된 도구 결과 축약, 실행당 도구·모델 호출 한도)."""
import json

import pytest
from langchain_core.messages import AIMessage, ToolMessage

import config
from agent.evidence_context import Owner
from conftest import tool_call
from entity.file import create_file
from parser.pdf.type import PageText

OWNER = Owner("task", "t1")


@pytest.fixture
def guide(agent_env, tmp_path):
    file = create_file(original_name="guide.pdf", stored_path=str(tmp_path / "g.pdf"))
    agent_env.file_repo.file_save(file)
    agent_env.page_repo.save_pages(file.file_id, [PageText(p, f"{p}페이지 " + "사양 " * 150) for p in range(1, 6)])
    return file.file_id


def _tool_contents(messages) -> dict:
    """도구 호출 ID → 모델이 받은 도구 결과 본문."""
    return {m.tool_call_id: m.content for m in messages if isinstance(m, ToolMessage)}


def test_old_tool_results_become_placeholder_but_evidence_list_stays(agent_env, guide, monkeypatch):
    from agent import agent as agent_module

    monkeypatch.setattr(config, "CTX_CLEAR_TRIGGER_TOKENS", 300)
    first_call = AIMessage(content="", tool_calls=[
        {"name": "list_evidence", "args": {}, "id": "ev"},
        {"name": "read_pages", "args": {"file_id": guide, "pages": [1]}, "id": "r1"},
    ])
    model = agent_env.install([
        first_call,
        tool_call("read_pages", {"file_id": guide, "pages": [2]}, "r2"),
        tool_call("read_pages", {"file_id": guide, "pages": [3]}, "r3"),
        tool_call("read_pages", {"file_id": guide, "pages": [4]}, "r4"),
        AIMessage(content="끝\n근거: 없음"),
    ])

    agent_module.run_agent_temp_attachments("사양", mode="local", owner=OWNER)

    fifth = _tool_contents(model.calls[4])
    assert fifth["r1"] == agent_module.CLEARED_TOOL_PLACEHOLDER
    assert fifth["r2"] != agent_module.CLEARED_TOOL_PLACEHOLDER  # 최근 3개는 그대로
    assert fifth["ev"] == "등록된 근거가 없습니다."          # list_evidence는 지우지 않는다
    assert json.loads(fifth["r4"])["pages"][0]["page"] == 4
    # 축약은 모델 입력에만 적용된다. 근거는 그대로 남아 list_evidence로 다시 볼 수 있다
    assert len(agent_env.evidence_repo.list_for_owner("task", "t1")) == 4


def test_spec_results_are_not_cleared(agent_env, guide, monkeypatch):
    """여러 모델을 대조할 때 앞서 받은 사양 값이 지워지지 않는다 (지워지면 마지막 모델 값만 남았다)."""
    from agent import agent as agent_module

    monkeypatch.setattr(config, "CTX_CLEAR_TRIGGER_TOKENS", 300)
    repo = agent_env.spec_repo
    repo.create_attribute("weight_kg", "무게", "body", "number", "kg")
    product = repo.create_product("A650-GA70-OU01")
    repo.add_spec("product", product["id"], "weight_kg", "2.16")
    model = agent_env.install([
        tool_call("get_specs", {"owner_type": "product", "owner_id": "A650-GA70-OU01"}, "s1"),
        tool_call("read_pages", {"file_id": guide, "pages": [1]}, "r1"),
        tool_call("read_pages", {"file_id": guide, "pages": [2]}, "r2"),
        tool_call("read_pages", {"file_id": guide, "pages": [3]}, "r3"),
        tool_call("read_pages", {"file_id": guide, "pages": [4]}, "r4"),
        AIMessage(content="끝\n근거: 없음"),
    ])

    agent_module.run_agent_temp_attachments("사양", mode="local", owner=OWNER)

    last = _tool_contents(model.calls[5])
    assert last["r1"] == agent_module.CLEARED_TOOL_PLACEHOLDER  # 문서 읽기 결과는 예전처럼 지운다
    assert last["s1"] != agent_module.CLEARED_TOOL_PLACEHOLDER and "2.16" in last["s1"]


def test_no_clearing_below_trigger(agent_env, guide):
    from agent import agent as agent_module

    model = agent_env.install([
        tool_call("read_pages", {"file_id": guide, "pages": [1]}, "r1"),
        tool_call("read_pages", {"file_id": guide, "pages": [2]}, "r2"),
        tool_call("read_pages", {"file_id": guide, "pages": [3]}, "r3"),
        tool_call("read_pages", {"file_id": guide, "pages": [4]}, "r4"),
        AIMessage(content="끝\n근거: 없음"),
    ])

    agent_module.run_agent_temp_attachments("사양", mode="local", owner=OWNER)

    assert agent_module.CLEARED_TOOL_PLACEHOLDER not in _tool_contents(model.calls[4]).values()


def test_search_documents_limited_per_run(agent_env, monkeypatch):
    from types import SimpleNamespace

    from agent import agent as agent_module
    from tools import tool as tools

    monkeypatch.setattr(tools, "get_embedding_model", lambda: SimpleNamespace(embed_query=lambda q: [0.0]))
    searched = []
    monkeypatch.setattr(tools, "search", lambda **kw: searched.append(kw) or [])
    model = agent_env.install(
        [tool_call("search_documents", {"query": f"q{i}"}, f"s{i}") for i in range(7)]
        + [AIMessage(content="못 찾음\n근거: 없음")]
    )

    agent_module.run_agent_temp_attachments("x", mode="local", owner=OWNER)

    assert len(searched) == 6
    last = _tool_contents(model.calls[-1])["s6"]
    assert "Tool call limit exceeded" in last


def test_middleware_order_and_settings():
    from agent import agent as agent_module

    from conftest import ScriptedModel

    middleware = agent_module.build_middleware(ScriptedModel())
    names = [m.name for m in middleware]
    assert names[1:] == [
        "ContextEditingMiddleware", "SummarizationMiddleware", "ToolCallLimitMiddleware[search_documents]",
        "ToolCallLimitMiddleware", "ModelCallLimitMiddleware",  # SKILL 도구에는 따로 한도가 없다
    ]
    summary = middleware[2]
    assert summary.trigger == ("tokens", config.CTX_SUMMARY_TRIGGER_TOKENS)  # 비율 기준이 아니다
    assert "근거 ID(e…)" in agent_module.SUMMARY_PROMPT and "{messages}" in agent_module.SUMMARY_PROMPT
    assert (config.CTX_CLEAR_TRIGGER_TOKENS, config.CTX_SUMMARY_TRIGGER_TOKENS) == (80000, 120000)
    editing = middleware[1]
    # 사양 조회·비교 결과는 지우지 않는다 (여러 모델 대조에서 앞 모델의 값을 잃지 않게)
    assert {"list_evidence", "load_skill", "get_specs", "compare_specs"} <= set(editing.edits[0].exclude_tools)
