"""Z1: 프롬프트 v3(근거 ID·사양)와 절차 문서 교체."""
import re
from pathlib import Path

from agent.prompt import (
    PROMPT_V2_NAME, PROMPT_V2_TEMPLATE, PROMPT_V3_NAME, PROMPT_V3_TEMPLATE, SYSTEM_PROMPT_TEMPLATE, render_prompt,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOL_WORD = re.compile(r"\b(?:read|list|grep|search|graph|load|rerank|get|compare)_[a-z_]+")


def test_v3_is_prompt_doc_code_block_verbatim():
    doc = (PROJECT_ROOT / "docs" / "prompt_v3.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    [block] = re.findall(r"```text\n(.*?)\n```", doc, re.S)
    assert PROMPT_V3_TEMPLATE.template == block + "\n"
    assert PROMPT_V3_NAME == "v3 근거 ID·사양"
    assert SYSTEM_PROMPT_TEMPLATE is not PROMPT_V3_TEMPLATE  # 기본값은 v4 (GR6)
    rendered = render_prompt(PROMPT_V3_TEMPLATE.template)
    for removed in ("$aliases", "용어 별칭", "상위 개념"):
        assert removed not in rendered
    # CRLF로 저장된 옛 본문도 같다
    assert "상위 개념" not in render_prompt(PROMPT_V3_TEMPLATE.template.replace("\n", "\r\n"))


def test_v3_table_names_existing_tools_only():
    from agent.agent import BASE_TOOLS, SPEC_TOOLS, get_customer_history

    all_tools = {t.name for t in [*BASE_TOOLS, *SPEC_TOOLS, get_customer_history]}
    mentioned = set(TOOL_WORD.findall(PROMPT_V3_TEMPLATE.template))
    assert mentioned and mentioned <= all_tools, mentioned - all_tools
    assert {"get_specs", "compare_specs", "search_spec_items", "list_spec_attributes", "get_customer_history",
            "load_skill"} <= mentioned


def test_ensure_v3_once_and_v2_row_untouched(agent_env):
    repo = agent_env.prompt_repo
    repo.ensure_default()
    v2 = repo.ensure_v2()

    v3 = repo.ensure_v3()

    assert v3 is not None and v3.name == PROMPT_V3_NAME and v3.is_selected
    assert repo.get(v2.id).content == PROMPT_V2_TEMPLATE.template and repo.get(v2.id).name == PROMPT_V2_NAME
    assert repo.get_system_prompt() == PROMPT_V3_TEMPLATE.template
    # 다시 켜도(ensure_* 재호출) 한 번만 있고, 담당자가 고른 프롬프트가 유지된다
    repo.select(v2.id)
    repo.ensure_default()
    assert repo.ensure_v2() is None and repo.ensure_v3() is None
    names = [p.name for p in repo.list_all()]
    assert names.count(PROMPT_V3_NAME) == 1 and names.count(PROMPT_V2_NAME) == 1
    assert repo.get_selected().id == v2.id


def test_replaced_skill_documents_are_version_2_and_load():
    from agent.skills import load_skills

    loaded = load_skills(PROJECT_ROOT / "skills")
    for name in ("certification-bundle", "mail-reply-style", "revise-after-reject", "spec-compare"):
        text = (PROJECT_ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
        assert ('version: "3"' if name == "certification-bundle" else 'version: "2"') in text, name  # GR6
        assert name in loaded, name
    assert "compare_specs" in loaded["spec-compare"].body
    assert not (PROJECT_ROOT / "docs" / "skills_next").exists()
