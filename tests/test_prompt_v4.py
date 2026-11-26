"""GR6: 프롬프트 v4(근거 ID·사양·그래프 정비)."""
import re

from agent.prompt import (
    BUNDLE_RULE, PROMPT_V4_NAME, PROMPT_V4_TEMPLATE, SYSTEM_PROMPT_TEMPLATE,
    render_prompt,
)

TOOL_WORD = re.compile(r"\b(?:read|list|grep|search|graph|load|rerank|get|compare)_[a-z_]+")


def test_v4_is_the_only_prompt_and_default():
    import agent.prompt as prompt

    assert PROMPT_V4_NAME == "v4 근거 ID·사양·그래프 정비"
    assert SYSTEM_PROMPT_TEMPLATE is PROMPT_V4_TEMPLATE
    assert not any(name.startswith(("PROMPT_V2", "PROMPT_V3")) for name in dir(prompt))
    assert "matched의 ref_type·ref_id는 get_specs에 넘길 수 있다" in PROMPT_V4_TEMPLATE.template
    assert "$aliases" not in PROMPT_V4_TEMPLATE.template


def test_rendered_v4_has_no_concepts_and_has_product_line_rule():
    rendered = render_prompt(PROMPT_V4_TEMPLATE.template)
    # 렌더링 때 지우는 것은 묶음을 펼치지 않는다는 규칙 한 줄뿐이다 (용어집 묶음은 graph_search가 펼친다)
    assert rendered == PROMPT_V4_TEMPLATE.template.replace(BUNDLE_RULE + "\n", "")
    for removed in ("상위 개념", "용어 별칭", "$aliases"):
        assert removed not in rendered
    assert "- 제품군(예: A650)은 판매 모델이 아니다." in rendered
    assert BUNDLE_RULE in PROMPT_V4_TEMPLATE.template and "인증 묶음 이름(예: KC 인증)" not in rendered


def test_v4_table_names_existing_tools_only():
    from agent.agent import BASE_TOOLS, SPEC_TOOLS, get_customer_history

    all_tools = {t.name for t in [*BASE_TOOLS, *SPEC_TOOLS, get_customer_history]}
    mentioned = set(TOOL_WORD.findall(PROMPT_V4_TEMPLATE.template))
    assert mentioned and mentioned <= all_tools, mentioned - all_tools


def test_ensure_v4_once_and_keeps_chosen_prompt(agent_env):
    repo = agent_env.prompt_repo
    default = repo.ensure_default()

    v4 = repo.ensure_v4()

    assert v4 is not None and v4.name == PROMPT_V4_NAME and v4.is_selected
    assert repo.get_system_prompt() == PROMPT_V4_TEMPLATE.template
    repo.select(default.id)
    assert repo.ensure_v4() is None
    assert [p.name for p in repo.list_all()].count(PROMPT_V4_NAME) == 1
    assert repo.get_selected().id == default.id  # 담당자가 고른 프롬프트가 유지된다
