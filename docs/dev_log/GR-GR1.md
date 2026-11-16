# GR-GR1 시스템 상위 개념 완전 제거

## 변경 파일
- `aliases.yaml` 삭제
- `agent/agent.py`: `ALIAS_PATH`, `load_aliases`, `ALIASES`, `_graph_concepts`, `yaml` 임포트 삭제. `render_prompt` 호출에서 별칭·개념 인자 삭제
- `agent/prompt.py`: `ALIAS_PATH`, `render_aliases`, `render_concepts`, `_build_prompt`, `aliases`·`concepts` 인자 삭제. `strip_legacy_concepts()`가 옛 본문(v2·v3)의 `**용어 별칭 (표준 이름 = 별칭)**`·`$aliases` 줄과 상위 개념 펼치기 문장을 렌더링할 때 지운다 (DB 행은 그대로)
- `main.py`: `seed_concepts` 호출과 `ALIASES` 임포트 삭제
- `graph_rag/types.py`: `concept` 종류, `part_of` 관계, `ExtractedEntity.concept` 삭제. `NON_EXTRACT_RELATIONS = {"variant_of"}`
- `graph_rag/extractor.py`: `_CONCEPT_GUIDE`, `_keep_known_concepts`, `concepts` 인자 삭제
- `graph_rag/service.py`: 개념 펼치기와 결과의 `expanded` 삭제. 문서 순위는 질문에서 찾은 개체 수로만
- `repository/graph_repository.py`: `seed_concepts`, `concept_members`, `list_concepts`, `replace_page`의 `part_of`, `relations_of`·`find_entities`·`_prune_orphans`의 `concept` 예외 삭제
- `repository/graph_migration.py`: 기본 관계 종류에서 `part_of` 삭제. `remove_system_concepts()` 마이그레이션 추가 (서버 시작마다, 결과가 같다)
- `tools/tool.py`: `graph_search` 설명에서 상위 개념·`expanded` 문장 삭제
- `storage/schema.sql`, `repository/prompt_repository.py`: 주석만
- 프론트 `frontend/src/knowledge/`: `meta.ts`(concept 색·크기 예외), `types.ts`(concept 종류), `GraphCanvas.tsx`(concept 그리기 예외), `EntityPanel.tsx`(part_of → concept 기본 종류)
- 테스트: `tests/test_graph_no_concepts.py`(신규), `test_graph.py`, `test_graph_edit.py`, `test_graph_spec.py`, `test_group_prompt.py`, `test_prompt_v2.py`, `test_prompt_v3.py`, `test_skills.py`, `tests/eval/deepagents_proto/run_compare.py`

## 결정한 것
- 지시서 테스트 "옛 v3를 선택해도 시스템 프롬프트에 '상위 개념'이 없다"를 맞추려면 v3 본문의 두 문장(도구 표의 "상위 개념(예: KC 인증)은 속한 인증 종류로 펼쳐 준다", 지켜야 할 것의 "상위 개념이 펼쳐졌으면 …")도 렌더링 때 바꿔야 한다. 도구 표 문장은 지우고, 지켜야 할 것 줄은 GR6 v4의 첫 줄(인증 묶음 이름은 펼치지 않는다 …)로 바꾼다. 제품군 문장(GR6 v4 둘째 줄)은 GR4 이전이라 넣지 않았다. CRLF로 저장된 본문도 처리한다.
- 마이그레이션은 `type='concept'` 개체를 **상태와 관계없이**(삭제·병합 포함) 지우고, 개념을 출발·도착으로 하는 관계는 종류와 출처(수동 포함)에 관계없이 지운다. 개념 개체가 없어지면 관계가 의미를 잃기 때문이다 (규칙 6의 예외 범위로 봤다). 그 관계·속성 값의 `graph_fact_source`도 지운다.
- 사용자 관계 종류의 허용 종류, 속성 정의의 허용 종류 JSON에서 `concept`을 뺀다. 다른 종류가 남지 않으면 그대로 둔다(빈 목록이면 편집 검사가 깨진다).
- 편집 이력은 지운 것이 있을 때만 한 건 남긴다 (`target_id='GR1-remove-system-concepts'`). 매 시작마다 0건 이력이 쌓이지 않게 했다.
- `graph_relation.origin`의 `seed` 값은 CHECK에 남겨 둔다 (빼려면 테이블을 다시 만들어야 하고, 이제 seed 관계를 만드는 코드가 없다). 화면의 `seed` 범례도 남겨 둔다.

## 사고: 운영 DB에 GR1 마이그레이션이 적용됨 (규칙 3 위반)
- 사본 예행으로 `python -c "from repository.repo_connect import Database; Database(사본)"`을 실행했는데, `repository` 패키지 초기화(`repository/__init__.py`)가 먼저 `storage/mail.db`를 열고 새 마이그레이션을 적용했다. 2026-11-16 10:32 (KST).
- 운영 DB에서 바뀐 것 (GR1이 지우도록 정한 것만): concept 개체 `KC 인증`(id 1)과 별칭 1개, `part_of` seed 관계 2개(158, 159), `graph_relation_block`의 part_of 행 4개, `graph_relation_type`의 `part_of` 행, `graph_edit_event` 1건 추가(action=migration). 나머지 기존 마이그레이션은 이미 적용돼 있어 변화 없음.
- 원래 행은 `storage/mail-backup.db`(2026-11-13)에 그대로 있다. 되돌릴지는 사용자 결정으로 남긴다 (되돌리려면 운영 DB에 다시 써야 하므로 구현자가 하지 않는다).
- 재발 방지: 이후 사본 예행은 `sqlite3.connect`를 가로채는 가드(운영 경로 → 임시 폴더)를 먼저 설치한 스크립트로만 한다.

## 테스트: 명령과 출력
```
$ .venv/Scripts/python.exe -m pytest tests/test_graph_no_concepts.py -q
......                                                                   [100%]
6 passed in 0.67s
$ .venv/Scripts/python.exe -m pytest tests -q
........................................................................ [ 97%]
............                                                             [100%]
516 passed in 69.65s (0:01:09)
$ npx tsc -b; npx eslint src/knowledge   (frontend/)
(출력 없음 = 통과)
```

## 확인하지 못한 것 / Gemini에게 요청할 검증
- 캡처가 나온 서버의 DB에는 적용하지 않았다 (사용자 재시작 시 적용).
- "KC 인증 자료" 질문의 실제 답변 저하 정도는 실모델로 확인하지 않았다 (GR8 실서버 확인 항목).

## 커밋 해시
GR-summary.md에 모은다.
