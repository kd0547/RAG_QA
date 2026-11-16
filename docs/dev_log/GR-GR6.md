# GR-GR6 프롬프트 v4와 절차 문서

## 변경 파일
- `agent/prompt.py`: `PROMPT_V4_NAME`, `PROMPT_V4_TEMPLATE`(v3 상수에서 세 곳만 바꿔 만든다: 별칭 줄 삭제, graph_search 행 교체, 상위 개념 문장 → 인증 묶음·제품군 두 줄), `SYSTEM_PROMPT_TEMPLATE = PROMPT_V4_TEMPLATE`. `GRAPH_SEARCH_ROW_V4`, `PRODUCT_LINE_RULE`
- `repository/prompt_repository.py`: `ensure_v4()`
- `main.py`: 서버 시작 때 `ensure_v4()` (v2·v3 다음)
- `skills/certification-bundle/SKILL.md`: version 3, 절차 1 교체, 절차 6 추가. 나머지 그대로
- `docs/prompt_v4.md` (신규): 바뀐 곳과 전문
- 테스트: `tests/test_prompt_v4.py`(신규), `tests/test_prompt_v3.py`(기본값이 v4, certification-bundle은 version 3)

## 결정한 것
- v4 본문은 문자열을 따로 적지 않고 v3 상수에 세 바꾸기를 적용해 만든다 (각 바꿀 곳이 정확히 한 번 있는지 검사). "v3 본문에서 아래만 바꾼다"를 코드가 보장하게 하려는 것이다. `docs/prompt_v4.md`의 코드 블록이 그 결과와 같은지 테스트가 확인한다.
- GR1에서 넣은 옛 프롬프트 렌더링 정리(`strip_legacy_concepts`)는 그대로 둔다. v4에는 지울 문구가 없어 렌더링 결과가 본문과 같다.
- 다른 절차 문서(mail-reply-style, revise-after-reject, spec-compare)는 바꾸지 않았다. 절차·도구 설명에 상위 개념을 펼친다는 문구는 남지 않았다("펼쳐 주지 않는다"는 부정 문장만 있다).
- `agent/prompt.py`의 `PROMPT_V2_TEMPLATE`·`PROMPT_V3_TEMPLATE` 상수에는 옛 문구가 그대로 있다. DB의 v2·v3 행과 같은 원문을 지키라는 규칙(v2·v3 행은 그대로) 때문이며, 렌더링 때 `strip_legacy_concepts`가 지운다. v4 상수를 만들 때 이 원문에서 바꿀 곳을 찾는 데도 쓴다.

## 테스트: 명령과 출력
```
$ .venv/Scripts/python.exe -m pytest tests/test_prompt_v4.py tests/test_prompt_v3.py -q
.........                                                                [100%]
9 passed in 5.76s
$ .venv/Scripts/python.exe -m pytest tests -q
564 passed in 82.04s (0:01:22)
```

## 확인하지 못한 것 / Gemini에게 요청할 검증
- 실모델이 "제품군은 하위 모델별로 나눠 답한다" 규칙을 따르는지는 GR8 실서버 확인(`/ask` "A650 GPU 알려줘").

## 커밋 해시
GR-summary.md에 모은다.
