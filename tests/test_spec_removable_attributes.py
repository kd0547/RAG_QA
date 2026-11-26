"""기능 제거 가능 여부 속성: 입찰 규격의 "○○ 기능 제거" 요구를 기능별로 판정한다."""
from entity.spec import DEFAULT_ATTRIBUTES
from parser.spec_table import build_attribute_index, normalize_label
from repository.repo_connect import Database
from repository.spec_repository import SpecRepository

REMOVABLE = {
    "camera_removable": "카메라 기능 제거 가능",
    "wireless_removable": "무선 기능 제거 가능",
    "bluetooth_removable": "블루투스 기능 제거 가능",
    "wwan_removable": "무선 데이터 통신(LTE/5G) 기능 제거 가능",
    "mic_removable": "마이크 기능 제거 가능",
    "recovery_removable": "복구모드 제거 가능",
}


def test_removable_attributes_are_bool_security_defaults():
    defaults = {a.key: a for a in DEFAULT_ATTRIBUTES}
    for key, name in REMOVABLE.items():
        assert defaults[key].name == name
        assert (defaults[key].category, defaults[key].data_type) == ("security", "bool")
    assert "블루투스" in defaults["wireless_removable"].description  # 무선 LAN만이라는 것을 밝힌다


def test_table_rows_map_to_removable_attributes_not_to_the_feature_itself():
    index = build_attribute_index([], include_defaults=True)
    for label, key in [("블루투스 제거", "bluetooth_removable"), ("LTE 제거", "wwan_removable"),
                       ("마이크 제거", "mic_removable"), ("Recovery Mode 제거", "recovery_removable"),
                       ("블루투스", "bluetooth")]:
        assert index[normalize_label(label)][0] == key, label


def test_add_default_attributes_adds_only_missing(tmp_path):
    repo = SpecRepository(Database(str(tmp_path / "spec.db")))
    repo.create_attribute("wireless_removable", "무선 기능 제거 가능", "security", "bool", "")
    added = repo.add_default_attributes()
    keys = {a["key"] for a in repo.list_attributes()}
    assert set(REMOVABLE) <= keys
    assert added == len(DEFAULT_ATTRIBUTES) - 1  # 이미 있던 속성은 건드리지 않는다
    assert repo.add_default_attributes() == 0
