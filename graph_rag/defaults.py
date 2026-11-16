"""그래프 개체·관계 종류의 기본값 (지시서 GR2·GR3). 마이그레이션이 테이블이 비었을 때만 넣는다.

여기 값은 기본값일 뿐이다. 실행 중의 종류 목록은 graph_entity_type·graph_relation_type 테이블에서 읽고,
사용자는 기본 종류를 포함해 모두 고칠 수 있다. DB·저장소를 임포트하지 않는다.
"""
from __future__ import annotations

# 새 종류에 고르는 고정 팔레트 (앞에서부터 아직 쓰지 않은 색)
PALETTE: tuple[str, ...] = (
    "#0E7490", "#F97316", "#14B8A6", "#A855F7", "#EF4444", "#84CC16", "#EAB308", "#6366F1",
    "#0891B2", "#BE185D", "#65A30D", "#9333EA", "#B45309", "#0F766E", "#94A3B8",
)

DEFAULT_ENTITY_TYPES: tuple[dict, ...] = (
    {"key": "product_line", "label": "제품군", "color": "#0E7490", "extract": 1, "requires_identifier": 1,
     "description": "판매 모델들을 묶는 상위 모델(시리즈). 실제 판매 단위가 아니다. 예: A650"},
    {"key": "product", "label": "제품", "color": "#00A4E4", "extract": 1, "requires_identifier": 1,
     "description": "실제 판매 단위의 완제품 모델(노트북·데스크톱·모니터·서버). 예: A650-GA70-OU01, N5800. "
                    "CPU·GPU·SSD는 제품이 아니라 부품이다"},
    {"key": "component", "label": "부품", "color": "#7C5CFF", "extract": 1, "requires_identifier": 1,
     "description": "제품에 들어가는 부품의 모델명. 예: AMD Ryzen AI 7 350, GeForce RTX 5070, Samsung PM9C1b. "
                    "브랜드 이름(Ryzen, Radeon)·기술 이름(Tensor 코어, RT 코어)·아키텍처(Blackwell)는 부품이 아니다"},
    {"key": "spec_value", "label": "사양 값", "color": "#94A3B8", "extract": 0, "requires_identifier": 0,
     "description": "사양 DB의 속성 값 하나. 예: 메모리 용량 64GB. 사양 DB에서만 만든다"},
    {"key": "certification", "label": "인증", "color": "#16A34A", "extract": 1, "requires_identifier": 0,
     "description": "인증·신고·시험의 종류. 예: 안전확인 신고, 적합성 등록"},
    {"key": "cert_number", "label": "인증번호", "color": "#64748B", "extract": 1, "requires_identifier": 1,
     "description": "인증서·등록·신고·시험성적서 번호. 예: R-R-TGE-N5800"},
    {"key": "organization", "label": "기관·회사", "color": "#E19A00", "extract": 1, "requires_identifier": 0,
     "description": "회사, 제조사, 시험기관, 발급기관. 예: NVIDIA, 국립전파연구원"},
    {"key": "standard", "label": "규격", "color": "#DB2777", "extract": 1, "requires_identifier": 0,
     "description": "규격·표준·기준. 예: KN 32, IEC 62368-1"},
)

# 사양 DB 투영(GR4)이 노드를 만드는 종류. 사용 중지하면 투영이 그 종류의 노드를 만들지 않는다
PROJECTION_TYPES = frozenset({"product_line", "product", "component", "spec_value"})

# 기본 관계 종류. extract=0은 문서 추출 대상이 아니다 (사양 DB에서만 만든다)
DEFAULT_RELATION_TYPES: tuple[dict, ...] = (
    {"key": "has_component", "label": "부품", "description": "제품 -> 부품",
     "source": ["product"], "target": ["component"], "extract": 1},
    {"key": "has_certification", "label": "인증", "description": "제품 -> 인증 종류",
     "source": ["product"], "target": ["certification"], "extract": 1},
    {"key": "has_number", "label": "번호", "description": "인증 종류 또는 제품 -> 인증·등록 번호",
     "source": ["product", "certification"], "target": ["cert_number"], "extract": 1},
    {"key": "issued_by", "label": "발급 기관", "description": "인증 종류 또는 번호 -> 발급·시험 기관",
     "source": ["certification", "cert_number"], "target": ["organization"], "extract": 1},
    {"key": "complies_with", "label": "규격 준수", "description": "제품 또는 인증 -> 규격·표준",
     "source": ["product", "certification"], "target": ["standard"], "extract": 1},
    {"key": "variant_of", "label": "상위 모델",
     "description": "파생 모델 -> 상위 모델. 사양 DB에서만 만든다 (LLM 추출 대상이 아니다)",
     "source": ["product"], "target": ["product"], "extract": 0},
)
