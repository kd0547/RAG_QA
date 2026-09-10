# 메일 전송 승인 API 명세

프론트엔드(`frontend/src/mail/`)가 호출하는 백엔드 API 계약서.
대상 화면: `#/mail` — 메일 전송 승인 대시보드(안 4).

- **Base URL**: `http://127.0.0.1:8000` (프론트는 `VITE_MAIL_API_BASE` 로 덮어쓸 수 있음)
- **요청/응답 형식**: `application/json`, UTF-8
- **시각 형식**: ISO 8601, 오프셋 포함 (`2026-09-10T14:23:00+09:00`)
- **인증**: 현재 없음(사내망 전제). 붙일 경우 `Authorization: Bearer <token>` 헤더로.
- **CORS**: 개발 시 프론트가 `:5173` 에서 뜨므로 FastAPI 에 CORS 허용 필요
  ```python
  from fastapi.middleware.cors import CORSMiddleware
  app.add_middleware(
      CORSMiddleware,
      allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
      allow_methods=["*"], allow_headers=["*"],
  )
  ```

---

## 0. 사전 작업 (백엔드 변경 요약)

현재 `mail/email_service.py::email_consumer_loop` 은 `run_agent()` 결과를 **곧바로 `send_email()` 로 자동 전송**한다.
승인 단계를 넣으려면:

1. consumer 는 전송하지 말고 **초안까지만 저장**한다.
   `repo.save_draft(uid, answer, sources, confidence, model, retrieval)` → `status = 'drafted'`
2. 실제 전송은 `POST /mails/{uid}/approve` 가 호출될 때 수행한다.
3. `MailStatus` 는 이미 `pending / drafted / in_review / sent / failed` 를 정의하고 있어 그대로 사용.
4. `mails` 테이블에 컬럼 추가 (마이그레이션):

   | 컬럼 | 타입 | 용도 |
   |---|---|---|
   | `confidence` | REAL | 0~1, 근거/리랭크 점수 기반 신뢰도 (nullable) |
   | `assignee` | TEXT | 검토 담당자 (nullable) |
   | `sources` | TEXT | 근거 문서 JSON 배열 |
   | `model` | TEXT | 생성 모델명 (예: `qwen3.8:27b`) |
   | `retrieval` | TEXT | `{"query_top_k":6,"rerank_top_n":3}` JSON |
   | `reviewed_at` | TEXT | 승인/반려 처리 시각 (평균 검토 시간 계산용) |
   | `edited` | INTEGER | 승인 시 초안을 수정했는지 (0/1) |
   | `reject_reason` | TEXT | 반려 사유 |

---

## 1. 공통 규칙

### 에러 응답

모든 4xx/5xx 는 아래 형태로 통일:

```json
{ "detail": "사람이 읽을 메시지", "code": "machine_code" }
```

| HTTP | code | 상황 |
|---|---|---|
| 400 | `bad_request` | 파라미터 오류 |
| 404 | `not_found` | 해당 `uid` 없음 |
| 409 | `invalid_state` | 현재 상태에서 불가능한 동작 (예: 이미 `sent` 인 건을 승인) |
| 502 | `smtp_error` | SMTP 전송 실패 |
| 500 | `internal` | 그 외 |

### `uid` 취급

`uid` 는 POP3 UIDL 문자열이며 `/`, `=` 등이 포함될 수 있다. 경로에 넣을 때 **URL 인코딩**한다
(프론트는 `encodeURIComponent` 적용). 백엔드 라우트는 `{uid:path}` 대신 인코딩된 단일 세그먼트로 받는 것을 권장.

---

## 2. 데이터 모델

### MailSummary (목록 행)

```json
{
  "uid": "UID-1a2b3c",
  "subject": "A650 16인치 모델 RAM 최대 용량과 슬롯 구성 문의",
  "sender": "kim.jh@trigem.co.kr",
  "sender_name": "김지현",
  "sender_domain": "trigem.co.kr",
  "received_at": "2026-09-10T14:23:00+09:00",
  "status": "drafted",
  "confidence": 0.92,
  "assignee": null,
  "has_draft": true,
  "retry_count": 0
}
```

