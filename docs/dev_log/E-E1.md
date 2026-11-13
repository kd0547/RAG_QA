# E-E1 상속 허용 표시와 사양 데이터 점검

## 변경 파일
- `storage/schema.sql`: `spec_attribute.inheritable INTEGER NOT NULL DEFAULT 0 CHECK (inheritable IN (0, 1))`
- `repository/repo_connect.py` `_migrate`: 컬럼이 없으면 `ALTER TABLE spec_attribute ADD COLUMN inheritable INTEGER NOT NULL DEFAULT 0` (기존 속성 전부 0)
- `repository/spec_repository.py` `update_attribute`: `inheritable`을 받는다. 결과 분류가 `cert`인데 `inheritable=1`이면 `ValueError`(→ 400)
- `app/routers/specs.py` `AttributeUpdate.inheritable: bool | None`
- `entity/spec_units.py`(신규): 단위 표(지시서 E2 (다))와 `to_attribute_unit`, `read_number`. 점검 스크립트와 E2 사양 서비스가 함께 쓴다. 저장소를 임포트하지 않는다
- `scripts/audit_spec_values.py`(신규): 읽기 전용 점검. `sqlite3` `file:…?mode=ro`, 저장소 임포트 없음
- `docs/dev_log/E-spec-audit.md`(신규): 운영 DB 점검 결과
- `tests/test_spec_inheritable.py`(신규) 32건

## 결정한 것
1. **인증 분류로 옮기는 것도 막는다.** 지시서는 "cert 속성은 1로 바꿀 수 없다"이다. 물려받기가 켜진 속성의 분류를 `cert`로 바꾸면 같은 상태가 되므로 같은 400을 낸다. 사양 서비스(E2)도 읽을 때 `cert` 속성은 `inheritable`과 관계없이 물려받지 않는다 (이중 안전장치).
2. **단위 표를 E1에 만들었다.** 점검 항목 1("값 문자열의 단위가 속성 단위와 다른 값")이 E2 (다)와 같은 규칙으로 읽어야 결과가 비교 코드와 맞는다. 점검 스크립트가 저장소를 임포트하면 안 되므로 `agent/`가 아니라 의존성 없는 `entity/spec_units.py`에 두고, E2의 `agent/spec_service.py`가 다시 내보낸다.
3. **값 문자열 읽기 규칙** (`read_number`)
   - 첫 숫자(천 단위 쉼표 제거) 뒤에 붙은 단위를 표(차원별 단위·다른 표기)와 속성 단위에서 긴 것부터 찾는다. 단위 뒤에 영문·숫자가 이어지면 단위가 아니다 (`GDDR7`의 `G`는 GB가 아니다).
   - 다른 표기는 그 속성의 차원 안에서만 쓴다: 저장 용량 `T`=TB·`G`=GB, 메모리 `G`=GB, IOPS `K`·`KIOPS`=K IOPS, 길이 `인치`·`in`·`"`=inch. 운영 값 `600T`, `545K`가 이 규칙으로 읽힌다.
   - 숫자에 바로 붙은 모르는 영문 단위(`16XB`)나 다른 차원 단위(GHz 속성에 `16GB`)는 "단위 확인 필요"다. 띄어 쓴 뒤의 단위 아닌 말(`8 GDDR7`)은 설명으로 보고 속성 단위로 읽는다.
   - GB·MB 속성의 차원: 분류가 `memory`·`graphics`·`cpu`면 메모리(1GB = 1,024MB), 그 밖은 저장 용량(1TB = 1,000GB).
   - 표에 없는 속성 단위(코어, 개, px, 년, TOPS, kWh/년 …)는 글자가 같을 때만 같은 단위다. 한글 단위가 속성 단위와 다르게 붙은 경우(`2개`를 코어 속성에)는 모르는 단위로 잡지 않는다 (영문 단위만 검사). 운영 데이터에 그런 값은 없다.
4. **비슷한 속성 쌍의 기준**: 기본 속성(`DEFAULT_ATTRIBUTES`)끼리는 설계로 나눈 것(`ram_gb`/`ram_max_gb`)이라 뺀다. 하나 이상이 기본 속성이 아닌 쌍에서 (a) 이름이 공백·기호만 다름, (b) 기본 속성이 아닌 쪽의 키·이름이 기본 속성의 별칭과 같음, (c) 키 단어가 겹침(앞부분 일치 3자 이상, `ver`~`version`)을 본다.

## 운영 DB 점검 결과 요약 (`E-spec-audit.md`)
- 단위가 다른 값 0건, 단위 확인 필요 0건, `value_num` NULL 0건
- 비슷한 속성 11쌍. 모두 가져오기로 생긴 속성(값 0건) ↔ 기본 속성(값 있음): `tbw`/`ssd_tbw`, `accept`/`tg_approval`, `random_read`/`ssd_random_read_kiops` 등
- 값이 없는 제품 1(N5800), 부품 1(AMD Ryzen AI 7 350), 제품-부품 연결 0, 근거 문서가 적힌 값 0
- **데이터는 고치지 않았다.** 실행 전후 `storage/mail.db` 수정 시각 13:59 그대로.

## 테스트: 명령과 출력
```
.venv/Scripts/python.exe -m pytest tests/test_spec_inheritable.py -q
32 passed in 1.30s

.venv/Scripts/python.exe -m pytest tests -q
394 passed in 48.87s
```
- 새 속성 0, 켜고 끄기, 다른 칸만 고쳐도 유지
- `cert` 속성 켜기 거부(저장소 `ValueError`, API 400), 켜진 속성을 `cert`로 옮기기 거부
- 옛 DB에 컬럼이 한 번만 생기고 기존 행은 0
- 단위 환산 14건(같은 차원·다른 차원·전력/용량 비환산), 값 문자열 읽기 11건
- 점검 스크립트: fixture DB에서 네 항목이 모두 나오고, 실행 전후 DB 파일 해시가 같다. 스크립트·단위 모듈에 저장소 임포트가 없다

## 확인하지 못한 것
- 운영 DB의 컬럼 추가는 사용자의 서버 재시작 때 적용된다.
