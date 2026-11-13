"""E3: 사양 도구 4개와 근거 등록 (get_specs·compare_specs만 근거, 후보 목록은 근거가 아니다)."""
import json

import pytest
from langchain_core.messages import AIMessage

import config
from agent.evidence_context import Owner, owner_scope, run_scope
from conftest import tool_call

OWNER = Owner("task", "t1")


@pytest.fixture
def specs(agent_env):
    repo = agent_env.spec_repo
    repo.create_attribute("ram_gb", "메모리 용량", "memory", "number", "GB")
    repo.create_attribute("weight_kg", "무게", "body", "number", "kg")
    product = repo.create_product("N5800")
    repo.add_spec("product", product["id"], "ram_gb", "16GB")
    repo.add_spec("product", product["id"], "ram_gb", "32GB", is_option=True)
    repo.add_spec("product", product["id"], "weight_kg", "1.5kg")
    other = repo.create_product("A650")
    repo.add_spec("product", other["id"], "ram_gb", "16GB")
    return {"n5800": product["id"], "a650": other["id"]}


def _content(messages) -> dict:
    return json.loads(messages[-1].content)


def test_get_specs_registers_evidence_and_citation_passes(agent_env, specs):
    from agent import agent as agent_module

    def cite(messages):
        result = _content(messages)
        assert result["model"] == "N5800" and len(result["values"]) == 3
        return AIMessage(content=f"N5800 무게는 1.5kg입니다.\n근거: {result['evidence_id']}")

    agent_env.install([tool_call("get_specs", {"owner_type": "product", "owner_id": specs["n5800"]}), cite])
    out = agent_module.run_agent_temp_attachments("N5800 무게", mode="local", owner=OWNER)

    assert out["validation"]["ok"] is True and len(out["validation"]["cited_ids"]) == 1
    [source] = out["sources"]
    assert source["source"] == "사양 DB: N5800" and source["file_id"] is None and source["origin_type"] == "spec_value"
    assert "무게(weight_kg) = 1.5kg" in source["text"] and "메모리 용량(ram_gb) = 32GB [옵션]" in source["text"]


def test_compare_specs_registers_one_evidence_per_target(agent_env, specs):
    from agent import agent as agent_module

    seen = {}

    def cite(messages):
        result = _content(messages)
        seen.update(result)
        ids = [t["evidence_id"] for t in result["targets"]]
        return AIMessage(content=f"N5800은 옵션으로 만족, A650은 만족하지 않습니다.\n근거: {', '.join(ids)}")

    condition = {"attribute": "ram_gb", "op": ">=", "value": "32", "unit": "GB"}
    agent_env.install([
        tool_call("compare_specs", {"owner_type": "product", "owner_ids": [specs["n5800"], "A650"], "conditions": [condition]}),
        cite,
    ])
    out = agent_module.run_agent_temp_attachments("RAM 32GB 이상?", mode="local", owner=OWNER)

    assert [(t["model"], t["results"][0]["verdict"]) for t in seen["targets"]] == [("N5800", "met_with_option"), ("A650", "not_met")]
    assert len({t["evidence_id"] for t in seen["targets"]}) == 2
    assert out["validation"]["ok"] is True and len(out["validation"]["cited_ids"]) == 2
    assert {s["source"] for s in out["sources"]} == {"사양 DB: N5800", "사양 DB: A650"}
    # 판정에 쓴 속성만 근거 본문에 들어간다
    assert all("weight_kg" not in s["text"] for s in out["sources"])


def test_search_only_answer_fails_validation(agent_env, specs):
    from agent import agent as agent_module

    def answer(messages):
        result = _content(messages)
        assert result["items"][0]["model"] == "N5800" and "evidence_id" not in json.dumps(result)
        return AIMessage(content="N5800이 있습니다.\n근거: e00000000")

    agent_env.install([tool_call("search_spec_items", {"query": "N5800"}), answer])
    out = agent_module.run_agent_temp_attachments("N5800 있어?", mode="local", owner=OWNER)

    assert out["validation"]["ok"] is False
    assert "근거를 읽지 않고 답변" in out["validation"]["errors"]
    assert agent_env.evidence_repo.list_for_owner("task", "t1") == []


def _call(tool, args, owner=OWNER, run="r1"):
    with owner_scope(owner), run_scope(run):
        return tool.invoke(args)