- `sender_name` / `sender_domain` 은 `sender` 에서 파싱해 채워도 되고 `null` 이어도 된다.
- `confidence` 는 `null` 허용. 화면에서 `< 0.6` 이면 저신뢰 경고 표시.

### MailSource (근거 문서)

```json
{ "source": "사양서_일반형노트북_20.pdf", "page": 4, "text": "메모리 / 최대 64GB (SO-DIMM 2)" }
```

`run_agent()` 결과의 `result["sources"]` (`{source, page, text}`) 를 그대로 저장·반환.

### MailDetail (상세) = MailSummary + 다음 필드

```json
{
  "recipient": "support-ai@trigem.co.kr",
  "body": "안녕하세요. 개발본부 김지현입니다. ...",
  "draft": "김지현 님,\n\n문의하신 ...",
  "model": "qwen3.8:27b",
  "retrieval": { "query_top_k": 6, "rerank_top_n": 3 },
  "sources": [ /* MailSource[] */ ],
  "created_at": "2026-09-10T14:23:05+09:00",
  "updated_at": "2026-09-10T14:23:05+09:00"
}
```

- `body` = 받은 원문(plain text). HTML 본문이면 서버에서 텍스트로 변환해 전달(현재 `get_body()` 로직 재사용).
- `draft` = AI 초안, 편집 대상. `null` 이면 초안 미생성.

### MailStats (대시보드 요약)

```json
{
  "date": "2026-09-10",
  "pending_review": 5,
  "low_confidence": 1,
  "sent_today": 24,
  "rejected_today": 3,
  "failed": 1,
  "avg_review_seconds": 112,
  "draft_adoption_rate": 0.79,
  "sent_delta": 6,
  "daily_volume": [
    { "date": "2026-08-28", "sent": 12 },
    { "date": "2026-09-10", "sent": 24 }
  ]
}
```

| 필드 | 정의 |
|---|---|
| `pending_review` | `status IN ('drafted','in_review')` 개수 |
| `low_confidence` | 위 중 `confidence < 0.6` 개수 |
| `sent_today` | 오늘(로컬 TZ) `status='sent'` 로 바뀐 개수 |
| `rejected_today` | 오늘 반려 처리된 개수 |
| `failed` | 현재 `status='failed'` 개수 |
| `avg_review_seconds` | 오늘 `reviewed_at - received_at` 평균(초). 데이터 없으면 `null` |
| `draft_adoption_rate` | 오늘 승인분 중 `edited=0` 비율 (0~1). 없으면 `null` |
| `sent_delta` | `sent_today − 어제 전송량` |
| `daily_volume` | 최근 14일, **오래된 → 최신** 순, 날짜 누락 없이 채움(0 포함) |

---

## 3. 엔드포인트

### GET `/mails` — 승인 대기 목록

| Query | 기본값 | 설명 |
|---|---|---|
| `status` | `drafted,in_review,failed` | 쉼표 구분. `pending,drafted,in_review,sent,failed` 부분집합 |
| `q` | — | 제목·발신자 부분 일치 검색 |
| `order` | `-received_at` | `received_at` \| `-received_at` \| `confidence` \| `-confidence` (`-` = 내림차순) |
| `limit` | `50` | 최대 200 |
| `offset` | `0` | |

**200 OK**

```json
{ "items": [ /* MailSummary[] */ ], "total": 6, "limit": 100, "offset": 0 }
```

---

### GET `/mails/stats` — 대시보드 요약

| Query | 기본값 | 설명 |
|---|---|---|
| `date` | 오늘 | `YYYY-MM-DD`, 해당 날짜 기준 집계 |

**200 OK** → `MailStats`

---

### GET `/mails/{uid}` — 상세

**200 OK** → `MailDetail`
**404** `not_found`

---

### PATCH `/mails/{uid}/draft` — 초안만 저장 (전송 안 함)

검토자가 초안을 고쳐두되 아직 안 보낼 때.

**Request**

```json
{ "draft": "수정한 초안 전문" }
```

**200 OK**

```json
{ "uid": "UID-1a2b3c", "draft": "수정한 초안 전문", "updated_at": "2026-09-10T14:35:10+09:00" }
```

상태는 바꾸지 않는다(`drafted` / `in_review` 유지).

---

### POST `/mails/{uid}/approve` — 승인하고 전송

