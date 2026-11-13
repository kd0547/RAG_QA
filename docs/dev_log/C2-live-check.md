# C2 실환경 확인 (2026-11-13, 사용자 서버 재시작 후)

Gemini C2 판정(PASS 9) 뒤 남은 확인 항목을 실서버(8000)·실모델(qwen3.8-flash-next)로 확인했다. 코드 변경 없음. 운영 DB는 읽기 전용으로 조회했고, 쓰기는 `/ask` 1회가 남긴 웹 질문 근거·실행 기록뿐이다 (14일 뒤 자동 정리 대상).

## 서버 기동 (logs/app.log, 11:46:35 기동)
- `오래된 웹 질문 기록 정리(14일 초과): {'evidence': 0, 'evidence_use': 0, 'run': 0}`
- 발송 중 작업 정리는 경고 없음 — 운영 `tasks`에 `sending` 0건이라 정상 (건수가 있을 때만 WARNING)
- 마이그레이션 적용 확인 (읽기 전용 조회)
  - `run` 컬럼에 `label` 있음
  - `task_reviews` CHECK: `action IN ('reject', 'mark_sent', 'retry')`
- 11:44 종료 때 `['mail-receiver']` 경고는 재시작 전(구 코드) 서버의 종료라 P7 효과와 무관하다. P7은 다음 종료부터 적용된다.

## P2 next_offset 이어 읽기 — 확인됨
운영 문서에 6,000자(기본 `max_chars`)를 넘는 페이지가 없다 (`SSD_성능_비교.xlsx`는 지금 운영 `file`에 없음, 가장 긴 페이지는 N5800 KC 인증서 14페이지 4,832자). 그래서 질문에서 `max_chars=2000`으로 나눠 읽으라고 지정했다.

```
POST /ask  (200, 49.96초)
질문: N5800 KC 인증서 14페이지를 read_pages로 max_chars=2000씩 나눠 읽고, 잘리면 next_offset으로 끝까지 읽어 시험 항목 정리
```
run `r0c0b8cc30924` (status ok, label "질문", 입력 토큰 64,637) 도구 호출:
```
read_pages pages=[14] max_chars=2000
read_pages pages=[14] max_chars=2000 offset=2000
read_pages pages=[14] max_chars=2000 offset=4000
grep_documents "시험"
read_pages pages=[10] max_chars=2000
read_pages pages=[10] max_chars=1000 offset=2000     ← 지시하지 않았는데 스스로 offset 사용
grep_documents "(Test Item|시험항목|…)"
```
- 14페이지 세 번 읽기 모두 같은 근거 `ea6e759b3` (`evidence_use` read 3행), 10페이지 두 번은 `ec370c3f4`
- 답변 검증 `ok: True`, 인용 `['ea6e759b3', 'ec370c3f4']` 둘 다 `cite` 기록

한계: 페이지가 실제로 6,000자를 넘어 **기본값에서** 잘리는 경우(모델이 max_chars를 지정하지 않을 때)는 운영 문서에 해당 페이지가 없어 확인하지 못했다.

## P6 웹 질문 대화 정리 — 확인됨
`/ask` 전후 `agent_threads.db` 대화 목록이 같다 (새 `ask:` 없음):
```
ask:27c795a6… 36행, ask:9aaa93db… 22행 (P6 이전 것, 그대로), task:6b40acb4… 30행
```

## P5 [재시도] — 확인하지 못함
- `[재시도]` 안내는 "대화 기록이 있고 직전 실행이 답 없이 끝난" 작업에서만 나간다. 운영의 `failed` 24건은 모두 2026-09-30 ~ 10-27, 대화 저장(C1) 이전 작업이라 대화가 없다 → 다시 생성하면 첫 실행 경로로 돌고 `[재시도]`는 나가지 않는다.
- 다시 생성은 초안 저장 뒤 검토자에게 실제 알림 메일을 보낸다. 그래서 운영 작업으로 시험하지 않았다.
- 확인하려면 C1 이후 모델 호출 한도로 실패한 작업이 생겨야 한다.

## P6 이전 ask: 대화 정리 (사용자 지시 "지워", 2026-11-13)
- 백업: `storage/agent_threads.db.bak-20261113` (sqlite backup API, 서버 가동 중)
- 삭제: `ask:27c795a6…` (checkpoints 36·writes 57), `ask:9aaa93db…` (checkpoints 22·writes 32) → checkpoints 58행, writes 89행
- 남은 것: `task:6b40acb4…` (checkpoints 30·writes 45) 그대로
