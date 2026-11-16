# GR 후속 — 부품 카탈로그를 그래프 투영에서 빼기

근거: 사용자 결정 2026-11-16. 현실에서는 부품 DB에 있어도 승인된 부품만 해당 노트북에 들어간다. 부품 DB는 승인 부품 카탈로그라
제품과 이어지는 구조가 아니므로(`product_component` 0건) 부품은 따로 본다. 그래프 투영에서 뺀다.

## 변경 파일
- `repository/graph_projection.py`: 부품 노드는 제품이 실제로 가리키는 것만 만든다 — `product_component` 연결, 제품 사양 값 중 그래프 방식이 `entity`이고 도착 종류가 부품인 값(cpu_model·gpu_model·chipset·wifi)이 정식 이름 맞춤 키로 가리키는 부품. 나머지 부품과 그 사양 값은 넣지 않는다. 예전 투영이 만든 카탈로그 부품 노드(사양 출처, 문서·사람 편집·다른 관계 없음)는 다음 투영에서 지우고 요약에 `catalog_removed`로 센다
- 테스트: `tests/test_graph_projection.py::test_component_catalog_is_not_projected`(신규), `tests/test_graph_spec.py`(연결 안 된 부품은 노드 없음, 연결이 끊긴 부품 노드는 정리)

## 결정한 것
- 문서에 나온 부품 노드, 사람이 고친 노드, 문서·사용자 관계가 있는 노드는 지우지 않는다(사양 참조는 그대로).
- 부품의 사양 값은 그 부품이 노드일 때만 투영한다(제품이 가리키는 CPU의 코어 수 등).
- 그래프 검색(`graph_search`)·문서 추출의 정식 종류 우선도 투영된 노드만 쓰므로 카탈로그 부품에는 붙지 않는다. 문서 추출 때 사양 DB 부품 이름과 같으면 `ref`만 단다(기존 link_specs).

## 운영 DB 사본 예행 (가드 설치, 운영 DB 수정 시각 변화 없음)
```
1회: {'product_lines': 1, 'products': 3, 'components': 1, 'value_nodes': 29, 'variant_of': 2, 'has_component': 0,
      'has_spec': 75, 'entity_relations': 12, 'skipped': 0, 'blocked': 0, 'catalog_removed': 122, 'seconds': 0.034}
2회: 같음, 'catalog_removed': 0, 'seconds': 0.009
활성 개체: component 127 → 5 (사양 DB 부품 1 + 대상 값 노드 4), spec_value 341 → 29
사양 데이터 행 수 그대로: product 4, component 123, spec_value 1572, product_component 0
```

## 테스트
```
$ .venv/Scripts/python.exe -m pytest tests -q
565 passed in 80.10s (0:01:20)
```
