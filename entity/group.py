"""문서 그룹 정의와 과거 자동 생성 그룹의 원본 값.

신규 그룹은 사용자가 POST /groups로 만든다. DEFAULT_GROUPS는 이전 버전이 자동 생성했던
그룹을 식별하기 위해 유지한다. 서버는 새 DB에 이 목록을 자동으로 넣지 않는다.
"""
from dataclasses import dataclass


@dataclass
class FileGroup:
    id: str            # 과거 그룹의 안정된 키. 신규 그룹은 UUID다.
    name: str          # 화면 표시 이름
    description: str   # 어떤 문서가 들어가는지


DEFAULT_GROUPS: tuple[FileGroup, ...] = (
    FileGroup("product_spec", "제품 사양", "제품제안서, 제품기획서, 개발계획서처럼 우리 제품의 사양표가 들어 있는 문서"),
    FileGroup("component_spec", "부품 사양", "CPU, SSD, 메모리 등 부품의 스펙 시트와 성능 비교 자료"),
    FileGroup("certificate", "인증서", "KC 안전확인, 전자파 적합등록, 에너지효율 등 인증·시험 문서"),
    FileGroup("manual", "매뉴얼", "사용자 매뉴얼, 설치·설정 가이드"),
    FileGroup("sales", "판매 자료", "Sales Guide, 카탈로그, 제안 자료"),
    FileGroup("bid", "입찰 사양서", "발주처가 요구한 사양·조건 문서, 입찰 공고"),
    FileGroup("report", "보고서·회의록", "주간보고, 회의록, 판매 실적 등 내부 기록"),
    FileGroup("general", "일반 문서", "위 분류에 들어가지 않는 문서"),
)

# 과거 기본 그룹의 키. 신규 그룹의 유효성을 검사하는 허용 목록으로 쓰지 않는다.
GROUP_IDS: frozenset[str] = frozenset(group.id for group in DEFAULT_GROUPS)
