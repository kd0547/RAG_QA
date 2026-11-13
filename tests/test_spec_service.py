"""E2: 사양 서비스 (대상 찾기, 유효 사양, 단위, 비교, 조건으로 찾기). fixture DB만 쓴다."""
import sqlite3
from types import SimpleNamespace

import pytest

import repository
from agent import spec_service
from repository.repo_connect import Database
from repository.spec_repository import SpecRepository


@pytest.fixture
def spec(tmp_path, monkeypatch):
    repo = SpecRepository(Database(str(tmp_path / "spec.db")))
    monkeypatch.setattr(repository, "spec_repo", repo)
    for args in [
        ("ram_gb", "메모리 용량", "memory", "number", "GB"),
        ("ram_max_gb", "메모리 최대 용량", "memory", "number", "GB"),
        ("weight_kg", "무게", "body", "number", "kg"),
        ("ssd_gb", "SSD 용량", "storage", "number", "GB"),
        ("ssd_tbw", "총 쓰기 용량(TBW)", "storage", "number", "TB"),
        ("ssd_seq_read_mbps", "순차 읽기 속도", "storage", "number", "MB/s"),
        ("card_reader", "카드리더", "io", "bool", ""),
        ("os", "운영체제", "os", "text", ""),
        ("kc_safety", "KC 안전확인", "cert", "text", ""),
    ]:
        repo.create_attribute(*args)
    repo.update_attribute("ram_max_gb", inheritable=True)

    a650 = repo.create_product("A650", name="A650 Series")
    child = repo.create_product("A650-GA70-PU02", name="Pro", parent_id=a650["id"])
    n5800 = repo.create_product("N5800", name="N5800 14세대 노트북")
    n5800_child = repo.create_product("N5800-GB70-PU02", parent_id=n5800["id"])
    ns = SimpleNamespace(repo=repo, a650=a650, child=child, n5800=n5800, n5800_child=n5800_child)
    ns.add = lambda owner, key, text, option=False: repo.add_spec(
        "component" if "kind" in owner else "product", owner["id"], key, text, is_option=option)
    return ns


def _verdicts(result):
    return [r["verdict"] for r in result["results"]]


# ---------- (나) 유효 사양: 상속 ----------

def test_child_value_wins_over_parent(spec):
    spec.add(spec.a650, "ram_max_gb", "64")
    spec.add(spec.child, "ram_max_gb", "32")
    values = spec_service.effective_specs("product", spec.child["id"])["values"]
    assert [(v["value_text"], v["inherited_from"]) for v in values] == [("32", None)]


def test_inherits_only_allowed_attributes_from_nearest_parent(spec):
    spec.add(spec.a650, "ram_max_gb", "64")
    spec.add(spec.a650, "weight_kg", "1.5kg")   # inheritable=0
    values = spec_service.effective_specs("product", spec.child["id"])["values"]
    assert [(v["attribute_key"], v["inherited_from"]) for v in values] == [("ram_max_gb", "A650")]

    spec.repo.update_attribute("weight_kg", inheritable=True)
    keys = {v["attribute_key"] for v in spec_service.effective_specs("product", spec.child["id"])["values"]}
    assert keys == {"ram_max_gb", "weight_kg"}


def test_grandchild_takes_nearest_ancestor(spec):
    grandchild = spec.repo.create_product("A650-GA70-PU02-X", parent_id=spec.child["id"])
    spec.add(spec.a650, "ram_max_gb", "64")
    spec.add(spec.child, "ram_max_gb", "48")
    values = spec_service.effective_specs("product", grandchild["id"])["values"]
    assert [(v["value_text"], v["inherited_from"]) for v in values] == [("48", "A650-GA70-PU02")]


def test_cert_attribute_never_inherited(spec):
    spec.add(spec.a650, "kc_safety", "R-R-TGE-A650")
    with sqlite3.connect(spec.repo.db.db_path) as conn:  # 화면은 막지만, 값이 들어가 있어도 읽을 때 한 번 더 막는다
        conn.execute("UPDATE spec_attribute SET inheritable = 1 WHERE key = 'kc_safety'")
    assert spec_service.effective_specs("product", spec.child["id"])["values"] == []
    with pytest.raises(ValueError):
        spec.repo.update_attribute("kc_safety", inheritable=True)


# ---------- (라) 비교: 판정 4종 ----------

def _product(spec, model):
    return spec.repo.create_product(model)


