# R-summary 남은 단계 통합 구현·검증 기록

정리일: 2026-11-13. 지시서: [opus_development_instructions_remaining.md](../opus_development_instructions_remaining.md).

R0·E·H·G·Z1 구현, F 비교 결과 정리, T2 사본 마이그레이션 예행을 마쳤다. 전체 자동 테스트는 **453 passed**다. T1 전체 린트에는 기존 App.tsx 오류 2건이 남아 있다. F는 실행 가능한 9문항의 비교를 완료했으며, 빈 10번 문항과 정답 대조는 미완료다. 운영 반영과 T4~T6 확인은 아래 조건에 따라 남는다.

## 항목과 커밋

| 항목 | 내용 | 커밋 | 기록 |
|------|------|------|------|
| R0 | D1~D5 요약, D6를 통합 확인으로 이관 | `24dc2dd` | [D-summary](D-summary.md) |
| E1 | 상속 허용 표시·인증 상속 금지·읽기 전용 데이터 점검 | `f9aa7c0` | [E-E1](E-E1.md), [E-spec-audit](E-spec-audit.md) |
| E2 | 사양 조회·상속·단위 환산·4종 판정·조건 검색 | `0c19740` | [E-E2](E-E2.md) |
| E3 | 사양 도구 4개·대상별 근거 등록 | `d400196` | [E-E3](E-E3.md) |
| E4 | 속성의 물려받기 허용 체크박스 | `d22ae7f` | [E-E4](E-E4.md) |
| H1 | 그래프 ref·옵션 컬럼·CHECK 마이그레이션 | `9bc911e` | [H-H1](H-H1.md) |
| H2 | 사양 제품·연결 부품·파생 관계 심기 | `36420d8` | [H-H2](H-H2.md) |
| H3 | 추출 정식 이름·별칭 검증·사양 참조 | `77b3bea` | [H-H3](H-H3.md) |
| H4 | 검색 ref·상위 모델 문서 후보의 via 표시 | `d9f2d8b` | [H-H4](H-H4.md) |
| G1 | 고객 이력 조회·건수 안내·담당자 메모 API | `7bbe1d6` | [G-G1](G-G1.md) |
| G2 | 고객방 담당자 메모 화면 | `06a277d` | [G-G2](G-G2.md) |
| Z1 | v3 프롬프트 등록·절차 4종 원문 교체 | `166317e` | [Z-Z1](Z-Z1.md) |
| F1 시제품 | 별도 환경·읽기 전용 backend·실행기·API 조사 | `ec846de` | [F-compare](F-compare.md), [시제품 README](../../tests/eval/deepagents_proto/README.md) |
| F1 측정표 | 현재 엔진·시제품 각 9문항 결과 | `7e6817b` | [F-compare-table](F-compare-table.md) |
| F1 해석 | 원본 JSON 재검산·문항별 해석·비교 한계 | `42c9b2a` | [F-compare 4~6절](F-compare.md#4-측정-결과-2026-11-13) |
| T2 | 운영 DB 사본에서 초기화 2회 예행 | `ec846de` | [T-migration](T-migration.md) |
| T1 | 전체 검사 재확인·기존 린트 오류·임시 사본 정리 | `8d59da5` | [T-T1](T-T1.md) |
| Z2 | 본 요약·최신 인수인계 | 본 문서 추가 커밋 | [HANDOFF-remaining](HANDOFF-remaining.md) |

Z2 커밋은 `git log -1 -- docs/dev_log/R-summary.md`로 확인한다. 이번 마무리는 운영 코드 변경 없이 F1·T1·Z2 기록을 각각 커밋했다. 사용자의 `skills/skill-creator/SKILL.md` 수정과 기존 미추적 파일은 커밋에 포함하지 않았다.

## 전체 테스트 출력

2026-11-13 재실행. 출력이 20줄보다 짧아 전부 적는다.

```text
.venv/Scripts/python.exe -m pytest tests -q
........................................................................ [ 15%]
........................................................................ [ 31%]
........................................................................ [ 47%]
........................................................................ [ 63%]
........................................................................ [ 79%]
........................................................................ [ 95%]
.....................                                                    [100%]
453 passed in 65.63s (0:01:05)
```

프론트는 `npx --no-install tsc -b`와 변경 폴더 `npx --no-install eslint src/spec src/mail src/knowledge`가 통과했다. `npm run build -- --outDir "$env:TEMP\ragqa-remaining-build"`도 통과했으며 출력 대상은 임시 폴더다. 전체 `npx --no-install eslint src`는 App.tsx의 기존 오류 2건·경고 1건으로 exit 1이다. 정확한 명령, 오류 위치, 빌드 출력은 [T-T1](T-T1.md)에 있다. **전체 린트 통과나 운영 빌드 완료로 보고하지 않는다.**

## 멈춘 항목과 미완료 범위

설계 충돌로 중단된 구현 항목은 없다. 다음은 구현 완료와 구분해 남겨 둔다.

| 항목 | 상태·남은 조건 |
|------|----------------|
| T1 전체 린트 | 기존 App.tsx 315·319행 오류 2건, 316행 경고 1건. 마지막 변경은 2026-11-05 `52963dd`이며 이번 구현과 무관하다. 인수인계대로 보고만 했다. |
| F1 10번·정답 대조 | 주간판매 질문이 빈 자리라 두 구성 모두 1~9번만 실행. 정답 근거·키워드도 전 문항에서 비어 있다. 담당자가 채워야 한다. |
| T3 운영 반영 | 사용자가 DB 두 파일 백업 → frontend 빌드 → 서버 재시작을 수행한다. |
| T4 통합 실환경 확인 | 사용자의 「통합 확인 진행」 지시 후 실행. 기대와 다르면 결과만 적는다. 승인 발송 S1은 별도 지시가 필요하다. |
| T5 Gemini | 읽기 전용 외부 검증 대기. 아래 확인 위치를 전달한다. |
| T6 기준선 비교 | 사용자가 개발 서버 주소를 제공한 뒤 17문서 환경에서 진행. 빈 문항·정답 기준의 상태를 함께 명시한다. |

F 비교는 서버 근거 검사에서 양쪽 9/9 ok=true였지만, 시제품 3번은 근거 줄 누락 경고와 인용 0건이다. 시제품 총 시간은 784.0 → 595.3초(-24.1%), 입력 토큰은 1,457,313 → 2,256,057(+54.8%)이다. 로컬 문서 2개, 의존성·맥락 관리 차이, 가상 `/docs/` 미사용을 포함한 한계 때문에 채택 결론을 내리지 않았다. 상세 근거는 [F-compare](F-compare.md)에 있다.

## 지시서와 다르게 한 것

| 항목 | 결정·이유 | 상세 |
|------|-----------|------|
| H2·H3 제품 이름 별칭 | 제품 이름은 정규화한 모델명을 포함할 때만 별칭·추출 다른 표기로 사용. `Pro`·`Home` 같은 일반 이름의 오매칭을 막는다. | [H-H2](H-H2.md), [H-H3](H-H3.md) |
| H1 옵션 저장 | 지시서가 저장 위치를 정하지 않아 `graph_relation.is_option`을 추가했다. | [H-H1](H-H1.md) |
| H1 CHECK 이관 | 기존의 끊어진 참조 행도 보존하도록 이관 중 외래키 검사를 끄고 옮긴 뒤 다시 켠다. | [H-H1](H-H1.md) |
| H3 별칭 근거 확인 | 알려진 정식 이름에 해당하는 개체만 별칭으로 페이지 존재를 입증할 수 있게 했다. | [H-H3](H-H3.md) |
| H4 상위 모델 매칭 | `find_entities`에서 더 긴 모델명 안에만 나타나는 상위 모델은 직접 매칭하지 않는다. 상위 문서는 `variant_of` 후보 경로로만 온다. | [H-H4](H-H4.md) |
| G1 저장소 분리 | 본문·초안을 포함한 고객방 저장소와 모델 입력의 경계를 유지하도록 `customer_history_repository.py`를 따로 뒀다. | [G-G1](G-G1.md) |
| E3 대상 입력 | 사양 도구 `owner_id`에 DB ID뿐 아니라 정확한 모델명도 받는다. | [E-E3](E-E3.md) |
| E1 인증 분류 변경 | 상속 허용을 켠 속성을 `cert` 분류로 옮기는 것도 400으로 막았다. | [E-E1](E-E1.md) |
| F1 측정 범위·구성 | 10번이 빈 자리라 9문항 측정. 시제품은 langchain 1.5.0/langgraph 1.2.21과 자체 요약 사용. 절차 읽기·파일 도구도 달라 deepagents 단독 효과로 볼 수 없다. | [F-compare](F-compare.md) |
| T1 빌드 위치 | 사용자 담당 T3 운영 반영을 앞서 하지 않도록 임시 outDir로 빌드했다. 전체 린트의 기존 오류도 기록했다. | [T-T1](T-T1.md) |

Z1의 프롬프트·절차 본문은 설계자 원문 그대로다. 설정으로 꺼진 도구가 프롬프트 표에 남는 것도 지시서 Z1-4대로 유지했다. 고객 회신 기능 제외는 사용자 결정에 따른 범위이며 구현 누락이 아니다.

## 재시작 시 운영 DB 변경 표

다음은 **T2에서 운영 DB 사본으로 확인한 변경**이다. 이 요약을 작성하면서 운영 DB에 적용한 것이 아니다. 원본의 시각·크기 유지, 2회 실행 결과와 정확한 행 수는 [T-migration](T-migration.md)을 참조한다.

| 대상 | 변경·기존 데이터 영향 | 예행 결과 |
|------|----------------------|-----------|
| `customer_note` | `note_id`, `sender`, `text`, `created_at`, `created_by`, `retired_at` 테이블과 `idx_customer_note_sender` 인덱스 추가 | 새 테이블 0행 |
| `spec_attribute` | `inheritable INTEGER NOT NULL DEFAULT 0` 추가. 허용 속성을 자동 선정하지 않는다. | 기존 90개 모두 0 |
| `graph_entity` | `ref_type TEXT`, `ref_id TEXT`, `idx_graph_entity_ref` 인덱스 추가 | 개체 수 유지. 이미 있던 제품 4개에 ref 연결 |
| `graph_relation` | CHECK의 출처에 `spec` 허용, `is_option INTEGER NOT NULL DEFAULT 0` 추가를 위해 테이블 재생성. 기존 3개 인덱스 재생성 | 마이그레이션 직후 31행·기존 id·created_at 등 유지, 기존 행 옵션 0 |
| `graph_relation` 기존 행 검증 | `(id, src, dst, type, file, page, origin, created_at)` 해시 비교, 외래키 검사 | 전후 해시 `3664d086eee0ddeb` 동일, 외래키 위반 0 |
| `prompt` | `v3 근거 ID·사양`을 한 번 등록·선택. v2 본문은 유지하고 기존 선택만 해제 | 3 → 4행, v3 id 4. 재실행은 추가하지 않음 |
| 사양 관계 심기 | `A650-GA70-OU01 → A650`, `A650-GA70-PU02 → A650` 파생 관계 추가 | `spec` 2행으로 관계 총 31 → 33. 부품 연결 0건이라 `has_component` 0 |
| `graph_alias` | 모델명이 포함된 제품 이름 별칭 추가 | 96 → 97행 |

스키마 마이그레이션만으로 기존 테이블 행 수는 바뀌지 않았다. 이후 초기화의 프롬프트 등록·관계 심기는 위 표처럼 행을 추가한다. 2회차의 스키마·행 수·출처별 관계 수는 1회차와 같았다. `seed_specs`는 spec 관계만 지우고 다시 넣으므로 새 spec 관계의 id 고정을 뜻하지 않는다. 문서 추출·수동 관계 보존은 별도 테스트로 확인했다.

## 9절 통합 확인 위치

| 항목 | 확인 위치·실행 조건 |
|------|--------------------|
| T1 자동 검사 | [T-T1](T-T1.md), 위 전체 pytest 출력. 기존 전체 린트 실패 포함 |
| T2 마이그레이션 | [T-migration](T-migration.md), `tests/test_graph_spec.py::test_check_migration_keeps_rows_ids_and_indexes` |
| T3 사용자 운영 반영 | `storage/mail.db`·`storage/agent_threads.db` 백업 → frontend의 `npm run build` → 서버 재시작 |
| T4 W1~W6 | 지시서 9절 웹 질문 표. 사용자 지시 후 확인 결과를 `T-live-check.md`에 작성 예정 |
| T4 M1~M5 | 지시서 9절 메일 흐름 표. 작업 생성과 검토 알림 메일이 발생하는 단계이므로 별도 진행 지시 후 실행 |
| T4 S1 | Outlook이 실행 중이고 사용자가 따로 승인 발송 확인을 지시할 때만 실행 |
| T5 | 아래 E/H/G/Z/F/공통 확인표와 [D-summary](D-summary.md), [I-summary](I-summary.md). Gemini 판정은 아직 없음 |
| T6 | [Gemini 지시서 C절](../gemini_verification_instructions.md), [평가셋 README](../../tests/eval/README.md), `tests/eval/baseline_2026-11-12.json`. 개발 서버 주소 필요 |

T4 미실행 상태이므로 `T-live-check.md`는 아직 작성하지 않았다. D6도 T4에 포함한다. 이전 I 실환경 확인은 [I-live-check](I-live-check.md)에 있으며 이번 T4를 대신하지 않는다.

### T5 항목별 확인표

아래 표는 구현자 검증 자료 위치이며 Gemini 판정을 대신하지 않는다.

| 번호 | 확인 위치 |
|------|-----------|
| E-1 숫자·단위·4종 판정 | `entity/spec_units.py`, `agent/spec_service.py`; `tests/test_spec_service.py::test_ram_32_verdicts_base_option_missing_and_max_separate`, `::test_units_kg_g_and_tb_gb_and_unknown_unit` |
| E-2 허용된 상속·인증 금지 | `tests/test_spec_service.py::test_child_value_wins_over_parent`, `::test_inherits_only_allowed_attributes_from_nearest_parent`, `::test_cert_attribute_never_inherited`; `tests/test_spec_inheritable.py::test_api_put_inheritable_and_cert_400` |
| E-3 연결된 부품만 | `tests/test_spec_service.py::test_only_linked_component_values_and_option_link_is_option` |
| E-4 값 없음·미지원 | `tests/test_spec_service.py::test_no_value_and_explicit_unsupported_bool_differ` |
| E-5 근거 등록·후보 불인용 | `tests/test_spec_tools.py::test_get_specs_registers_evidence_and_citation_passes`, `::test_compare_specs_registers_one_evidence_per_target`, `::test_search_only_answer_fails_validation`, `::test_other_tasks_spec_evidence_is_rejected` |
| E-6 데이터·엑셀 양식 | [E-spec-audit](E-spec-audit.md), `tests/test_spec_inheritable.py::test_audit_reports_findings_and_does_not_write`; `tests/test_spec_import.py`, `app/routers/spec_import.py` diff(가져오기 후 심기), [E-E4](E-E4.md) |
| H-1 재추출·삭제 유지 | `tests/test_graph_spec.py::test_reextract_keeps_spec_relations_and_unlink_removes_them`, `::test_deleted_spec_relation_is_not_reseeded`, `::test_prune_keeps_entities_with_spec_ref` |
| H-2 상위 문서는 후보 | `tests/test_graph_spec.py::test_variant_question_gets_parent_documents_as_candidates_only`, `graph_rag/service.py`, `tests/test_spec_service.py::test_cert_attribute_never_inherited` |
| H-3 상위·파생 구분 | `tests/test_graph_spec.py::test_n5800_and_variant_are_different_entities`, `tests/test_spec_service.py::test_resolve_keeps_n5800_and_variant_apart` |
| H-4 CHECK 이관 보존 | `tests/test_graph_spec.py::test_check_migration_keeps_rows_ids_and_indexes`, `::test_migration_copies_rows_even_with_dangling_file`, [T-migration](T-migration.md) |
| G-1 건수만 안내 | `tests/test_customer_history.py::test_next_inquiry_gets_count_line_only`, `tests/test_customers.py`, `agent/agent.py::customer_history_hint` |
| G-2 발신자 격리·본문 제외 | `tests/test_customer_history.py::test_history_is_same_sender_only_recent_and_has_no_bodies`, `::test_sender_cannot_be_changed_by_arguments`, `::test_retired_notes_are_hidden` |
| G-3 고객 회신 기능 제외 | `git diff 1d8b4d5 HEAD -- mail/` 변경 없음. G1/G2 변경 목록과 [통합 지시서 5절](../opus_development_instructions_remaining.md) |
| Z-1 v2 보존·v3 한 번·절차 원문 | `tests/test_prompt_v3.py::test_v3_is_prompt_doc_code_block_verbatim`, `::test_ensure_v3_once_and_v2_row_untouched`, `::test_replaced_skill_documents_are_version_2_and_load`; [Z-Z1](Z-Z1.md)의 원문 바이트 비교 기록 |
| F-1 운영 의존성·동일 문항 | [F-compare 1·4·6절](F-compare.md), `git diff 1d8b4d5 HEAD -- requirements.txt` 변경 없음, `tests/eval/deepagents_proto/common.py::load_models`·`cases` |
| 공통-1 실행 한도·맥락 예산 | `agent/agent.py`: 검색 6·도구 25·모델 20, `config.py`: 24,000/40,000·recursion 200; `tests/test_context_budget.py::test_middleware_order_and_settings` |
| 공통-2 설정으로 기능 끄기 | `tests/test_spec_tools.py::test_disabled_spec_tools_are_not_bound_to_agent`; `tests/test_graph_spec.py::test_router_changes_reseed_and_flag_off_skips`, `::test_flag_off_keeps_old_prompt_and_no_refs`; `tests/test_customer_history.py::test_flag_off_removes_tool_and_hint` |
| 공통-3 쓰기 도구·자동 승인·재발송 없음 | `tools/tool.py`의 TOOLS·`agent/agent.py::active_tools`, `tests/test_skills.py`, `tests/test_skill_api.py`, `tests/test_mail_send_status.py`, `tests/test_email_send.py`; [I-summary](I-summary.md) I-3 |

## 사용자에게 남는 결정과 운영 순서

1. 운영 반영 전 DB 두 파일을 백업하고 프론트 빌드·서버 재시작을 한다. 이번 마무리에서는 시행하지 않았다.
2. R&D가 `/spec`에서 상속 허용 속성을 선택한다. 기본값은 모두 꺼짐이며 인증 분류는 허용할 수 없다.
3. 제품-부품 연결이 0건인 상태에서는 제품에 어떤 SSD가 들어가는지 사양 DB만으로 답할 수 없다. 연결·사양 값을 임의로 만들지 않았다.
4. [E-spec-audit](E-spec-audit.md)의 비슷한 속성 11쌍과 값이 없는 제품·부품 등을 검토하고 데이터 정리 여부를 정한다.
5. 운영 반영 뒤 T4 진행을 지시하고, 메일 흐름 확인과 S1 실제 승인 발송은 구분해 지시한다.
6. T5 검증 담당자에게 본 문서를 전달하고, T6용 개발 서버 주소·주간판매 질문·정답 칸을 준비한다.

확인용 개발 서버(8010·5174)는 이미 꺼져 있었고, 인수인계의 임시 DB 사본 폴더 2개는 삭제했다. [T-T1](T-T1.md)에 경로와 확인 방법을 기록했다.
