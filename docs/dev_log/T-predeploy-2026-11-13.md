# 운영 반영 전 후속 수정·검증 — 2026-11-13

대상: 사용자가 전달한 T5 보고서와 「운영 반영 전 남은 작업까지 진행」 요청.
기준 HEAD: `7840d4c`, 브랜치 `feat/graph-rag`. 이번 후속 수정은 작업 트리에 있으며 커밋·푸시·서버 재시작은 하지 않았다.

## 결과

P3 지적 4건을 실제 코드에 맞춰 보완하고, T1 전체 린트를 막던 기존 OCR 콜백 순서 문제를 수정했다. 전체 테스트 463건, 전체 프론트 린트, 타입 검사와 임시 운영용 빌드가 통과했다. DB 두 파일은 SQLite 백업 API로 읽기 전용 백업했으며, 스키마 초기화·시드는 임시 사본에서만 두 차례 검증했다.

운영 `mail.db`·`agent_threads.db`는 시작·종료 SHA-256이 동일하다. 사용자가 수정한 `skills/skill-creator/SKILL.md`도 해시가 동일하다. `.env`, `requirements.txt`, `mail/`, `parser/spec_table.py`는 변경하지 않았다. 운영 서버·실제 모델·POP3/SMTP를 실행하지 않았다.

SQLite의 WAL 모드 읽기 전용 접속 과정에서 `agent_threads.db-wal`(0바이트)과 `agent_threads.db-shm`(32,768바이트) 보조 파일은 생성됐다. DB 본체 해시와 기존 테이블 행 수가 동일한 것을 별도로 확인했다. 이 파일들도 코드 커밋 대상이 아니다.

## 수정 내용

| 항목 | 수정·검증 |
| --- | --- |
| P3-1 작성 절차의 도구 안내 | `skills/create-skill/SKILL.md`에서 사양 조회를 없는 도구 예시로 들던 문구 제거. 활성 도구 계약을 따르게 정리 |
| P3-2 I1 기록 현행화 | `I-I1.md`에 실제 작성 절차의 추가 커밋·출처·별도 라이선스 선언 부재·크기·author 채널·외부 실행 여부 기록. 과거 문서가 없던 시점은 이력으로 구분 |
| P3-3 사용량 집계 | 잘린 load_skill 인자에 JSON 파싱 실패 시 이름 복원. 문의 분석과 같은 규칙으로 집계하며 한 실행의 중복 호출은 한 번만 계산 |
| P3-4 사양 없는 비교 대상 | 대상에 실제 비교 속성 값이 없으면 evidence_id=None과 함께 근거 미등록·확인 필요 안내를 반환. 근거를 임의로 만들지 않음 |
| T1 기존 린트 | OCR 실행 콜백을 파일 추가 콜백보다 먼저 선언하고 의존성에 연결. OCR 동작·화면·API 계약은 유지 |

추가 회귀 사례 10건: 잘린 JSON·단일 인용부호 로그·정상 JSON의 비객체/빈 이름·이름 없는 절단 로그·실행별 중복 집계/분석과의 일치, 사양이 전혀 없는 제품·선택 속성만 없는 제품·정상 대상과 빈 대상의 혼합 비교.

## 실행한 검사

프로젝트 venv가 사용자 계정 Python을 참조하고, npm 실행기도 사용자 계정 경로에 있어 정상 사용자 실행 환경에서 검증했다. 의존성을 설치하거나 갱신하지 않았다.

```text
.venv/Scripts/python.exe -B -m pytest tests/test_skill_repository.py tests/test_skill_author.py tests/test_spec_tools.py tests/test_validation.py -q -p no:cacheprovider
53 passed in 13.93s

.venv/Scripts/python.exe -B -m pytest tests -q -p no:cacheprovider
463 passed in 61.19s

# frontend/
npx --no-install eslint src
exit 0, 출력 없음

npm run build -- --outDir ../temp/codex_predeploy_build_20261113
tsc -b && vite build ...
871 modules transformed
exit 0
```

빌드 산출물은 `temp/codex_predeploy_build_20261113/`이며 `frontend/dist`를 교체하지 않았다. Vite의 큰 chunk 경고와 프로젝트 밖 outDir 안내는 남지만 빌드 오류는 없다. 화면 리팩터링·chunk 분할은 이번 범위에 넣지 않았다.

## DB 백업과 마이그레이션 사본 검증

백업 폴더: [predeploy-20261113-164410](/C:/TG_AI_DEV/rag_QA/storage/backup/predeploy-20261113-164410).
운영 DB를 `mode=ro`로 열어 SQLite backup API로 다음 두 파일을 만들었다. 원본에 WAL이 있더라도 DB 파일 단순 복사에 의존하지 않는다. 이 백업은 로컬 자료이며 코드 커밋 대상이 아니다.

| 파일 | 운영 원본 SHA-256 — 검증 전후 동일 |
| --- | --- |
| mail.db | `41e85e39ce373fd9f22eee6704b4d4293d6df3fce065e91f2254a069c363c1ef` |
| agent_threads.db | `8acc62116fb8fde301e33456b7b183dbb1f26efd0955e7489a3f47cb8092bf2c` |

저장소 import 전에 운영 두 DB 경로 연결을 임시 사본으로 전환했다. `main.py`나 lifespan·메일 worker·LLM을 시작하지 않고 스키마 초기화와 prompt/요청 유형/개념/사양 그래프 시드만 실행했다.

