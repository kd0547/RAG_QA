"""제품·부품 사양 도메인 값.

문서(세일즈 가이드 등)는 근거로만 쓰고, 입찰 조건 판정에 쓰는 사양은 여기 정의한 속성 키로
구조화해 저장한다. 속성 사전(spec_attribute)이 있어야 "16GB 이상" 같은 조건을 코드로 비교할 수 있다.

DEFAULT_ATTRIBUTES는 서버가 자동으로 넣지 않는다. 화면의 "기본 속성 추가" 버튼이
POST /specs/attributes/defaults 를 불러 없는 것만 넣는다.
"""
from dataclasses import dataclass

# 속성 분류. 화면 정렬과 그룹 표시용이다.
ATTRIBUTE_CATEGORIES: dict[str, str] = {
    "cpu": "CPU",
    "memory": "메모리",
    "storage": "저장장치",
    "graphics": "그래픽",
    "display": "디스플레이",
    "io": "입출력 단자",
    "network": "네트워크",
    "power": "전원·배터리",
    "body": "크기·무게",
    "os": "운영체제",
    "security": "보안·관리 기능",
    "cert": "인증·규격",
    "other": "기타",
}

DATA_TYPES: dict[str, str] = {
    "number": "숫자",
    "text": "텍스트",
    "bool": "예/아니오",
}

PRODUCT_CATEGORIES: dict[str, str] = {
    "notebook": "노트북",
    "desktop": "데스크톱",
    "aio": "일체형 PC",
    "monitor": "모니터",
    "other": "기타",
}

PRODUCT_STATUSES: dict[str, str] = {
    "active": "판매 중",
    "planned": "출시 예정",
    "eol": "단종",
}

COMPONENT_KINDS: dict[str, str] = {
    "cpu": "CPU",
    "gpu": "GPU",
    "memory": "메모리",
    "ssd": "SSD",
    "wifi": "무선 모듈",
    "display": "패널",
    "battery": "배터리",
    "adapter": "어댑터",
    "other": "기타",
}

# 부품 종류 → 그 부품에 쓰는 속성 분류. 여기 없는 종류는 모든 분류를 쓴다. 기타(other) 분류는 늘 같이 쓴다.
# 화면(frontend/src/spec/styles.ts KIND_CATEGORIES)과 엑셀 양식이 같은 기준으로 속성을 거른다.
KIND_CATEGORIES: dict[str, tuple[str, ...]] = {
    "cpu": ("cpu",),
    "gpu": ("graphics",),
    "memory": ("memory",),
    "ssd": ("storage",),
    "wifi": ("network",),
    "display": ("display",),
    "battery": ("power",),
    "adapter": ("power",),
}


@dataclass(frozen=True)
class SpecAttribute:
    key: str           # 영문 소문자·숫자·_ 로 된 안정 키. 비교 코드가 이 키를 본다
    name: str          # 화면 이름
    category: str      # ATTRIBUTE_CATEGORIES 키
    data_type: str     # DATA_TYPES 키
    unit: str = ""     # number일 때 단위
    description: str = ""
    aliases: tuple[str, ...] = ()  # 엑셀·붙여넣기 표의 행 이름을 이 속성으로 맞출 때 쓰는 별칭 (parser/spec_table.py)


