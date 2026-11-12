# 에이전트 평가셋

| 파일 | 내용 |
|------|------|
| `baseline_2026-11-12.json` | 개선 전 기준선. 운영 DB의 메일 103건과 당시 답변·출처·도구 호출 기록 (`export_baseline.py`로 추출) |
| `eval_set.json` | 기준선에서 고른 10문항. 개선 전후 비교(Gemini 지시서 C절)에 쓴다 |

## eval_set.json 문항 선정

`docs/gemini_verification_instructions.md` C-1의 목록대로 골랐다. 같은 질문이 반복된 SSD 대체품 시리즈(SSD2~SSD16)는 대표 1건만 넣었다.

각 문항에는 기준선 항목을 그대로 복사하고 아래 필드를 더했다.

- `eval_title`: 문항 이름 (C-1 목록의 표현)
- `why`: 이 문항이 무엇을 검증하는지 한 줄

**주간판매 문항(10번째)은 빈 자리다.** C-1은 "주간판매 질문 1건 (xlsx 표)"을 요구하지만 기준선 103건에 주간판매를 묻는 질문이 없다. 지어내지 않고 `missing_in_baseline: true`로 두었다. R&D 담당자가 질문을 정해 `question`을 채워야 한다.

## R&D 담당자가 채울 것

`expected_evidence`·`expected_keywords`는 비어 있다. 정답을 아는 사람(R&D 담당자)이 채운다. 비어 있는 문항은 Gemini가 UNVERIFIED로 두고 시간·도구 호출 수·근거 없는 수치처럼 측정 가능한 지표만 적는다.

- `expected_evidence`: 답변이 인용해야 하는 근거. 예: `[{"file": "N5800_14세대__Sales_Guide_V1.1_20260922.pdf", "page": 3}]`
- `expected_keywords`: 답변에 반드시 들어가야 하는 말·수치. 예: `["R-R-TGE-N5800", "1.5kg"]`
- "찾지 못함"이 정답인 문항(데스크탑 Sales Guide)은 `expected_evidence: []`, `expected_keywords: ["찾지 못"]`처럼 적는다.

## 실행 전제

기준선이 참조한 문서 17개(`documents_referenced`)는 개발 서버에만 있다. 로컬 DB에는 없으므로 비교 실행은 개발 서버에서 한다. 실행할 때 메일은 승인하지 않는다.
