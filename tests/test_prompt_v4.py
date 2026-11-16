"""GR6: 프롬프트 v4(근거 ID·사양·그래프 정비)와 인증 묶음 절차 version 3."""
import re
from pathlib import Path

from agent.prompt import (
    PROMPT_V2_TEMPLATE, PROMPT_V3_NAME, PROMPT_V3_TEMPLATE, PROMPT_V4_NAME, PROMPT_V4_TEMPLATE, SYSTEM_PROMPT_TEMPLATE,
    render_prompt,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOL_WORD = re.compile(r"\b(?:read|list|grep|search|graph|load|rerank|get|compare)_[a-z_]+")


def test_v4_is_v3_with_three_changes_and_matches_doc():
    doc = (PROJECT_ROOT / "docs" / "prompt_v4.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    [block] = re.findall(r"```text\n(.*?)\n```", doc, re.S)
    assert PROMPT_V4_TEMPLATE.template == block + "\n"
    assert PROMPT_V4_NAME == "v4 근거 ID·사양·그래프 정비"
    assert SYSTEM_PROMPT_TEMPLATE is PROMPT_V4_TEMPLATE
    v3_lines = PROMPT_V3_TEMPLATE.template.splitlines()
    v4_lines = PROMPT_V4_TEMPLATE.template.splitlines()
    removed = [line for line in v3_lines if line not in v4_lines]
    added = [line for line in v4_lines if line not in v3_lines]
    assert len(removed) == 4 and len(added) == 3  # 별칭 2줄 + graph_search 행 + 상위 개념 줄 / 새 행 + 두 줄
    assert "matched의 ref_type·ref_id는 get_specs에 넘길 수 있다" in PROMPT_V4_TEMPLATE.template


def test_rendered_v4_has_no_concepts_and_has_product_line_rule():
    rendered = render_prompt(PROMPT_V4_TEMPLATE.template)
    assert rendered == PROMPT_V4_TEMPLATE.template  # 렌더링 때 지울 옛 문구가 없다
    for removed in ("상위 개념", "용어 별칭", "$aliases"):
        assert removed not in rendered
    assert "- 제품군(예: A650)은 판매 모델이 아니다." in rendered
    assert "인증 묶음 이름(예: KC 인증)은 시스템이 속한 종류로 펼쳐 주지 않는다" in rendered


def test_v4_table_names_existing_tools_only():
    from agent.agent import BASE_TOOLS, SPEC_TOOLS, get_customer_history

    all_tools = {t.name for t in [*BASE_TOOLS, *SPEC_TOOLS, get_customer_history]}
    mentioned = set(TOOL_WORD.findall(PROMPT_V4_TEMPLATE.template))
    assert mentioned and mentioned <= all_tools, mentioned - all_tools


def test_ensure_v4_once_and_old_rows_untouched(agent_env):
    repo = agent_env.prompt_repo
    repo.ensure_default()
    v2, v3 = repo.ensure_v2(), repo.ensure_v3()

    v4 = repo.ensure_v4()

    assert v4 is not None and v4.name == PROMPT_V4_NAME and v4.is_selected
    assert repo.get(v2.id).content == PROMPT_V2_TEMPLATE.template and repo.get(v3.id).content == PROMPT_V3_TEMPLATE.template
    assert repo.get_system_prompt() == PROMPT_V4_TEMPLATE.template
    repo.select(v3.id)
    assert repo.ensure_v2() is None and repo.ensure_v3() is None and repo.ensure_v4() is None
    names = [p.name for p in repo.list_all()]
    assert names.count(PROMPT_V4_NAME) == 1 and names.count(PROMPT_V3_NAME) == 1
    assert repo.get_selected().id == v3.id  # 담당자가 고른 프롬프트가 유지된다


def test_certification_bundle_version_3_without_expansion():
    from agent.skills import load_skills

    text = (PROJECT_ROOT / "skills" / "certification-bundle" / "SKILL.md").read_text(encoding="utf-8")
    assert 'version: "3"' in text
    loaded = load_skills(PROJECT_ROOT / "skills")
    body = loaded["certification-bundle"].body
    assert "펼쳐진다" not in body and "상위 개념" not in body
    assert "인증 묶음 이름(예: KC 인증)은 시스템이 속한 종류로 펼쳐 주지 않는다." in body
    assert '6. **묶음 이름으로만 물었으면**' in body
