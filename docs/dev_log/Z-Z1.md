# Z-Z1 프롬프트 v3와 절차 문서 교체

## 변경 파일
- `agent/prompt.py`
  - `PROMPT_V2_TEMPLATE`: 지금까지의 `SYSTEM_PROMPT_TEMPLATE` 본문을 **그대로** 옮긴 상수 (바이트 단위로 같은지 확인함)
  - `PROMPT_V3_NAME = "v3 근거 ID·사양"`, `PROMPT_V3_TEMPLATE`: [prompt_v3.md](../prompt_v3.md)의 코드 블록 본문을 그대로 (끝 줄바꿈 하나는 v2 상수와 같은 형식)
  - `SYSTEM_PROMPT_TEMPLATE = PROMPT_V3_TEMPLATE` (기본값을 v3로)
- `repository/prompt_repository.py`: `ensure_v2()`는 `PROMPT_V2_TEMPLATE`로(기본값이 v3로 바뀌어도 v2 이름에 v3 본문이 들어가지 않게), `ensure_v3()` 추가
- `main.py` lifespan: `ensure_v2()` 다음에 `ensure_v3()`
- `skills/{certification-bundle,mail-reply-style,revise-after-reject,spec-compare}/SKILL.md`: `docs/skills_next/`의 같은 이름 문서로 **그대로 덮어썼다** (`cmp`로 바이트 동일 확인). 네 문서 모두 `version: "2"`
- `docs/skills_next/` 삭제
- `tests/test_prompt_v2.py`: v2 테스트가 `PROMPT_V2_TEMPLATE`를 보게 했다 (기본값이 v3로 바뀌었으므로)
- `tests/test_customer_history.py`: v3 시스템 프롬프트에 "이전 문의 목록"이라는 말이 들어 있어, 안내 줄 검사를 대괄호 안내 줄(`[이 발신자의 이전 문의`)로 좁혔다
- `tests/test_prompt_v3.py`(신규) 4건

## 동작
- 운영 DB에 `v2 근거 ID`가 있고 선택돼 있으면, 재시작 때 `v3 근거 ID·사양`이 한 번 들어가고 선택된다. v2 행은 지우거나 고치지 않는다.
- 담당자가 나중에 다른 프롬프트를 고르면 다시 켜도 그 선택이 유지된다 (`ensure_seeded` 규칙 그대로).
- **설정으로 꺼진 도구가 프롬프트 표에 남는 것은 그대로 둔다** (지시서 Z1-4). `SPEC_TOOLS_ENABLED=0`이나 `CUSTOMER_HISTORY_ENABLED=0`이면 표에는 이름이 있지만 도구 목록에 없어 모델이 부를 수 없다 (부르면 LangChain이 "없는 도구" 오류 메시지를 돌려준다).

## 절차 본문의 도구 이름 검사
`tests/test_skills.py::test_skill_bodies_only_mention_existing_tools`(검사 접두어에 `get_`·`compare_`가 이미 있다)가 그대로 통과한다. 새 절차 본문이 가리키는 도구: `list_spec_attributes`, `search_spec_items`, `compare_specs`, `get_specs`, `read_attachment`, `read_pages`, `grep_documents`, `search_documents`, `graph_search`, `list_evidence` — 모두 도구 목록에 있다.

## 테스트: 명령과 출력
```
.venv/Scripts/python.exe -m pytest tests -q
453 passed in 59.43s
```
- `test_v3_is_prompt_doc_code_block_verbatim`: 상수가 문서의 코드 블록과 같다, 기본값이 v3, `$aliases` 치환
- `test_v3_table_names_existing_tools_only`: 표의 도구 이름이 모두 실제 도구
- `test_ensure_v3_once_and_v2_row_untouched`: v3 한 번 등록·선택, v2 행 그대로, 재시작에도 한 번, 담당자 선택 유지
- `test_replaced_skill_documents_are_version_2_and_load`: 네 문서 `version: "2"`, 로더 검사 통과, `docs/skills_next` 없음

## 고치지 않은 것
- 프롬프트 본문과 절차 본문은 설계자 소유라 한 글자도 바꾸지 않았다 (지시서 0-7).
