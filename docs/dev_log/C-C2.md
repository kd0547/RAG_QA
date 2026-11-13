# C-C2 맥락 예산 미들웨어

## 변경 파일
- `agent/agent.py`: `build_middleware(summary_model)`. 순서: `_system_prompt` → `ContextEditingMiddleware(ClearToolUsesEdit(trigger=CTX_CLEAR_TRIGGER_TOKENS, keep=3, exclude_tools=("list_evidence",), placeholder="[축약됨 — list_evidence로 근거 ID를 다시 조회하세요]"))` → `SummarizationMiddleware(model=get_llm_model("local"), trigger=("tokens", CTX_SUMMARY_TRIGGER_TOKENS), keep=("messages", 12), summary_prompt=…)` → `ToolCallLimitMiddleware(tool_name="search_documents", run_limit=6)` → `ToolCallLimitMiddleware(run_limit=25)` → `ModelCallLimitMiddleware(run_limit=20, exit_behavior="end")`. 모델 호출 한도로 끝나면 run `limit` + `AgentRunError`
- `config.py`: `CTX_CLEAR_TRIGGER_TOKENS=24000`, `CTX_SUMMARY_TRIGGER_TOKENS=40000`, `AGENT_RECURSION_LIMIT=200` (환경변수로 덮어쓰기)
- `tests/test_context_budget.py`(신규), `tests/test_validation.py`(재귀 한도 테스트를 두 경우로 나눔)

## 결정한 것
1. **`recursion_limit` 40 → 200 (지시서 C1과 다름).** 미들웨어마다 그래프 노드가 생긴다 (`SummarizationMiddleware.before_model`, `ModelCallLimitMiddleware.before_model/after_model`, `ToolCallLimitMiddleware…after_model` ×2). 그래서 모델 호출 한 번에 약 7단계를 쓴다. 대역 모델로 잰 결과:

   | 도구 호출 수 | 미들웨어 + 40 | 미들웨어 없음 + 40 | 미들웨어 + 200 |
   |---|---|---|---|
   | 9 | 재귀 한도 초과 | 정상 | 정상 |
   | 19 | 재귀 한도 초과 | 정상 | 정상 |
   | 25 | 재귀 한도 초과 | 재귀 한도 초과 | `Model call limits exceeded: run limit (20/20)`로 정상 종료 |

   어제 실제 질문 1건이 도구를 8회 불렀으므로 40이면 평범한 질문도 실패한다. 지시서가 의도한 한도는 "모델 호출 20회"라고 보고, 그 한도가 먼저 걸리도록 200으로 올렸다. 재귀 한도 초과도 여전히 `limit`으로 기록된다 (테스트 유지).
2. **맥락 예산 값은 지시서 기본값 그대로 (24000 / 40000).** 로컬 모델 `qwen3.8-flash-next`의 최대 컨텍스트는 262,144토큰이다 (vLLM `GET /v1/models`의 `max_model_len`). 그래서 이 값들은 모델 한계가 아니라 비용·지연 예산이다. 근거: 2026-11-12 17:46 실제 `/ask` 1건이 모델 호출 9회에 입력 63,264토큰(호출당 평균 약 7,000)을 썼다. 24,000이면 도구 결과가 3~4개 쌓인 뒤 축약이 시작된다.
3. **요약 프롬프트는 langchain 기본문의 `<messages>` 앞에** 보존 지시(영어 + 한국어)를 넣었다: 근거 ID(e…), 제품 모델명, 수치, 인증번호, 반려 사유는 원문 그대로.
4. 요약 모델은 `build_agent`에서 항상 `get_llm_model("local")`이다. 테스트용 `create_rag_agent`는 요약 모델을 따로 주지 않으면 같은 모델을 쓴다.
5. `ClearToolUsesEdit`는 모델 입력에만 적용되고 저장된 대화(checkpoint)는 그대로다. 근거 행도 그대로라 `list_evidence`로 다시 볼 수 있다 (테스트로 확인).

## 테스트: 명령과 출력
```
.venv/Scripts/python.exe -m pytest tests/test_context_budget.py tests/test_validation.py::test_model_call_limit_is_recorded_as_limit tests/test_validation.py::test_recursion_limit_is_recorded_as_limit -v

tests/test_context_budget.py::test_old_tool_results_become_placeholder_but_evidence_list_stays PASSED [ 16%]
tests/test_context_budget.py::test_no_clearing_below_trigger PASSED      [ 33%]
tests/test_context_budget.py::test_search_documents_limited_per_run PASSED [ 50%]
tests/test_context_budget.py::test_middleware_order_and_settings PASSED  [ 66%]
tests/test_validation.py::test_model_call_limit_is_recorded_as_limit PASSED [ 83%]
tests/test_validation.py::test_recursion_limit_is_recorded_as_limit PASSED [100%]
============================== 6 passed in 5.95s ==============================
```
지시서 테스트: `list_evidence` + `read_pages` 4개가 쌓인 뒤 5번째 모델 호출 입력에서 첫 `read_pages` 결과는 자리표시자, 최근 3개는 그대로, `list_evidence` 결과는 남아 있다 (`test_old_tool_results_become_placeholder_but_evidence_list_stays`, 축약 기준을 300토큰으로 낮춰 실행).

## 확인하지 못한 것 / Gemini에게 요청할 검증
- 요약(40,000토큰)이 실제로 걸리는 긴 대화와, 요약 뒤 근거 ID 보존 여부는 실제 모델로 확인하지 않았다.
- `count_tokens_approximately`(글자 수 기반 근사)가 한국어 토큰 수를 얼마나 맞추는지 재지 않았다.

## 커밋 해시
- `26dcca0`
