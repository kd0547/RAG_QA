# D-D5 절차 문서 점검 (본문은 고치지 않았다)

`skills/*/SKILL.md` 4종을 현재 도구 동작, `mail/templates.py`, 운영 DB에서 선택된 프롬프트("v2 근거 ID", 읽기 전용 조회)와 대조했다. **본문은 고치지 않았다.** 코드도 바꾸지 않았다.

아래 표의 "어긋남"은 설계자(C)가 판단할 항목이다. 지시서의 "충돌"(코드가 지시서와 맞지 않아 구현을 멈춰야 하는 경우)에 해당하는 것은 없었다.

## 1. 본문과 현재 도구 동작

| 문서 | 본문 | 현재 동작 | 판단 |
|------|------|-----------|------|
| spec-compare | "read_attachment로 … 잘렸으면 next_offset으로 이어 읽는다" | `read_attachment`가 `next_offset`을 준다 (C2-P2). 단, `offset`은 **페이지 하나**를 읽을 때만 받는다 (여러 페이지 + offset → 오류) | 맞음. 이 제약은 도구 결과 안내문에 있다 (본문에는 없음) |
| spec-compare | graph_search·grep_documents로 후보 모델, search_documents 스니펫만 보고 적지 않음 | 도구 설명·프롬프트와 같음 | 맞음 |
| certification-bundle | "graph_search가 돌려준 문서와 페이지를 먼저 본다", 상위 개념이 펼쳐짐 | `graph_search` 결과 `documents`에 `file_id`·`pages`가 있고, 상위 개념은 속한 종류로 펼친다 | 맞음 |
| certification-bundle | "답장에 붙일 파일은 검토 담당자가 승인할 때 고른다" | 메일은 맞다 (검토 화면 첨부 선택). 이 문서는 `channels: "mail,web"`이라 웹 질문(`/ask`)에도 쓰이는데, 웹에는 검토 담당자·답장 첨부가 없다 | **어긋남(경미)**: 웹에서 읽히면 이 문장이 상황과 맞지 않는다 |
| revise-after-reject | "`[검토 담당자 반려]` 메시지" | `mail/email_service.py`가 `[검토 담당자 반려]\n…`로 넣는다 | 맞음 |
| revise-after-reject | 사실 오류: "list_evidence로 근거를 확인하고, 해당 페이지를 read_pages로 다시 읽어" | `list_evidence`가 근거 원천(`file_page`·`attachment` 등)을 보여 준다. 근거가 **첨부**면 `read_pages`가 아니라 `read_attachment`로 다시 읽어야 한다 | **어긋남**: 첨부 근거의 다시 읽기 도구가 본문에 없다 |
| revise-after-reject | "이미 읽은 근거는 evidence_id로 다시 인용할 수 있다" | 근거 검증의 '읽음' 확인은 같은 소유자(같은 메일 대화) 전체 기준이다 (B6/C3) | 맞음 |
| 4종 공통 | 도구 이름 | 본문에 나오는 `read_·list_·grep_·search_·graph_…` 낱말은 모두 `TOOLS`에 있다 (`test_skill_bodies_only_mention_existing_tools`) | 맞음 |

## 2. `mail-reply-style`의 "메일 틀과 문의 원문은 서버가 붙인다"
`mail/templates.py` `render_answer_email(answer, question)` (승인 API `app/routers/mails.py`가 `question=task.body`로 부른다)이 붙이는 것:
- 머리: "문의하신 내용에 대한 답변입니다" / "문의해주신 내용에 대해 아래와 같이 답변드립니다."
- "문의하신 내용" 칸에 문의 원문 (`question`이 비어 있지 않을 때)
- "답변" 칸에 초안 (마크다운 → HTML)
- 꼬리: "본 메일은 문의 내용에 대한 답변 안내 메일입니다."

→ **맞음.** 다만 서버 틀에는 **서명이 없다.** 이 절차는 초안에 서명을 쓰지 말라고 하므로, 담당자가 편집하지 않으면 답장이 서명 없이 나간다. (사실만 적는다. 정할지는 설계자·사용자)

## 3. 시스템 프롬프트 v2와 절차 문서가 다르게 말하는 곳

| 위치 | 프롬프트 v2 | 절차 문서 | 판단 |
|------|-------------|-----------|------|
| revise-after-reject "사실 오류" 1 | "답변에 쓰는 사실과 수치는 반드시 read_pages 또는 read_attachment로 읽은 페이지에 있어야 한다" | "담당자가 올바른 값을 적어 줬으면 그 값으로 고친다" | **다름.** 담당자가 준 값은 읽은 페이지에 없을 수 있다. 적용 절차 머리에 "근거 규칙과 마지막 줄 형식은 이 절차보다 우선한다"가 붙으므로, 모델이 어느 쪽을 따를지 정해지지 않는다 |
| spec-compare "출력" (메일 채널) | "답변 본문만 쓴다. 여러 항목을 비교할 때는 표로 쓴다" | 표를 먼저 쓰고 표 아래에 개수 문장 | 프롬프트와는 맞음. 그러나 메일에서는 `mail-reply-style`("첫 문장에 결론")이 함께 적용되어 **두 절차의 순서가 다르다** (결론 문장 → 표 / 표 → 요약 문장) |
| certification-bundle "출력" (메일 채널) | 같음 | 표 + 아래 한 문장 | 위와 같은 순서 차이 |
| mail-reply-style "질문이 한 가지면 다섯 문장" | 길이 제한 없음 | — | 충돌 아님 (절차가 더 좁힘) |
| 프롬프트 v2 "도구" 표 | `load_skill`이 표에 없다 (DB 프롬프트는 바꾸지 않음) | — | 선택 절차 절과 도구 설명(docstring)에 `load_skill(name)` 사용법이 있다. 표에 없어도 동작한다 |
| mail-reply-style "찾지 못했을 때" | "문서에서 찾지 못했다고 밝힌다", 마지막 줄 `근거: 없음` | "등록된 문서에서 확인하지 못했습니다"라고 쓴다 | 맞음 |

## 설계자에게 넘기는 것 (본문 수정 후보, 구현자는 고치지 않음)
1. revise-after-reject: 첨부 근거는 `read_attachment`로 다시 읽는다는 문장.
2. revise-after-reject "사실 오류" 1과 프롬프트 근거 규칙 중 무엇이 우선인지 (담당자 값을 근거 없이 쓸 수 있는지).
3. 메일 채널에서 spec-compare·certification-bundle 출력 순서와 mail-reply-style "첫 문장에 결론"의 관계.
4. certification-bundle의 웹 채널 문장("검토 담당자가 승인할 때 고른다").

`spec-compare`는 지금처럼 문서에서 읽은 값으로만 대조한다. 단계 E의 `get_product_specs`·`compare_specs`가 생기면 설계자가 문서를 고친다 (지시서 6절).

## 확인: 명령과 결과
- 읽은 것: `skills/*/SKILL.md`, `tools/tool.py`(`graph_search`·`read_page_texts`·`read_attachment` 설명과 반환), `mail/templates.py`, `mail/email_service.py`(반려 안내문), `app/routers/mails.py`(승인 시 `render_answer_email` 호출)
- 운영 프롬프트: `storage/mail.db`를 `mode=ro` 연결로 열어 선택된 프롬프트의 "지켜야 할 것"·"출력 형식"을 읽었다 (저장소 클래스 임포트 없음)
- 도구 이름 대조: `tests/test_skills.py::test_skill_bodies_only_mention_existing_tools` 통과

## 커밋 해시
- (summary에 기록)