def test_ram_32_verdicts_base_option_missing_and_max_separate(spec):
    base16 = _product(spec, "X16")
    spec.add(base16, "ram_gb", "16GB")
    spec.add(base16, "ram_max_gb", "64GB")
    option32 = _product(spec, "X16O32")
    spec.add(option32, "ram_gb", "16GB")
    spec.add(option32, "ram_gb", "32GB", option=True)
    base32 = _product(spec, "X32")
    spec.add(base32, "ram_gb", "32GB")
    empty = _product(spec, "XNONE")
    condition = {"attribute": "ram_gb", "op": ">=", "value": "32", "unit": "GB"}

    assert _verdicts(spec_service.compare("product", base16["id"], [condition])) == ["not_met"]
    assert _verdicts(spec_service.compare("product", option32["id"], [condition])) == ["met_with_option"]
    assert _verdicts(spec_service.compare("product", base32["id"], [condition])) == ["met"]
    assert _verdicts(spec_service.compare("product", empty["id"], [condition])) == ["unknown"]
    # 최대 용량은 다른 속성으로 따로 판정한다
    both = spec_service.compare("product", base16["id"], [condition, {**condition, "attribute": "ram_max_gb"}])
    assert _verdicts(both) == ["not_met", "met"]


def test_units_kg_g_and_tb_gb_and_unknown_unit(spec):
    light = _product(spec, "L1")
    spec.add(light, "weight_kg", "1500g")
    heavy = _product(spec, "L2")
    spec.add(heavy, "weight_kg", "1.5kg")
    assert _verdicts(spec_service.compare("product", light["id"], [{"attribute": "weight_kg", "op": "==", "value": "1.5", "unit": "kg"}])) == ["met"]
    assert _verdicts(spec_service.compare("product", heavy["id"], [{"attribute": "weight_kg", "op": "<=", "value": "1500", "unit": "g"}])) == ["met"]

    ssd = spec.repo.create_component("ssd", "Big SSD")
    spec.add(ssd, "ssd_gb", "1TB")
    assert _verdicts(spec_service.compare("component", ssd["id"], [{"attribute": "ssd_gb", "op": ">=", "value": "1000"}])) == ["met"]
    assert _verdicts(spec_service.compare("component", ssd["id"], [{"attribute": "ssd_gb", "op": ">", "value": "1000GB"}])) == ["not_met"]

    odd = _product(spec, "L3")
    spec.add(odd, "weight_kg", "3XB")
    unknown_value = spec_service.compare("product", odd["id"], [{"attribute": "weight_kg", "op": "<=", "value": "2"}])
    unknown_unit = spec_service.compare("product", light["id"], [{"attribute": "weight_kg", "op": "<=", "value": "2", "unit": "GHz"}])
    assert _verdicts(unknown_value) == ["unknown"] and "단위 확인 필요" in unknown_value["results"][0]["reason"]
    assert _verdicts(unknown_unit) == ["unknown"] and "단위 확인 필요" in unknown_unit["results"][0]["reason"]


def test_missing_attribute_key_and_bad_number_are_unknown(spec):
    product = _product(spec, "K1")
    spec.add(product, "ram_gb", "16")
    result = spec_service.compare("product", product["id"], [
        {"attribute": "ram_size", "op": ">=", "value": "16"},
        {"attribute": "ram_gb", "op": ">=", "value": "많이"},
        {"attribute": "ram_gb", "op": "~", "value": "16"},
    ])
    assert _verdicts(result) == ["unknown", "unknown", "unknown"]
    assert "속성 키가 없습니다" in result["results"][0]["reason"]
    assert spec_service.compare("product", "없는-id", []) is None


def test_no_value_and_explicit_unsupported_bool_differ(spec):
    without = _product(spec, "B0")
    unsupported = _product(spec, "B1")
    spec.add(unsupported, "card_reader", "없음")
    supported = _product(spec, "B2")
    spec.add(supported, "card_reader", "예")
    condition = {"attribute": "card_reader", "op": "exists"}
    assert _verdicts(spec_service.compare("product", without["id"], [condition])) == ["unknown"]
    assert _verdicts(spec_service.compare("product", unsupported["id"], [condition])) == ["not_met"]
    assert _verdicts(spec_service.compare("product", supported["id"], [condition])) == ["met"]
    specs = spec_service.effective_specs("product", without["id"], ["card_reader"])
    assert specs["values"] == [] and specs["missing_attributes"] == ["card_reader"]


def test_text_attribute_same_or_unknown_never_not_met(spec):
    product = _product(spec, "T1")
    spec.add(product, "os", "Windows 11 Pro")
    same = spec_service.compare("product", product["id"], [{"attribute": "os", "op": "==", "value": "windows11 pro"}])
    contains = spec_service.compare("product", product["id"], [{"attribute": "os", "op": "contains", "value": "Win 11"}])
    differs = spec_service.compare("product", product["id"], [{"attribute": "os", "op": "==", "value": "Win11 Pro"}])
    assert _verdicts(same) == ["met"]
    assert _verdicts(contains) == ["unknown"] and _verdicts(differs) == ["unknown"]
    reason = differs["results"][0]["reason"]
    assert "Win11 Pro" in reason and "Windows 11 Pro" in reason


# ---------- 부품 연결 ----------

