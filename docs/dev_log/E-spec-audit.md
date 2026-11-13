<!-- 생성: .venv/Scripts/python.exe scripts/audit_spec_values.py (2026-11-13, 운영 storage/mail.db를 mode=ro로 읽음. 실행 전후 파일 수정 시각 13:59 그대로) -->

# 사양 DB 점검 결과

- 대상: `mail.db` (읽기 전용으로 열었다. 데이터를 고치지 않았다)

## 0. 개수

| 항목 | 개수 |
|---|---|
| 속성 | 90 |
| 제품 | 4 |
| 부품 | 123 |
| 사양 값 | 1572 |
| 제품-부품 연결 | 0 |
| 근거 문서(source_file_id)가 적힌 값 | 0 |

## 1. 값의 단위가 속성 단위와 다른 값

숫자 속성(`number`)의 값 문자열을 비교 코드(`entity/spec_units.py read_number`)와 같은 규칙으로 읽었다.

### 1-1. 다른 단위지만 환산할 수 있음 (0건)

비교 코드는 이 값을 환산해 판정한다. 저장된 `value_num`은 첫 숫자 그대로라 환산 전 값이다.

없음

### 1-2. 단위 확인 필요 (0건)

비교 코드는 이 값을 숫자로 쓰지 않는다 (판정 `unknown`).

없음

## 2. 이름이 비슷한 속성 쌍 (11쌍)

기본 속성(`entity/spec.py DEFAULT_ATTRIBUTES`)끼리는 설계로 나눈 것이라 빼고, 하나 이상이 기본 속성이 아닌 쌍만 본다.

| 속성 A | 속성 B | A 값 수 | B 값 수 | 이유 |
|---|---|---|---|---|
| accept (TG승인 여부, text) | tg_approval (TG 승인 여부, text) | 0 | 122 | 이름이 공백·기호만 다름; accept의 키·이름이 기본 속성 tg_approval의 별칭과 같음 |
| dram (DRAM, text) | ssd_dram (SSD DRAM, text) | 0 | 57 | dram의 키·이름이 기본 속성 ssd_dram의 별칭과 같음; 키 단어가 겹침 |
| form_factors (Form Factors, text) | ssd_form_factor (SSD 폼팩터, text) | 0 | 125 | form_factors의 키·이름이 기본 속성 ssd_form_factor의 별칭과 같음; 키 단어가 겹침 |
| io_ports (단자 구성, text) | rear_ports (후면 포트, text) | 3 | 0 | rear_ports의 키·이름이 기본 속성 io_ports의 별칭과 같음 |
| nand (NAND, text) | ssd_nand (NAND 종류, text) | 0 | 118 | nand의 키·이름이 기본 속성 ssd_nand의 별칭과 같음; 키 단어가 겹침 |
| nvme_ver (NVMe Ver., text) | ssd_nvme_version (NVMe 버전, text) | 0 | 109 | nvme_ver의 키·이름이 기본 속성 ssd_nvme_version의 별칭과 같음; 키 단어가 겹침 |
| random_read (Random Read, text) | ssd_random_read_kiops (랜덤 읽기 IOPS, number, K IOPS) | 0 | 116 | random_read의 키·이름이 기본 속성 ssd_random_read_kiops의 별칭과 같음; 키 단어가 겹침 |
| random_write (Random Write, text) | ssd_random_write_kiops (랜덤 쓰기 IOPS, number, K IOPS) | 0 | 116 | random_write의 키·이름이 기본 속성 ssd_random_write_kiops의 별칭과 같음; 키 단어가 겹침 |
| req_read (Req. Read, text) | ssd_seq_read_mbps (순차 읽기 속도, number, MB/s) | 0 | 122 | req_read의 키·이름이 기본 속성 ssd_seq_read_mbps의 별칭과 같음 |
| req_write (Req. Write, text) | ssd_seq_write_mbps (순차 쓰기 속도, number, MB/s) | 0 | 122 | req_write의 키·이름이 기본 속성 ssd_seq_write_mbps의 별칭과 같음 |
| ssd_tbw (총 쓰기 용량(TBW), number, TB) | tbw (TBW, text) | 115 | 0 | tbw의 키·이름이 기본 속성 ssd_tbw의 별칭과 같음; 키 단어가 겹침 |

## 3. number 속성인데 value_num이 NULL인 값 (0건)

없음

## 4. 값이 없는 제품 (1개)·부품 (1개)

| 제품 모델 | 이름 |
|---|---|
| N5800 | N5800 14세대 노트북 |

| 부품 종류 | 부품 모델 |
|---|---|
| cpu | AMD Ryzen AI 7 350 |

제품-부품 연결: 0건


## 읽는 법 (구현자 메모)



- 1장이 0건인 것은 운영 값이 모두 속성 단위로 적혀 있거나 단위가 없다는 뜻이다. `600T`(TB 속성)는 `T`=TB, `100K`(K IOPS 속성)는 `K`=K IOPS, `8 GDDR7`(GB 속성)은 띄어 쓴 설명으로 읽어 모두 속성 단위와 같다.

- 2장의 쌍은 한쪽(가져오기로 생긴 속성)이 값 0건이고 기본 속성 쪽에 값이 있다. 중복 속성을 합칠지는 사용자가 정한다 (지시서 8절: 데이터 정리는 하지 않는다).

- N5800은 사양 값이 0건이다. 통합 확인 W1(N5800 무게)은 사양 DB가 아니라 문서 근거로 답해야 한다.

- 제품-부품 연결 0건: "이 제품에 들어간 SSD" 같은 질문은 사양 DB가 답하지 못한다 (지시서 10-3).
