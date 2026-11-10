"""제품·부품 사양: 속성 사전, 제품·부품 CRUD, 사양 값 파싱, 부품 연결, API 상태 코드를 확인한다."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from entity.spec import DEFAULT_ATTRIBUTES  # noqa: E402
from repository.repo_connect import Database  # noqa: E402
from repository.spec_repository import (  # noqa: E402
    SpecConflictError,
    SpecNotFoundError,
    SpecRepository,
    parse_value,
)


@pytest.fixture
def repo(tmp_path):
    return SpecRepository(Database(str(tmp_path / "spec.db")))


# ---------- 값 파싱 ----------

@pytest.mark.parametrize("text, expected", [
    ("16", 16.0), ("16GB", 16.0), ("4.8GHz 이상", 4.8), ("2,811", 2811.0), ("무게 1.65kg", 1.65),
])
def test_parse_number(text, expected):
    assert parse_value("number", text) == expected


@pytest.mark.parametrize("text, expected", [("예", 1.0), ("있음", 1.0), ("O", 1.0), ("아니오", 0.0), ("없음", 0.0), ("X", 0.0)])
def test_parse_bool(text, expected):
    assert parse_value("bool", text) == expected


def test_parse_rejects_unreadable_values():
    assert parse_value("text", "Windows 11") is None
    with pytest.raises(ValueError):
        parse_value("number", "없음")
    with pytest.raises(ValueError):
        parse_value("bool", "가끔")
    with pytest.raises(ValueError):
        parse_value("number", "   ")


# ---------- 속성 사전 ----------

def test_default_attributes_insert_once(repo):
    assert repo.add_default_attributes() == len(DEFAULT_ATTRIBUTES)
    assert repo.add_default_attributes() == 0
    attributes = repo.list_attributes()
    assert len(attributes) == len(DEFAULT_ATTRIBUTES)
    assert attributes[0]["category"] == "cpu"  # 분류 순서대로 정렬
    assert all(a["usage_count"] == 0 for a in attributes)


def test_attribute_key_validation_and_duplicates(repo):
    created = repo.create_attribute("ram_gb", "메모리", "memory", "number", "GB")
    assert created["key"] == "ram_gb" and created["usage_count"] == 0
    with pytest.raises(ValueError):
        repo.create_attribute("Ram GB", "메모리")
    with pytest.raises(ValueError):
        repo.create_attribute("ok_key", "x", category="nope")
    with pytest.raises(SpecConflictError):
        repo.create_attribute("ram_gb", "다른 이름")


def test_attribute_in_use_cannot_be_deleted_and_type_change_reparses(repo):
    repo.create_attribute("weight", "무게", "body", "text")
    product = repo.create_product("N5800")
    repo.add_spec("product", product["id"], "weight", "1.65kg")
    assert repo.get_product(product["id"])["specs"][0]["value_num"] is None

    with pytest.raises(SpecConflictError):
        repo.delete_attribute("weight")

    updated = repo.update_attribute("weight", data_type="number", unit="kg")
    assert updated["unit"] == "kg" and updated["usage_count"] == 1
    assert repo.get_product(product["id"])["specs"][0]["value_num"] == 1.65

    repo.create_attribute("os", "운영체제", "os", "text")
    repo.add_spec("product", product["id"], "os", "Windows Home")
    with pytest.raises(ValueError):  # 숫자로 못 바꾸는 값이 있으면 자료형 변경 거부
        repo.update_attribute("os", data_type="number")


# ---------- 제품 / 부품 / 사양 값 ----------

def test_sub_models_form_a_tree(repo):
    base = repo.create_product("N5800")
    series = repo.create_product("N5800-GB70", parent_id=base["id"])
    sku = repo.create_product("N5800-GB70-PU02", parent_id=series["id"])

    assert [c["model"] for c in repo.get_product(base["id"])["children"]] == ["N5800-GB70"]
    detail = repo.get_product(sku["id"])
    assert detail["parent_id"] == series["id"]
    assert [a["model"] for a in detail["ancestors"]] == ["N5800", "N5800-GB70"]
    assert {p["model"]: p["child_count"] for p in repo.list_products()} == {"N5800": 1, "N5800-GB70": 1, "N5800-GB70-PU02": 0}

    with pytest.raises(SpecNotFoundError):
        repo.create_product("X1", parent_id="missing")
    with pytest.raises(ValueError):
        repo.update_product(base["id"], parent_id=base["id"])  # 자기 자신
    with pytest.raises(ValueError):
        repo.update_product(base["id"], parent_id=sku["id"])  # 자기 하위 모델
    with pytest.raises(SpecConflictError):
        repo.delete_product(series["id"])  # 하위 모델이 남아 있다

    # 다른 값만 고치면 상위 모델은 그대로, parent_id=None을 넘기면 최상위로 올라간다
    assert repo.update_product(sku["id"], name="PU02")["parent_id"] == series["id"]
    moved = repo.update_product(sku["id"], parent_id=None)
    assert moved["parent_id"] is None and moved["ancestors"] == []
    repo.delete_product(series["id"])
    assert repo.get_product(base["id"])["children"] == []


def test_old_product_table_gets_parent_column(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE product (id TEXT PRIMARY KEY, model TEXT NOT NULL UNIQUE, name TEXT NOT NULL DEFAULT '',"
                 " category TEXT NOT NULL DEFAULT 'notebook', status TEXT NOT NULL DEFAULT 'active', note TEXT NOT NULL DEFAULT '',"
                 " created_at TEXT NOT NULL DEFAULT current_timestamp, updated_at TEXT NOT NULL DEFAULT current_timestamp)")
    conn.execute("INSERT INTO product (id, model) VALUES ('p1', 'N5800')")
    conn.commit()
    conn.close()

    repo = SpecRepository(Database(str(path)))
    child = repo.create_product("N5800-GB70-PU02", parent_id="p1")
    assert repo.get_product("p1")["children"][0]["id"] == child["id"]


def test_product_specs_with_options_and_sources(repo):
    repo.add_default_attributes()
    product = repo.create_product(" N5800 ", "N5800 14세대", "notebook", "active")
    assert product["model"] == "N5800"

    base = repo.add_spec("product", product["id"], "ram_gb", "16GB", source_note="R&D 2026-11-05")
    option = repo.add_spec("product", product["id"], "ram_gb", "32GB", is_option=True, source_file_id="f1", source_page=16)
    assert (base["value_num"], base["is_option"]) == (16.0, False)
    assert (option["value_num"], option["is_option"], option["source_page"]) == (32.0, True, 16)

    with pytest.raises(SpecConflictError):  # 같은 속성·같은 값 중복
        repo.add_spec("product", product["id"], "ram_gb", "16GB")
    with pytest.raises(ValueError):  # 없는 속성
        repo.add_spec("product", product["id"], "nope", "1")
    with pytest.raises(SpecNotFoundError):  # 없는 제품
        repo.add_spec("product", "missing", "ram_gb", "1")

    changed = repo.update_spec(option["id"], value_text="64GB", note="최대 구성")
    assert changed["value_num"] == 64.0 and changed["note"] == "최대 구성" and changed["is_option"] is True

    detail = repo.get_product(product["id"])
    assert [s["value_text"] for s in detail["specs"]] == ["16GB", "64GB"]
    assert repo.list_products()[0]["spec_count"] == 2

    repo.delete_spec(base["id"])
    assert repo.get_product(product["id"])["spec_count"] == 1


def test_component_link_and_delete_rules(repo):
    repo.add_default_attributes()
    product = repo.create_product("A650")
    cpu = repo.create_component("cpu", "AMD Ryzen AI 7 350", "AMD")
    repo.add_spec("component", cpu["id"], "cpu_cores", "8")
    with pytest.raises(SpecConflictError):
        repo.create_component("cpu", "AMD Ryzen AI 7 350")

    linked = repo.link_component(product["id"], cpu["id"])
    assert linked["components"][0]["model"] == "AMD Ryzen AI 7 350" and linked["components"][0]["is_option"] is False
    relinked = repo.link_component(product["id"], cpu["id"], is_option=True, note="상위 옵션")
    assert relinked["components"][0]["is_option"] is True and relinked["components"][0]["link_note"] == "상위 옵션"
    assert repo.get_component(cpu["id"])["products"][0]["model"] == "A650"

    with pytest.raises(SpecConflictError):  # 제품이 쓰는 부품은 못 지운다
        repo.delete_component(cpu["id"])

    repo.unlink_component(product["id"], cpu["id"])
    repo.delete_component(cpu["id"])
    assert repo.list_components() == []
    assert repo.get_component(cpu["id"]) is None

    repo.add_spec("product", product["id"], "weight_kg", "2.16")
    repo.delete_product(product["id"])
    assert repo.list_products() == []
    assert repo.get_spec(1) is None or repo.get_spec(1)["owner_id"] != product["id"]  # 사양 값도 함께 삭제


# ---------- API ----------

@pytest.fixture
def client(tmp_path, monkeypatch):
    repo = SpecRepository(Database(str(tmp_path / "api.db")))
    repository = ModuleType("repository")
    repository.spec_repo = repo
    monkeypatch.setitem(sys.modules, "repository", repository)

    spec = importlib.util.spec_from_file_location("specs_router_test", PROJECT_ROOT / "app" / "routers" / "specs.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    app = FastAPI()
    app.include_router(module.router)
    with TestClient(app) as c:
        yield c


def test_api_flow(client):
    assert "component_kinds" in client.get("/specs/meta").json()
    assert client.post("/specs/attributes/defaults").json()["added"] == len(DEFAULT_ATTRIBUTES)

    product = client.post("/specs/products", json={"model": "N5800", "name": "N5800 14세대"})
    assert product.status_code == 201
    pid = product.json()["id"]
    assert client.post("/specs/products", json={"model": "N5800"}).status_code == 409
    assert client.post("/specs/products", json={"model": "X", "status": "nope"}).status_code == 400
    sub = client.post("/specs/products", json={"model": "N5800-GB70-PU02", "parent_id": pid})
    assert sub.status_code == 201 and sub.json()["ancestors"][0]["model"] == "N5800"
    assert client.post("/specs/products", json={"model": "N5800-Z", "parent_id": "missing"}).status_code == 404
    assert client.delete(f"/specs/products/{pid}").status_code == 409  # 하위 모델이 있다
    assert client.put(f"/specs/products/{pid}", json={"parent_id": sub.json()["id"]}).status_code == 400
    assert client.delete(f"/specs/products/{sub.json()['id']}").status_code == 204

    value = client.post("/specs/values", json={"owner_type": "product", "owner_id": pid, "attribute_key": "ram_gb", "value_text": "16GB"})
    assert value.status_code == 201 and value.json()["value_num"] == 16.0
    assert client.post("/specs/values", json={"owner_type": "product", "owner_id": pid, "attribute_key": "ram_gb", "value_text": "없음"}).status_code == 400
    assert client.put(f"/specs/values/{value.json()['id']}", json={"is_option": True}).json()["is_option"] is True

    cpu = client.post("/specs/components", json={"kind": "cpu", "model": "Core i7-1355U", "vendor": "Intel"}).json()
    linked = client.put(f"/specs/products/{pid}/components", json={"component_id": cpu["id"], "is_option": False})
    assert linked.status_code == 200 and linked.json()["components"][0]["id"] == cpu["id"]
    assert client.delete(f"/specs/components/{cpu['id']}").status_code == 409
    assert client.delete(f"/specs/products/{pid}/components/{cpu['id']}").status_code == 200
    assert client.delete(f"/specs/components/{cpu['id']}").status_code == 204

    detail = client.get(f"/specs/products/{pid}").json()
    assert detail["spec_count"] == 1 and detail["components"] == []
    assert client.delete("/specs/attributes/ram_gb").status_code == 409  # 사용 중
    assert client.delete(f"/specs/values/{value.json()['id']}").status_code == 204
    assert client.delete("/specs/attributes/ram_gb").status_code == 204
    assert client.get("/specs/products/missing").status_code == 404
    assert client.delete(f"/specs/products/{pid}").status_code == 204
    assert client.get("/specs/products").json() == []