**Request** (모든 필드 선택)

```json
{
  "body": "최종 본문. 생략하면 저장된 draft 그대로 전송",
  "subject": "제목 override. 생략하면 기존 규칙([응답] {원제목})",
  "edited": true
}
```

- `edited` 생략 시 서버가 `body` 와 저장된 `draft` 를 비교해 판정.
- 처리: `send_email(to=sender, subject, body)` → 성공 시 `status='sent'`, `answer=본문`, `reviewed_at=now`, `edited` 기록.

**200 OK**

```json
{ "uid": "UID-1a2b3c", "status": "sent", "sent_at": "2026-09-10T14:41:12+09:00", "to": "kim.jh@trigem.co.kr" }
```

**409** `invalid_state` — 이미 `sent` 이거나 `draft` 없음
**502** `smtp_error` — 전송 실패 (상태는 `failed` 로, `retry_count += 1`)

---

### POST `/mails/{uid}/reject` — 반려

**Request**

```json
{ "reason": "근거 신뢰도가 낮아 재작성 필요", "requeue": true }
```

| `requeue` | 결과 상태 | 의미 |
|---|---|---|
| `true` (기본) | `pending` | 에이전트가 다시 초안 생성 |
| `false` | `failed` | 자동응답 포기, 사람이 직접 처리 |

**200 OK**

```json
{ "uid": "UID-1a2b3c", "status": "pending" }
```

`reject_reason`, `reviewed_at` 저장.

---

### POST `/mails/{uid}/claim` — 내가 검토 (담당 지정)

**Request**

```json
{ "assignee": "나" }
```

`status='in_review'`, `assignee` 저장. **200 OK** → `MailDetail`
**409** `invalid_state` — 다른 사람이 이미 검토 중

### POST `/mails/{uid}/release` — 담당 해제

본문 없음. `assignee=null`, `status='drafted'`. **200 OK** → `MailDetail`

---

### POST `/mails/{uid}/retry` — 전송 실패 건 재전송

`status='failed'` 인 건을 저장된 본문 그대로 다시 `send_email`.

**200 OK**

```json
{ "uid": "UID-6p7q8r", "status": "sent", "sent_at": "2026-09-10T15:02:00+09:00", "to": "..." }
```

**409** `invalid_state` — `failed` 아님
**502** `smtp_error` — 또 실패 (`retry_count += 1`)

---

## 4. curl 예시

```bash
BASE=http://127.0.0.1:8000

# 대기 목록
curl "$BASE/mails?status=drafted,in_review,failed&order=-received_at"

# 요약
curl "$BASE/mails/stats"

# 상세
curl "$BASE/mails/UID-1a2b3c"

# 초안 수정만 저장
curl -X PATCH "$BASE/mails/UID-1a2b3c/draft" \
  -H 'Content-Type: application/json' \
  -d '{"draft":"고친 초안"}'

# 승인 + 전송 (초안 그대로)
curl -X POST "$BASE/mails/UID-1a2b3c/approve" \
  -H 'Content-Type: application/json' -d '{}'

# 수정본으로 승인 + 전송
curl -X POST "$BASE/mails/UID-1a2b3c/approve" \
  -H 'Content-Type: application/json' \
  -d '{"body":"최종 본문","edited":true}'

# 반려 (재작성 요청)
curl -X POST "$BASE/mails/UID-1a2b3c/reject" \
  -H 'Content-Type: application/json' \
  -d '{"reason":"근거 부족","requeue":true}'
```

---

## 5. 프론트엔드 연동 메모

- 프론트는 API 실패 시 자동으로 **예시 데이터로 폴백**하고 상단에 `백엔드 미연결 · 예시 데이터` 배지를 띄운다. 위 엔드포인트가 하나라도 200 을 주면 실데이터 모드로 전환.
- 목록은 20초마다 자동 새로고침(편집 중이면 건너뜀). 부하가 크면 `GET /mails` 를 가볍게 유지.
- 신뢰도(`confidence`) 산출식은 백엔드 자유. 예: `리랭크 top1 score` 정규화, 또는 `min(1, 근거문서수/기대치) × 평균 score`.
- `daily_volume` 은 스파크라인 전용이라 근사치여도 무방.