DEFAULT_ATTRIBUTES: tuple[SpecAttribute, ...] = (
    # CPU
    SpecAttribute("cpu_model", "CPU 모델", "cpu", "text", "", "예: AMD Ryzen AI 7 350", aliases=("cpu", "프로세서", "중앙처리장치", "중앙처리장치(cpu)", "cpu 모델명")),
    SpecAttribute("cpu_cores", "CPU 코어 수", "cpu", "number", "코어", aliases=("코어", "코어수", "cpu 코어")),
    SpecAttribute("cpu_threads", "CPU 스레드 수", "cpu", "number", "스레드", aliases=("스레드", "쓰레드", "스레드수")),
    SpecAttribute("cpu_max_ghz", "CPU 최대 클럭", "cpu", "number", "GHz", aliases=("최대클럭", "클럭", "부스트클럭", "max clock")),
    SpecAttribute("cpu_cache_mb", "CPU 캐시", "cpu", "number", "MB", aliases=("캐시", "캐쉬", "캐시메모리", "l3 캐시")),
    SpecAttribute("npu_tops", "NPU 성능", "cpu", "number", "TOPS"),
    SpecAttribute("chipset", "칩셋", "cpu", "text", "", "예: AMD Kraken Mobile Platform", aliases=("chipset", "칩셋")),
    # 메모리
    SpecAttribute("ram_type", "메모리 종류", "memory", "text", "", "예: DDR5 SO-DIMM, LPDDR5x", aliases=("메모리종류", "메모리 타입", "ram type")),
    SpecAttribute("ram_gb", "메모리 용량", "memory", "number", "GB", "기본·옵션 구성을 각각 한 행으로", aliases=("메모리", "memory", "ram", "주기억장치", "주기억장치(ram)", "메모리용량", "기본메모리")),
    SpecAttribute("ram_max_gb", "메모리 최대 용량", "memory", "number", "GB", aliases=("최대메모리", "메모리최대", "메모리 최대", "max memory")),
    SpecAttribute("ram_slots", "메모리 슬롯 수", "memory", "number", "개"),
    # 저장장치
    SpecAttribute("ssd_gb", "SSD 용량", "storage", "number", "GB", "기본·옵션 구성을 각각 한 행으로", aliases=("ssd", "저장장치", "보조기억장치", "ssd용량", "저장용량", "storage", "용량", "capacity")),
    SpecAttribute("ssd_interface", "SSD 인터페이스", "storage", "text", "", "예: M.2 2280 PCIe Gen4 x4 NVMe", aliases=("ssd 인터페이스", "ssd 규격", "저장장치 인터페이스", "interface", "인터페이스")),
    SpecAttribute("ssd_slots", "SSD 슬롯 수", "storage", "number", "개"),
    SpecAttribute("hdd_supported", "HDD 장착 가능", "storage", "bool"),
    # 사내 SSD 비교표 항목 (부품 사양으로 주로 쓴다)
    SpecAttribute("ssd_form_factor", "SSD 폼팩터", "storage", "text", "", "예: M.2, 2.5인치", aliases=("form factor", "form factors", "폼팩터", "폼 팩터")),
    SpecAttribute("ssd_nvme_version", "NVMe 버전", "storage", "text", "", "예: 1.4, 2.0c", aliases=("nvme ver.", "nvme ver", "nvme version", "nvme 버전", "nvme")),
    SpecAttribute("ssd_nand", "NAND 종류", "storage", "text", "", "예: 3D TLC (V8)", aliases=("nand", "낸드", "nand type", "nand flash")),
    SpecAttribute("ssd_dram", "SSD DRAM", "storage", "text", "", "예: LPDDR4 512MB, DRAM Less", aliases=("dram", "dram 캐시", "캐시 dram", "dram cache")),
    SpecAttribute("ssd_seq_read_mbps", "순차 읽기 속도", "storage", "number", "MB/s", "", aliases=("req. read", "req read", "seq. read", "seq read", "sequential read", "순차읽기", "순차 읽기", "읽기속도", "읽기 속도")),
    SpecAttribute("ssd_seq_write_mbps", "순차 쓰기 속도", "storage", "number", "MB/s", "", aliases=("req. write", "req write", "seq. write", "seq write", "sequential write", "순차쓰기", "순차 쓰기", "쓰기속도", "쓰기 속도")),
    SpecAttribute("ssd_random_read_kiops", "랜덤 읽기 IOPS", "storage", "number", "K IOPS", "예: 1,000K", aliases=("random read", "랜덤읽기", "랜덤 읽기", "4k random read", "random read iops")),
    SpecAttribute("ssd_random_write_kiops", "랜덤 쓰기 IOPS", "storage", "number", "K IOPS", "예: 1,000K", aliases=("random write", "랜덤쓰기", "랜덤 쓰기", "4k random write", "random write iops")),
    SpecAttribute("ssd_tbw", "총 쓰기 용량(TBW)", "storage", "number", "TB", "", aliases=("tbw", "내구성", "endurance", "total bytes written")),
    SpecAttribute("m2_slots", "M.2 슬롯 구성", "storage", "text", "", "슬롯마다 한 줄. 예: 2번: M.2 2280 SSD PCIe Gen4x4",
                  aliases=("m.2 slot", "m.2 slots", "m2 slot", "m.2 슬롯", "m.2 슬롯 구성")),
    SpecAttribute("odd", "광학 드라이브(ODD)", "storage", "text", "", "예: 외장형 Super Multi, 미포함",
                  aliases=("odd", "광학드라이브", "광학 드라이브", "dvd", "cd-rom")),
    # 그래픽
    SpecAttribute("gpu_model", "GPU 모델", "graphics", "text", "", "내장·외장을 각각 한 행으로", aliases=("gpu", "vga", "그래픽", "그래픽카드", "비디오", "graphics", "display&video", "display & video", "display/video")),
    SpecAttribute("vram_gb", "비디오 메모리", "graphics", "number", "GB", "공유 메모리면 비고에 적는다", aliases=("비디오메모리", "vram", "그래픽메모리")),
    # 디스플레이
    SpecAttribute("display_inch", "화면 크기", "display", "number", "인치", aliases=("lcd", "화면", "디스플레이", "화면크기", "display", "패널")),
    SpecAttribute("display_resolution", "해상도", "display", "text", "", "예: 1920x1080", aliases=("해상도", "화면해상도", "resolution")),
    SpecAttribute("display_width_px", "해상도 가로", "display", "number", "px"),
    SpecAttribute("display_height_px", "해상도 세로", "display", "number", "px"),
    SpecAttribute("display_refresh_hz", "주사율", "display", "number", "Hz", aliases=("주사율", "refresh rate")),
    # 입출력
    SpecAttribute("hdmi_ports", "HDMI 단자 수", "io", "number", "개", aliases=("hdmi", "hdmi port")),
    SpecAttribute("usb_a_ports", "USB-A 단자 수", "io", "number", "개", aliases=("usb-a", "usb a", "usb type-a")),
    SpecAttribute("usb_c_ports", "USB-C 단자 수", "io", "number", "개", aliases=("usb-c", "usb c", "usb type-c")),
    SpecAttribute("usb_total_ports", "USB 단자 합계", "io", "number", "개", aliases=("usb", "usb port", "usb단자")),
    SpecAttribute("lan_port", "유선 LAN 단자", "io", "bool", aliases=("유선lan", "유선 lan", "lan", "rj-45", "rj45")),
    SpecAttribute("card_reader", "카드리더", "io", "bool", aliases=("카드리더", "카드리더기", "card reader")),
    SpecAttribute("audio_jack", "오디오 잭", "io", "bool"),
    SpecAttribute("audio", "오디오", "io", "text", "", "예: HD Audio, 스피커 2개, 마이크 내장", aliases=("audio", "사운드", "스피커")),
    SpecAttribute("io_ports", "단자 구성", "io", "text", "", "제안서의 I/O Port 칸을 그대로. 단자 수는 위 숫자 속성에 따로",
                  aliases=("i/o port", "i/o ports", "io port", "io ports", "입출력 단자", "포트 구성", "단자")),
    # 네트워크
    SpecAttribute("wifi", "무선 LAN", "network", "text", "", "예: Wi-Fi 6E AX210", aliases=("무선", "무선lan", "무선 lan", "wi-fi", "wireless", "wireless lan", "wlan")),
    SpecAttribute("bluetooth", "블루투스", "network", "text", "", "예: 5.2", aliases=("블루투스", "bt")),
    SpecAttribute("wwan", "무선 데이터 통신(LTE/5G)", "network", "bool"),
    # 전원
    SpecAttribute("battery_wh", "배터리 용량", "power", "number", "Wh", aliases=("배터리", "battery")),
    SpecAttribute("adapter_w", "어댑터 출력", "power", "number", "W", aliases=("어댑터", "adapter", "전원어댑터")),
    SpecAttribute("usb_c_charging", "USB-C 충전", "power", "bool"),
    # 크기·무게
    SpecAttribute("weight_kg", "무게", "body", "number", "kg", aliases=("무게", "중량", "weight")),
    SpecAttribute("dimensions_mm", "크기(W x D x H)", "body", "text", "mm", aliases=("크기", "치수", "사이즈", "size", "dimensions")),
    SpecAttribute("chassis_material", "외장 재질", "body", "text", aliases=("재질", "a/d", "외장")),
    SpecAttribute("housing", "베어본(하우징)", "body", "text", "", "예: Clevo V561KNP Bare-bone (with CPU)",
                  aliases=("housing", "베어본", "barebone", "bare-bone", "하우징")),
    SpecAttribute("keyboard", "키보드", "body", "text", "", "예: 102키, 백라이트, Copilot 키", aliases=("keyboard", "자판")),
    # 운영체제
    SpecAttribute("os", "운영체제", "os", "text", "", "예: Windows 11 Pro", aliases=("운영체제", "운영체제(os)", "operating system", "윈도우")),
    SpecAttribute("software", "기본 소프트웨어", "os", "text", "", "예: 복원 솔루션, 전자매뉴얼",
                  aliases=("s/w", "sw", "software", "소프트웨어", "번들 소프트웨어")),
    # 보안·관리
    SpecAttribute("webcam", "웹캠", "security", "text", "", "예: 5M IR, 없음", aliases=("웹캠", "웹카메라", "카메라", "camera")),
    SpecAttribute("camera_removable", "카메라 기능 제거 가능", "security", "bool", "", "BIOS 비활성화 또는 물리 제거"),
    SpecAttribute("wireless_removable", "무선 기능 제거 가능", "security", "bool"),
    SpecAttribute("bios_password_roles", "BIOS 관리자/사용자 비밀번호 분리", "security", "bool"),
    SpecAttribute("tpm", "TPM", "security", "text", "", "예: TPM 2.0"),
    SpecAttribute("kensington_lock", "켄싱턴 락 슬롯", "security", "bool", aliases=("켄싱턴", "잠금장치", "kensington")),
    # 인증·규격
    SpecAttribute("tg_approval", "TG 승인 여부", "other", "text", "", "예: 승인 완료, 검토 중", aliases=("tg승인 여부", "tg 승인 여부", "tg승인", "tg 승인", "승인 여부", "승인여부", "tg approval", "approval")),
    SpecAttribute("kc_safety", "KC 안전확인", "cert", "text", "", "인증번호"),
    SpecAttribute("kc_emc", "KC 전자파 적합등록", "cert", "text", "", "인증번호"),
    SpecAttribute("energy_efficiency", "에너지 효율", "cert", "text", "", "예: 에너지소비효율 1등급, Energy Star"),
    SpecAttribute("cert_model", "인증 모델명", "cert", "text", "", "KC 등 인증 문서에 적힌 모델명. 제품 모델명과 다를 때. 예: A600",
                  aliases=("인증명", "인증모델", "인증 모델", "certification model")),
    SpecAttribute("accessory", "구성품", "other", "text", "", "예: 어댑터, 전원 코드, 가방",
                  aliases=("accessory", "accessories", "부속품", "액세서리")),
    SpecAttribute("royalty", "로열티", "other", "text", "", "예: Windows 11, NEC", aliases=("royalty", "royalties")),
    SpecAttribute("warranty_years", "보증 기간", "other", "number", "년", aliases=("보증", "보증기간", "보증기한", "보증 기한", "warranty", "warranty period", "a/s")),
)
