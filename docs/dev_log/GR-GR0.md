# GR-GR0 그래프 점검 스크립트

## 변경 파일
- `scripts/audit_graph.py` (신규): 읽기 전용 점검. `sqlite3` `mode=ro`, 저장소 임포트 없음, `--db`로 DB 지정, 마크다운 출력
- `graph_rag/rules.py` (신규): 식별자 규칙 `has_identifier`(GR3-3), 정식 이름 맞춤 키 `spec_match_keys`/`spec_match_key`(GR3-4). DB·저장소·config를 임포트하지 않는 순수 함수
- `tests/test_graph_audit.py` (신규)

## 결정한 것
- 식별자 규칙과 맞춤 키를 점검 스크립트 안에 두지 않고 `graph_rag/rules.py`로 뺐다. GR3의 저장 전 검사가 같은 함수를 쓰게 해서 점검 결과와 실제 거르기가 어긋나지 않게 하려는 것이다. 지금은 점검 스크립트만 쓴다(동작 변경 없음).
- 식별자 = 숫자가 하나 이상 든 영숫자 토큰(`-_.`로 이은 것 포함)이고 기호를 뺀 길이 3자 이상. 지시서 예시(N5800, 5070, PM9C1b, R-R-TGE-N5800)는 통과하고 Tensor 코어·RT 코어·Blackwell 아키텍처·Radeon·Ryzen·XDNA는 빠진다. 3자 하한은 "XDNA 2", "4세대"처럼 숫자 한 자가 붙은 브랜드·세대 표기를 식별자로 보지 않기 위해서다. 그래서 `Windows 11`(부품)도 위반으로 잡힌다.
- 맞춤 키 끝 일반 명사 제거에서 영문 명사(cpu, gpu …)는 앞 글자가 영숫자면 떼지 않는다(`eGPU` 보존). 한글 명사는 붙여 써도 뗀다.
- 제조사 접두어 기본 목록은 `rules.DEFAULT_VENDOR_PREFIXES`에 둔다. `config.GRAPH_VENDOR_PREFIXES`는 GR3에서 이 값을 기본으로 더한다(점검 스크립트는 config를 읽지 않는다).
- GR2 이전 스키마에서는 식별자가 필요한 종류를 GR2 표의 `requires_identifier=1`(product_line, product, component, cert_number)로 본다. 사양 DB 기준 종류는 하위 모델이 있으면 product_line, 없으면 product, 부품은 component로 계산한다(GR4-1 규칙).

## 로컬 운영 DB 점검 결과 (`mode=ro`, 코드 변경 전)

```
# 지식 그래프 점검 (읽기 전용)

- 스키마: GR2 이전 (기본 종류 규칙)
- 관계 종류: complies_with, has_certification, has_component, has_number, issued_by, part_of, variant_of

## 1. 개체 종류별·출처별 개수 (활성)

| 종류 | 출처(creation_origin) | 개수 |
|---|---|---|
| certification | legacy | 2 |
| component | legacy | 1 |
| concept | legacy | 1 |
| product | legacy | 4 |

상태별: active 8

## 1. 관계 종류별·출처별 개수 (활성)

| 관계 종류 | 출처(origin) | 개수 |
|---|---|---|
| part_of | seed | 2 |
| variant_of | spec | 2 |

## 2. 상위 개념 개체와 part_of 관계

| id | 이름 | 출처 |
|---|---|---|
| 1 | KC 인증 | legacy |

| 관계 id | 출발 | 도착 | 출처 |
|---|---|---|---|
| 158 | 자율안전확인 | KC 인증 | seed |
| 159 | 안전확인신고 | KC 인증 | seed |

## 3. 허용 출발·도착 종류를 어긴 관계 (활성)

위반 0건 / 활성 관계 4건

(없음)

## 4. 식별자 규칙을 어기는 개체 (활성)

식별자가 필요한 종류: cert_number, component, product, product_line

위반 1건 (출처별: {'legacy': 1})

| id | 종류 | 이름 | 출처 | 사양 참조 |
|---|---|---|---|---|
| 100 | component | Windows 11 | legacy |  |

## 5. 사양 DB 모델명과 맞춤 키가 같은데 종류가 다른 개체

| id | 현재 종류 | 이름 | 사양 DB 기준 종류 | 출처 |
|---|---|---|---|---|
| 85 | product | A650 Series | product_line | legacy |

## 6. 관계도 등장 위치도 없는 개체

2개
```

## 테스트: 명령과 출력
```
$ .venv/Scripts/python.exe -m pytest tests/test_graph_audit.py -q
..................                                                       [100%]
18 passed in 0.62s
$ .venv/Scripts/python.exe -m pytest tests -q
511 passed in 71.48s (0:01:11)
```

## 확인하지 못한 것 / Gemini에게 요청할 검증
- 캡처가 나온 서버 DB로는 돌리지 않았다(사본을 받지 않음, 지시서 13-5).
- 식별자 3자 하한이 실제 문서 개체에서 놓치는 것이 있는지(예: 2자 모델명) 확인 요청.

## 커밋 해시
(커밋 후 `git log --oneline -1`)