| 대상 | 이전 | 스키마 직후 | 1회 시드 | 2회 초기화·시드 |
| --- | ---: | ---: | ---: | ---: |
| mails / tasks | 128 / 128 | 128 / 128 | 128 / 128 | 128 / 128 |
| spec_attribute / spec_value | 90 / 1,572 | 90 / 1,572 | 90 / 1,572 | 90 / 1,572 |
| graph_relation | 31 | 31 | 33 | 33 |
| graph_alias | 96 | 96 | 97 | 97 |
| graph_entity | 59 | 59 | 59 | 59 |
| prompt | 3 | 3 | 4 | 4 |
| customer_note | 미존재 | 0 | 0 | 0 |

- 스키마 변경 전 모든 기존 테이블의 기존 컬럼·행 해시를 비교해 데이터 보존 확인.
- 추출·수동 그래프 관계는 시드 후에도 전체 행 해시 동일. spec 관계는 파생 모델 관계 2개가 추가됨. `spec_value=1,572`가 곧 그래프 spec 관계 1,572개를 뜻하지 않음.
- 2회차의 테이블 행 수·컬럼 구성이 1회차와 동일. spec 관계 재생성의 새 id까지 고정된다는 뜻은 아님.
- integrity_check: `ok`, foreign_key_check: 0건. 새로 상속이 허용된 속성은 0건.
- 사본 선택 프롬프트는 `v3 근거 ID·사양`. 운영 원본의 선택 프롬프트를 바꾸지 않음.
- 검증에 쓴 임시 DB 사본은 열린 연결을 모두 닫고 삭제했다. 보존 대상은 위 백업과 검증 JSON뿐이다.

원시 검증 결과는 `temp/codex_predeploy_result_20261113.json`, 실행 보조 스크립트는 `temp/codex_predeploy_verify_20261113.py`에 있다. 원본 메일 본문·주소는 결과에 출력하지 않았다.

## 제공된 T5 보고서와 다른 사실

HEAD는 일치하지만 아래 설명은 현재 코드와 맞지 않아 그대로 PASS 근거로 사용하지 않았다.

| T5 설명 | 실제 확인 |
| --- | --- |
| D는 맥락 관리 단계이며 agent/context_budget.py를 사용 | 해당 파일은 HEAD에도 없음. D 지시서·D-summary는 고객방/업무 절차 단계이며 맥락 관리는 agent.py의 내장 미들웨어 구성과 test_context_budget.py로 확인 |
| 도구 이름 search_docs/read_document_page, 별도 get_customer_notes | 현재 이름은 search_documents/read_pages, 고객 이력·메모는 get_customer_history 하나로 조회 |
| 매 실행 task와 run을 합친 thread_id로 과거 상태 폐기 | 실제 메일은 task thread를 이어가며 새 반려/retry 메시지의 ID로 중복을 제어. 고객 회신 기능 제외와 내부 반려 멀티턴은 구분 |
| 검증기가 spec:product:숫자 ID를 인식 | 실제 공통 evidence ID는 `e`+hex. 근거 줄에서 파싱하고 task/session 소유 범위를 확인 |
| 읽지 않은 후보 인용이 항상 오류 | 현재 검증 계약은 미열람 인용을 warning으로 둠. 같은 소유자에 이미 읽은 근거가 있으면 candidate 인용만으로 ok=false가 되는 것은 아님. 기존 test_validation.py가 이 동작을 명시 |
| 검증 PASS와 초안 저장 정책의 구분 필요 | 현재 errors도 초안은 저장하고 검토 화면에 경고. 빈 답변·모델 한도 초과는 예외로 저장하지 않음. 검증 결과를 저장 차단·정답 보증과 혼동하지 않음 |
| create-skill의 원래 크기·추가 커밋 | HEAD 원본 전체 2,269자/본문 2,080자, 최초 추가 16274c1. 이번 수정 후 전체 2,320자/본문 2,131자 |
| R-summary에 특정 운영 DB 수정 시각 오기가 있음 | 현재 HEAD의 R-summary에는 지목한 시각 문구가 없음. 없는 문장을 고치지 않고 이번 시작·종료 해시로 무변경을 확인 |

이 차이는 제공된 T5 표 전체를 무효로 단정하는 근거가 아니라, 현재 코드를 기준으로 판정표를 다시 읽어야 하는 이유다. 서버 검증 통과율을 정답률·운영 안정성 보증으로 바꾸어 표현하지 않는다.

## 남아 있는 운영 단계와 입력 과제

1. 검토한 작업 트리 변경을 배포 경로에 반영하고 실제 frontend 빌드·서버 재시작(T3)을 한다. 이번 후속 작업은 커밋·푸시하지 않았다. 백업 이후 DB가 바뀌었다면 적용 직전 다시 백업한다.
2. 재시작 후 T4에서 새 스키마·선택 프롬프트·화면/API를 확인한다. 메일 주입은 검토 알림을 보내므로 기존 지시서의 별도 통합 확인 요청 후 진행한다. 실제 승인 발송 S1은 별도 지시 대상이다.
3. T6는 문서 17개가 있는 개발 서버에 같은 변경을 반영한 뒤 수행한다. 현재 로컬 문서는 2개이며 빈 10번 문항·정답/기대 근거는 임의로 채우지 않았다.
4. 제품-부품 연결 0건, 완제품 사양 미입력, 상속 허용 목록은 R&D 데이터 입력 과제다. 이번 작업에서 제품 사양을 추정하거나 변경하지 않았다.

현재 판정은 **로컬 운영 반영 전 자동 검사·사본 검증 완료**다. 실환경 UI 확인, 실제 고객 메일 흐름·답변 품질, 기준선 정답 대조를 완료한 것으로 표시하지 않는다.
