"""사용자 문서 그룹 설명이 매 질문의 검색 힌트로 들어가는지 확인한다."""

import json

from agent.prompt import render_prompt


def test_group_catalog_is_added_as_search_hint_only():
    groups = [
        {"id": "certificate", "name": "인증서", "description": "KC 안전확인과 적합등록 인증서", "file_count": 2},
    ]

    prompt = render_prompt("기본 지침\n$aliases", {"N5800": ["엔오팔공공"]}, groups)

    assert "N5800 = 엔오팔공공" in prompt
    assert "검색 범위를 고를 때만" in prompt
    assert "답변의 근거로도 사용하지 마세요" in prompt
    assert json.dumps([{"id": "certificate", "name": "인증서", "description": "KC 안전확인과 적합등록 인증서"}], ensure_ascii=False) in prompt
    assert "file_count" not in prompt


def test_prompt_without_groups_has_no_catalog():
    assert render_prompt("기본 지침", {}, []) == "기본 지침"