def test_same_call_twice_gives_same_evidence_id(agent_env, specs):
    from tools.tool import compare_specs, get_specs

    args = {"owner_type": "product", "owner_id": specs["n5800"]}
    first, second = _call(get_specs, args), _call(get_specs, args)
    assert first["evidence_id"] == second["evidence_id"]
    compare_args = {"owner_type": "product", "owner_ids": [specs["n5800"]],
                    "conditions": [{"attribute": "weight_kg", "op": "<=", "value": "1500g"}]}
    assert _call(compare_specs, compare_args)["targets"][0]["evidence_id"] == \
        _call(compare_specs, compare_args)["targets"][0]["evidence_id"]
    # 값을 고치면 새 근거
    spec_id = next(s["id"] for s in agent_env.spec_repo.get_product(specs["n5800"])["specs"] if s["attribute_key"] == "weight_kg")
    agent_env.spec_repo.update_spec(spec_id, value_text="1.4kg")
    assert _call(get_specs, args)["evidence_id"] != first["evidence_id"]


def test_other_tasks_spec_evidence_is_rejected(agent_env, specs):
    from agent.validation import validate_answer
    from tools.tool import get_specs

    theirs = _call(get_specs, {"owner_type": "product", "owner_id": specs["n5800"]}, owner=Owner("task", "t2"))["evidence_id"]
    run_id = agent_env.evidence_repo.start_run("task", "t1", "test", None)

    result = validate_answer(run_id, OWNER, f"1.5kg\n근거: {theirs}")

    assert f"이 질문의 근거가 아닌 ID 인용: {theirs}" in result.errors


def test_errors_are_results_not_exceptions(agent_env, specs):
    from tools.tool import compare_specs, get_specs, search_spec_items

    assert "error" in _call(get_specs, {"owner_type": "product", "owner_id": "없는모델"})
    assert "error" in _call(search_spec_items, {})
    assert "error" in _call(search_spec_items, {"query": "N5800", "owner_type": "phone"})
    result = _call(compare_specs, {"owner_type": "product", "owner_ids": [specs["n5800"], "없는모델"],
                                   "conditions": [{"attribute": "no_such_key", "op": ">=", "value": "1"}]})
    assert result["targets"][0]["results"][0]["verdict"] == "unknown"
    assert result["errors"] == ["사양 DB에 없는 대상입니다: product 없는모델"]
    # 에이전트 밖(실행 컨텍스트 없음)에서는 근거를 등록하지 않는다
    assert "error" in get_specs.invoke({"owner_type": "product", "owner_id": specs["n5800"]})


def test_empty_product_has_no_evidence(agent_env, specs):
    from tools.tool import get_specs

    empty = agent_env.spec_repo.create_product("EMPTY1")
    result = _call(get_specs, {"owner_type": "product", "owner_id": empty["id"]})
    assert result["evidence_id"] is None and result["values"] == [] and "값이 없습니다" in result["message"]


def test_spec_tools_switch_and_skill_author_tool_list(monkeypatch):
    from agent import agent as agent_module
    from agent import skill_author

    names = {"list_spec_attributes", "search_spec_items", "get_specs", "compare_specs"}
    assert names <= {t.name for t in agent_module.active_tools()}
    assert names <= set(skill_author.tool_names())  # 절차 초안 검사(I4)의 도구 목록에 자동으로 들어간다

    monkeypatch.setattr(config, "SPEC_TOOLS_ENABLED", False)
    assert not names & {t.name for t in agent_module.active_tools()}
    assert not names & set(skill_author.tool_names())
    assert {"read_pages", "graph_search", "load_skill"} <= {t.name for t in agent_module.active_tools()}


def test_disabled_spec_tools_are_not_bound_to_agent(agent_env, monkeypatch):
    monkeypatch.setattr(config, "SPEC_TOOLS_ENABLED", False)
    from agent import agent as agent_module

    agent = agent_module.create_rag_agent(agent_env.install([]))
    assert "get_specs" not in agent.nodes["tools"].bound.tools_by_name
    monkeypatch.setattr(config, "SPEC_TOOLS_ENABLED", True)
    agent = agent_module.create_rag_agent(agent_env.install([]))
    assert "get_specs" in agent.nodes["tools"].bound.tools_by_name


def test_tool_docstrings_state_rules():
    from tools.tool import compare_specs, search_spec_items

    assert "숫자 크기 비교와 단위 환산은 이 도구가 한다. 직접 계산하지 않는다." in compare_specs.description
    assert "결과는 후보다. 답에 쓰려면 get_specs나 compare_specs로 값을 읽는다." in search_spec_items.description
    for op in (">=", "<=", ">", "<", "==", "contains", "exists"):
        assert f'"{op}"' in compare_specs.description
    assert '"attribute": "ram_gb"' in compare_specs.description