def test_only_linked_component_values_and_option_link_is_option(spec):
    product = _product(spec, "P1")
    linked = spec.repo.create_component("ssd", "Linked SSD")
    optional = spec.repo.create_component("ssd", "Option SSD")
    unlinked = spec.repo.create_component("ssd", "Other SSD")
    spec.add(linked, "ssd_tbw", "300TB")
    spec.add(optional, "ssd_tbw", "600TB")
    spec.add(unlinked, "ssd_tbw", "1200TB")
    spec.repo.link_component(product["id"], linked["id"])
    spec.repo.link_component(product["id"], optional["id"], is_option=True)

    values = spec_service.effective_specs("product", product["id"])["values"]
    assert {(v["via_component"], v["is_option"]) for v in values} == {("Linked SSD", False), ("Option SSD", True)}
    assert _verdicts(spec_service.compare("product", product["id"], [{"attribute": "ssd_tbw", "op": ">=", "value": "500", "unit": "TB"}])) == ["met_with_option"]
    assert _verdicts(spec_service.compare("product", product["id"], [{"attribute": "ssd_tbw", "op": ">=", "value": "1000"}])) == ["not_met"]


# ---------- (가) 대상 찾기 ----------

def test_resolve_keeps_n5800_and_variant_apart(spec):
    found = spec_service.resolve_items("N5800")
    assert [i["model"] for i in found] == ["N5800"]
    assert found[0]["variants"] == ["N5800-GB70-PU02"]
    assert [i["model"] for i in spec_service.resolve_items("N5800-GB70-PU02")] == ["N5800-GB70-PU02"]
    assert spec_service.resolve_items("n5800-gb70-pu02")[0]["parent_model"] == "N5800"
    # 상위 모델이 없으면 'N5800'으로 파생 모델을 찾지 않는다
    spec.repo.update_product(spec.n5800_child["id"], parent_id=None)
    spec.repo.delete_product(spec.n5800["id"])
    assert spec_service.resolve_items("N5800") == []


def test_resolve_by_token_containment(spec):
    for model in ("Samsung 980 250GB", "Samsung 980 500GB", "Samsung 980 PRO 500GB"):
        spec.repo.create_component("ssd", model)
    assert {i["model"] for i in spec_service.resolve_items("Samsung 980", owner_type="component")} == {
        "Samsung 980 250GB", "Samsung 980 500GB", "Samsung 980 PRO 500GB"}
    assert [i["model"] for i in spec_service.resolve_items("Samsung 980 500GB 대체 가능한 모델", owner_type="component")][0] == "Samsung 980 500GB"
    assert [i["model"] for i in spec_service.resolve_items("a650 series")] == ["A650"]


# ---------- (마) 조건으로 찾기 (대체 모델) ----------

def test_search_with_reference_conditions_lists_only_better_parts_as_all_met(spec):
    rows = {"Ref SSD": ("300TB", "3,500MB/s"), "Better SSD": ("600T", "5,000MB/s"), "Equal SSD": ("300TB", "3500MB/s"),
            "Slow SSD": ("150TB", "2,000MB/s"), "Half SSD": ("600TB", "2,000MB/s"), "Blank SSD": (None, None)}
    for model, (tbw, read) in rows.items():
        component = spec.repo.create_component("ssd", model)
        if tbw:
            spec.add(component, "ssd_tbw", tbw)
            spec.add(component, "ssd_seq_read_mbps", read)
    ref = spec_service.resolve_items("Ref SSD", owner_type="component")[0]
    ref_values = {v["attribute_key"]: v["value_text"] for v in spec_service.effective_specs("component", ref["id"])["values"]}
    conditions = [{"attribute": key, "op": ">=", "value": text} for key, text in ref_values.items()]

    found = spec_service.search_items(owner_type="component", kind="ssd", conditions=conditions)

    all_met = {i["model"] for i in found["items"] if i["met"] == len(conditions)}
    assert all_met == {"Ref SSD", "Better SSD", "Equal SSD"}
    assert found["total"] == 6 and found["limit"] == 20
    half = next(i for i in found["items"] if i["model"] == "Half SSD")
    assert half["not_met_attributes"] == ["ssd_seq_read_mbps"]
    blank = next(i for i in found["items"] if i["model"] == "Blank SSD")
    assert blank["unknown"] == 2 and found["items"][-1]["model"] in ("Blank SSD", "Slow SSD")


def test_search_without_conditions_returns_candidates(spec):
    found = spec_service.search_items(query="A650")
    assert [i["model"] for i in found["items"]] == ["A650"] and found["items"][0]["variants"] == ["A650-GA70-PU02"]
    assert "met" not in found["items"][0]


def test_list_attributes_filters(spec):
    ssd = spec.repo.create_component("ssd", "S1")
    spec.add(ssd, "ssd_tbw", "300TB")
    assert [a["key"] for a in spec_service.list_attributes(kind="ssd")] == ["ssd_tbw"]
    memory = spec_service.list_attributes(category="memory")
    assert {a["key"] for a in memory} == {"ram_gb", "ram_max_gb"}
    assert next(a for a in memory if a["key"] == "ram_max_gb")["inheritable"] is True
