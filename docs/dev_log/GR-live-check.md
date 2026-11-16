# GR 실서버 확인

## 캡처가 나온 서버
확인하지 못했다. 그 서버는 사용자가 백업·재시작·전체 다시 만들기를 한 뒤 지시서 11절 표대로 본다 (GR-GR7.md 절차).

## 로컬 서버 (읽기 전용 GET만)
2026-11-16 12:22에 로컬에서 `uvicorn main:app --port 8000`이 새 코드로 시작돼 있었다(구현자가 띄운 것이 아니다). 그 시작으로 로컬 운영 DB에 GR 마이그레이션·사양 투영·프롬프트 v4 등록이 적용됐다. 로컬 DB에는 등록 문서가 없다.

| 확인 | 결과 |
|------|------|
| `GET /graph/stats` | 개체 component 127, product 3, product_line 1, spec_value 341 / 관계 1553(모두 spec) / 지운 관계 1 / 문서 0 |
| `GET /graph/search?q=A650` | matched `A650 Series`(product_line). relations 첫 줄 `A650-GA70-OU01 -[variant_of]-> A650 Series (사양 DB)` 등. `spec_values: 23`, has_spec 관계 없음, `expanded` 없음 |
| `GET /graph/search?q=메모리 64GB 제품` | matched `메모리 용량 64GB`, relations `A650-GA70-PU02 -[has_spec]-> 메모리 용량 64GB (사양 DB)` |
| `GET /graph/schema` | 개체 종류 8, 관계 종류 8(made_by·has_spec 포함, part_of 없음) |
| `GET /prompts` | `v4 근거 ID·사양·그래프 정비` 선택됨, v2·v3 행 유지 |

`/ask` 질문("A650 GPU 알려줘", "N5800 KC 인증 자료")은 실행 기록을 DB에 쓰므로 하지 않았다. 사용자 확인 항목으로 남긴다.
