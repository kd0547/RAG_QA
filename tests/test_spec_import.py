"""사양 표 가져오기: 텍스트·마크다운·엑셀 읽기, 속성 맞추기, 값 나누기, 저장 규칙, API 상태 코드."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import openpyxl
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from parser.spec_table import analyze_grid, grid_from_text, grid_from_xlsx, split_cell  # noqa: E402
from repository.repo_connect import Database  # noqa: E402
from repository.spec_repository import SpecImportError, SpecRepository  # noqa: E402


@pytest.fixture
def repo(tmp_path):
    r = SpecRepository(Database(str(tmp_path / "spec.db")))
    r.add_default_attributes()
    return r


# ---------- 읽기 ----------

def test_grid_from_tab_markdown_and_csv():
    tab = "항목\tN5800\tA650\n메모리\t16\t32\n\n무게\t1.75\t2.16\n"
    assert grid_from_text(tab) == [["항목", "N5800", "A650"], ["메모리", "16", "32"], ["무게", "1.75", "2.16"]]

    md = "| 속성 | A650 |\n|---|---|\n| 해상도 | 2560x1600 |"
    assert grid_from_text(md) == [["속성", "A650"], ["해상도", "2560x1600"]]

    csv_text = '항목,A650\n"크기(W x D x H)","358 x 258.6 x 19.9"\n'
    assert grid_from_text(csv_text) == [["항목", "A650"], ["크기(W x D x H)", "358 x 258.6 x 19.9"]]


def test_grid_from_xlsx_fills_merged_cells(tmp_path):
    path = tmp_path / "spec.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["속성키", "속성명", "단위", "N5800", "A650"])
    ws.append(["ram_gb", "메모리 용량", "GB", 16, "16 / 32(옵션)"])
    ws.append(["weight_kg", "무게", "kg", 1.75, 2.16])
    ws.append([None, None, None, None, None])
    wb.save(path)

    grid = grid_from_xlsx(path)

    assert grid[0] == ["속성키", "속성명", "단위", "N5800", "A650"]
    assert grid[1] == ["ram_gb", "메모리 용량", "GB", "16", "16 / 32(옵션)"]
    assert len(grid) == 3  # 빈 행 제거


def test_split_cell_options():
    assert split_cell("16GB / 32GB / 64GB") == [
        {"value_text": "16GB", "is_option": False},
        {"value_text": "32GB", "is_option": True},
        {"value_text": "64GB", "is_option": True},
    ]
    # 옵션 표시가 있으면 표시된 것만 옵션이다
    assert split_cell("16GB(옵션)\n32GB") == [
        {"value_text": "16GB", "is_option": True},
        {"value_text": "32GB", "is_option": False},
    ]
    assert split_cell("") == []
    # 붙은 슬래시(단위·N/A)는 나누지 않고, 미정 표기는 건너뛴다
    assert split_cell("3,500MB/s") == [{"value_text": "3,500MB/s", "is_option": False}]
    assert split_cell("500GB (w/Hsink)") == [{"value_text": "500GB (w/Hsink)", "is_option": False}]
    assert split_cell("PCIe Gen4x4 / PCIe Gen5x2") == [
        {"value_text": "PCIe Gen4x4", "is_option": False},
        {"value_text": "PCIe Gen5x2", "is_option": True},
    ]
    assert split_cell("N/A") == [] and split_cell("TBD") == [] and split_cell("?") == []
    assert split_cell("1.4 Spec (실제 1.3)") == [{"value_text": "1.4 Spec (실제 1.3)", "is_option": False}]


def test_default_attributes_cover_company_ssd_sheet(repo):
    """사내 SSD 비교표의 행 이름이 기본 속성에 맞는지."""
    grid = grid_from_text(
        "항목\tPM9A1 512GB\t980 PRO 1TB\n"
        "용량\t512GB\t1TB\nInterface\tPCIe Gen4x4\tPCIe Gen4x4\nNVMe Ver.\t1.4\t1.3c\nForm Factors\tM.2\tM.2\n"
        "NAND\t3D TLC (V6)\t3D TLC\nDRAM\tN/A\tLPDDR4 1GB\nReq. Read\t6,900MB/s\t7,000MB/s\nReq. Write\t5,000MB/s\t5,000MB/s\n"
        "Random Read\t800K\t1,000K\nRandom Write\t1,000K\t1,000K\nTBW\t300TB\t600TB\n보증기한\t5년\tTBD\nTG승인 여부\t승인 완료\t?\n"
    )
    preview = analyze_grid(grid, repo.list_attributes())
    keys = {r["label"]: r["attribute_key"] for r in preview["rows"]}
    assert keys == {
        "용량": "ssd_gb", "Interface": "ssd_interface", "NVMe Ver.": "ssd_nvme_version", "Form Factors": "ssd_form_factor",
        "NAND": "ssd_nand", "DRAM": "ssd_dram", "Req. Read": "ssd_seq_read_mbps", "Req. Write": "ssd_seq_write_mbps",
        "Random Read": "ssd_random_read_kiops", "Random Write": "ssd_random_write_kiops", "TBW": "ssd_tbw",
        "보증기한": "warranty_years", "TG승인 여부": "tg_approval",
    }
    rows = {r["label"]: r for r in preview["rows"]}
    assert rows["Req. Read"]["cells"][0]["values"] == [{"value_text": "6,900MB/s", "is_option": False, "error": None}]
    assert rows["DRAM"]["cells"][0]["values"] == []  # N/A는 건너뜀
    assert rows["보증기한"]["cells"][1]["values"] == []  # TBD도 건너뜀
    assert all(v["error"] is None for r in preview["rows"] for c in r["cells"] for v in c["values"])

    summary = repo.import_values(
        "component", kind="ssd",
        columns=[{"header": c["header"]} for c in preview["columns"]],
        rows=[{"attribute_key": r["attribute_key"], "cells": [c["raw"] for c in r["cells"]]} for r in preview["rows"]],
    )
    assert summary["owners_created"] == 2
    pm9a1 = repo.find_owner("component", "PM9A1 512GB", "ssd")
    specs = {s["attribute_key"]: s for s in repo.get_component(pm9a1["id"])["specs"]}
    assert specs["ssd_seq_read_mbps"]["value_num"] == 6900.0
    assert specs["ssd_tbw"]["value_num"] == 300.0
    assert specs["warranty_years"]["value_num"] == 5.0
    assert "ssd_dram" not in specs


def test_analyze_matches_key_name_alias_and_flags_errors(repo):
    attributes = repo.list_attributes()
    grid = grid_from_text(
        "항목\t단위\tN5800\tA650\n"
        "ram_gb\tGB\t16\t16 / 32(옵션)\n"       # 키
        "무게\tkg\t1.75kg\t2.16\n"              # 이름
        "중앙처리장치(CPU)\t\ti7\tRyzen\n"       # 별칭
        "보증기간\t년\t3\t없음\n"               # 숫자 못 읽음
        "알 수 없는 항목\t\tA\tB\n"             # 못 맞춤
        "빈 행\t\t\t\n"                         # 값 없음 → 제외
    )

    preview = analyze_grid(grid, attributes)

    assert [c["header"] for c in preview["columns"]] == ["N5800", "A650"]
    assert preview["skipped_columns"] == ["단위"]
    rows = {r["label"]: r for r in preview["rows"]}
    assert rows["ram_gb"]["match"] == "key"
    assert rows["무게"]["attribute_key"] == "weight_kg" and rows["무게"]["match"] == "name"
    assert rows["중앙처리장치(CPU)"]["attribute_key"] == "cpu_model" and rows["중앙처리장치(CPU)"]["match"] == "alias"
    assert rows["보증기간"]["cells"][1]["values"][0]["error"]
    assert rows["알 수 없는 항목"]["attribute_key"] is None
    assert "빈 행" not in rows
    assert preview["unmatched_rows"] == 1
    assert rows["ram_gb"]["cells"][1]["values"] == [
        {"value_text": "16", "is_option": False, "error": None},
        {"value_text": "32", "is_option": True, "error": None},
    ]


def test_analyze_requires_model_columns(repo):
    with pytest.raises(ValueError):
        analyze_grid([["항목"], ["메모리"]], repo.list_attributes())
    with pytest.raises(ValueError):
        analyze_grid([["항목", "단위"], ["메모리", "GB"]], repo.list_attributes())


# ---------- 저장 ----------

def test_import_creates_owners_replaces_values_and_adds_attribute(repo):
    existing = repo.create_product("N5800", "N5800 14세대")
    repo.add_spec("product", existing["id"], "ram_gb", "8GB")  # 표의 값으로 바뀌어야 한다
    repo.add_spec("product", existing["id"], "os", "Windows 10")  # 표에 없는 속성은 그대로

    summary = repo.import_values(
        "product",
        columns=[{"header": "n5800", "owner_id": None, "create": True}, {"header": "A650", "owner_id": None, "create": True}, {"header": "X1", "skip": True}],
        rows=[
            {"attribute_key": "ram_gb", "cells": ["16GB", "16 / 32(옵션)", "999"]},
            {"attribute_key": "weight_kg", "cells": ["1.75kg", "", "1"]},
            {"attribute_key": None, "new_attribute": {"key": "fan_count", "name": "팬 수", "category": "body", "data_type": "number", "unit": "개"}, "cells": ["1", "2", ""]},
            {"attribute_key": None, "cells": ["건너뜀", "건너뜀", ""]},
        ],
        source_note="R&D 2026-11",
    )

    assert summary["owners_created"] == 1  # A650만 새로. n5800은 대소문자 무시하고 기존 것
    assert summary["attributes_created"] == 1
    assert summary["values_replaced"] == 1  # ram_gb 8GB
    assert summary["values_added"] == 6  # 16 / 16,32 / 1.75 / 1,2
    assert summary["rows_skipped"] == 1

    n5800 = repo.get_product(existing["id"])
    values = {(s["attribute_key"], s["value_text"]): s for s in n5800["specs"]}
    assert ("ram_gb", "16GB") in values and ("ram_gb", "8GB") not in values
    assert ("os", "Windows 10") in values
    assert values[("fan_count", "1")]["value_num"] == 1.0 and values[("fan_count", "1")]["source_note"] == "R&D 2026-11"

    a650 = next(p for p in repo.list_products() if p["model"] == "A650")
    specs = repo.get_product(a650["id"])["specs"]
    assert sorted((s["value_text"], s["is_option"]) for s in specs if s["attribute_key"] == "ram_gb") == [("16", False), ("32", True)]
    assert all(s["attribute_key"] != "weight_kg" for s in specs)  # 빈 칸은 건너뜀
    assert len(repo.list_products()) == 2  # skip 열은 등록되지 않는다


def test_import_is_all_or_nothing(repo):
    with pytest.raises(SpecImportError) as info:
        repo.import_values(
            "product",
            columns=[{"header": "A650"}],
            rows=[
                {"attribute_key": "ram_gb", "cells": ["16GB"]},
                {"attribute_key": "weight_kg", "cells": ["무거움"]},
                {"attribute_key": "nope", "cells": ["1"]},
            ],
        )
    errors = info.value.errors
    assert {(e["row"], e["column"]) for e in errors} == {(1, 0), (2, None)}
    assert repo.list_products() == []  # 제품도 만들지 않았다


def test_import_components_with_kind(repo):
    summary = repo.import_values(
        "component",
        kind="cpu",
        columns=[{"header": "AMD Ryzen AI 7 350"}, {"header": "Core i7-1355U"}],
        rows=[{"attribute_key": "cpu_cores", "cells": ["8", "10"]}, {"attribute_key": "cpu_max_ghz", "cells": ["5.0GHz", "5.0"]}],
    )
    assert summary["owners_created"] == 2 and summary["values_added"] == 4
    components = repo.list_components("cpu")
    assert [c["model"] for c in components] == ["AMD Ryzen AI 7 350", "Core i7-1355U"]
    assert repo.find_owner("component", "amd ryzen ai 7 350", "cpu")["id"] == components[0]["id"]
    with pytest.raises(ValueError):
        repo.import_values("component", kind="nope", columns=[{"header": "x"}], rows=[])


# ---------- API ----------

@pytest.fixture
def client(tmp_path, monkeypatch):
    repo = SpecRepository(Database(str(tmp_path / "api.db")))
    repo.add_default_attributes()
    repo.create_product("N5800")
    repository = ModuleType("repository")
    repository.spec_repo = repo
    monkeypatch.setitem(sys.modules, "repository", repository)

    spec = importlib.util.spec_from_file_location("spec_import_router_test", PROJECT_ROOT / "app" / "routers" / "spec_import.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    app = FastAPI()
    app.include_router(module.router)
    with TestClient(app) as c:
        yield c, repo


def test_parse_image_uses_vlm_ocr(client, monkeypatch):
    """화면 캡처는 ocr_image 결과(마크다운 표)를 표로 읽는다. 표가 아닌 앞뒤 글은 버린다."""
    c, _ = client
    fake = ModuleType("ocr.provider")
    fake.ocr_image = lambda content: (
        "## SSD 비교표\n\n| 항목 | PM9A1 512GB | 980 PRO 1TB |\n|---|---|---|\n| 용량 | 512GB | 1TB |\n| Req. Read | 6,900MB/s | 7,000MB/s |\n\n(설명: 표 캡처)"
    )
    monkeypatch.setitem(sys.modules, "ocr.provider", fake)

    response = c.post(
        "/specs/import/parse",
        data={"owner_type": "component", "kind": "ssd"},
        files={"file": ("capture.png", b"\x89PNG\r\n\x1a\nfake", "image/png")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "캡처 이미지 (VLM 인식)"
    assert body["recognized_text"].startswith("| 항목 |")
    assert [c["header"] for c in body["columns"]] == ["PM9A1 512GB", "980 PRO 1TB"]
    assert [r["attribute_key"] for r in body["rows"]] == ["ssd_gb", "ssd_seq_read_mbps"]

    fake.ocr_image = lambda content: "표가 없는 그림입니다."
    assert c.post("/specs/import/parse", data={"owner_type": "product"}, files={"file": ("shot.jpg", b"x", "image/jpeg")}).status_code == 400

    def boom(content):
        raise RuntimeError("LLM down")
    fake.ocr_image = boom
    assert c.post("/specs/import/parse", data={"owner_type": "product"}, files={"file": ("shot.png", b"x", "image/png")}).status_code == 502


def test_parse_apply_and_template_endpoints(client, tmp_path):
    c, repo = client
    text = "항목\tN5800\tA650\n메모리\t16GB\t16 / 32(옵션)\n무게\t1.75\t2.16\n"

    preview = c.post("/specs/import/parse", data={"owner_type": "product", "text": text})
    assert preview.status_code == 200
    body = preview.json()
    assert body["columns"][0]["owner_id"] is not None and body["columns"][1]["owner_id"] is None  # N5800은 기존
    assert [r["attribute_key"] for r in body["rows"]] == ["ram_gb", "weight_kg"]

    bad = c.post("/specs/import/apply", json={
        "owner_type": "product",
        "columns": [{"header": "A650"}],
        "rows": [{"attribute_key": "weight_kg", "cells": ["무거움"]}],
    })
    assert bad.status_code == 400
    assert bad.json()["detail"]["errors"][0]["row"] == 0

    ok = c.post("/specs/import/apply", json={
        "owner_type": "product",
        "source_note": "테스트",
        "columns": [{"header": col["header"], "owner_id": col["owner_id"], "create": True} for col in body["columns"]],
        "rows": [{"attribute_key": r["attribute_key"], "cells": [cell["raw"] for cell in r["cells"]]} for r in body["rows"]],
    })
    assert ok.status_code == 200
    assert ok.json()["owners_created"] == 1 and ok.json()["values_added"] == 5

    assert c.post("/specs/import/parse", data={"owner_type": "component", "text": text}).status_code == 400  # kind 없음
    assert c.post("/specs/import/parse", data={"owner_type": "product"}).status_code == 400  # 입력 없음

    xlsx_path = tmp_path / "in.xlsx"
    wb = openpyxl.Workbook()
    wb.active.append(["속성", "N5800"])
    wb.active.append(["운영체제", "Windows 11"])
    wb.save(xlsx_path)
    with xlsx_path.open("rb") as f:
        uploaded = c.post("/specs/import/parse", data={"owner_type": "product"}, files={"file": ("in.xlsx", f, "application/octet-stream")})
    assert uploaded.status_code == 200 and uploaded.json()["rows"][0]["attribute_key"] == "os"

    template = c.get("/specs/import/template", params={"owner_type": "product"})
    assert template.status_code == 200
    wb = openpyxl.load_workbook(filename=__import__("io").BytesIO(template.content))
    ws = wb.worksheets[0]
    header = [cell.value for cell in ws[1]]
    assert header[:4] == ["분류", "속성키", "속성명", "단위"] and "A650" in header and "N5800" in header
    row = next(r for r in ws.iter_rows(min_row=2, values_only=True) if r[1] == "ram_gb")
    assert row[header.index("A650")] == "16 / 32(옵션)"  # 기존 값이 채워져 내려온다


# ---------- 엑셀 양식 (상위 모델·제품 이름 행, 병합 셀) ----------

def test_row_matching_missing_default_attribute_suggests_new_attribute():
    grid = [["항목", "A650"], ["인증명", "A600"], ["Housing", "Clevo V561KNP"]]
    preview = analyze_grid(grid, [])  # 속성 사전이 비어 있다
    rows = {r["label"]: r for r in preview["rows"]}
    assert rows["인증명"]["attribute_key"] is None and rows["인증명"]["new_attribute"]["key"] == "cert_model"
    assert rows["Housing"]["new_attribute"]["name"] == "베어본(하우징)"
    assert preview["unmatched_rows"] == 0


def _upload(c, wb, tmp_path, name="filled.xlsx"):
    path = tmp_path / name
    wb.save(path)
    with path.open("rb") as f:
        return c.post("/specs/import/parse", data={"owner_type": "product"}, files={"file": (name, f, "application/octet-stream")})


def _apply_preview(c, preview):
    return c.post("/specs/import/apply", json={
        "owner_type": "product",
        "columns": [{"header": col["header"], "owner_id": col["owner_id"], "create": True,
                     "parent_model": col["parent_model"], "name": col["name"], "category": col.get("category")} for col in preview["columns"]],
        "rows": [{"attribute_key": r["attribute_key"], "new_attribute": r["new_attribute"],
                  "cells": [cell["raw"] for cell in r["cells"]]} for r in preview["rows"]],
    })


def test_filled_template_creates_series_tree_and_shares_merged_values(client, tmp_path):
    c, repo = client
    template = c.get("/specs/import/template", params={"owner_type": "product"})
    wb = openpyxl.load_workbook(filename=__import__("io").BytesIO(template.content))
    assert wb.sheetnames == ["제품 사양", "작성 안내", "작성 예시"]
    ws = wb.worksheets[0]
    labels = [ws.cell(r, 3).value for r in range(1, 4)]
    assert labels == ["속성명", "상위 모델", "제품 이름"]
    keys = [ws.cell(r, 2).value for r in range(2, ws.max_row + 1)]
    assert {"cert_model", "housing", "chipset", "io_ports"} <= set(keys)  # 제안서 항목 기본 속성

    # 시리즈 A650과 파생 모델 둘을 채운다. CPU·인증 모델명은 세 열 병합(공통), 메모리는 칸마다
    assert ws.cell(1, 5).value == "N5800"  # 등록된 제품은 열로 내려온다. 새 모델은 그 뒤(F열~)에 적는다
    ws.cell(1, 6, "A650"), ws.cell(1, 7, "A650-GA70-OU01")
    ws.cell(1, 8, "A650-GA70-PU02")
    ws.cell(2, 7, "A650"), ws.cell(2, 8, "a650")  # 대소문자 무시
    ws.cell(3, 6, "A650 Series"), ws.cell(3, 7, "Home"), ws.cell(3, 8, "Pro")
    row_of = {ws.cell(r, 2).value: r for r in range(2, ws.max_row + 1)}
    ws.cell(row_of["cpu_model"], 6, "AMD Ryzen AI 7 350")
    ws.merge_cells(start_row=row_of["cpu_model"], start_column=6, end_row=row_of["cpu_model"], end_column=8)
    ws.cell(row_of["cert_model"], 6, "A600")
    ws.merge_cells(start_row=row_of["cert_model"], start_column=6, end_row=row_of["cert_model"], end_column=8)
    ws.cell(row_of["ram_gb"], 7, "16"), ws.cell(row_of["ram_gb"], 8, "64")

    preview = _upload(c, wb, tmp_path)
    assert preview.status_code == 200, preview.text
    body = preview.json()
    columns = {col["header"]: col for col in body["columns"]}
    assert set(columns) == {"N5800", "A650", "A650-GA70-OU01", "A650-GA70-PU02"}  # 기존 N5800 열도 내려왔다
    assert columns["A650-GA70-OU01"]["parent_model"] == "A650" and columns["A650-GA70-PU02"]["name"] == "Pro"
    assert all(r["label"] not in ("상위 모델", "제품 이름") for r in body["rows"])
    cert = next(r for r in body["rows"] if r["label"] == "인증 모델명")
    assert cert["attribute_key"] == "cert_model"  # 기본 속성을 넣어 둔 사전이라 바로 맞는다

    applied = _apply_preview(c, body)
    assert applied.status_code == 200, applied.text
    assert applied.json()["parents_set"] == 2

    by_model = {p["model"]: p for p in repo.list_products()}
    series = repo.get_product(by_model["A650"]["id"])
    assert series["name"] == "A650 Series"
    assert [child["model"] for child in series["children"]] == ["A650-GA70-OU01", "A650-GA70-PU02"]
    pro = repo.get_product(by_model["A650-GA70-PU02"]["id"])
    assert pro["name"] == "Pro"
    specs = {s["attribute_key"]: s["value_text"] for s in pro["specs"]}
    assert specs == {"cpu_model": "AMD Ryzen AI 7 350", "cert_model": "A600", "ram_gb": "64"}

    # 다시 내려받으면 상위 모델 바로 뒤에 파생 모델이 오고, 모델 정보 행이 채워져 있다
    again = openpyxl.load_workbook(filename=__import__("io").BytesIO(c.get("/specs/import/template").content)).worksheets[0]
    header = [cell.value for cell in again[1]][4:]
    assert header == ["A650", "A650-GA70-OU01", "A650-GA70-PU02", "N5800"]
    assert [again.cell(2, col).value for col in range(5, 9)] == [None, "A650", "A650", None]


def test_template_parent_errors_and_self_reference(client):
    c, repo = client
    base = {"owner_type": "product", "rows": [{"attribute_key": "os", "cells": ["Windows 11"]}]}
    missing = c.post("/specs/import/apply", json={**base, "columns": [{"header": "X1-AA", "parent_model": "X1"}]})
    assert missing.status_code == 400 and "X1" in missing.json()["detail"]["errors"][0]["message"]
    assert all(p["model"] != "X1-AA" for p in repo.list_products())  # 아무것도 저장하지 않는다

    # 병합 셀이 시리즈 열까지 덮어 자기 이름이 들어간 칸은 무시한다
    ok = c.post("/specs/import/apply", json={**base, "columns": [{"header": "N5800", "parent_model": "N5800"}]})
    assert ok.status_code == 200 and ok.json()["parents_set"] == 0


def test_label_falls_back_to_name_when_key_is_blank():
    grid = [["분류", "속성키", "속성명", "단위", "A650"], ["CPU", "", "CPU 모델", "", "Ryzen"], ["기타", "", "모르는 항목", "", "x"]]
    preview = analyze_grid(grid, [{"key": "cpu_model", "name": "CPU 모델", "data_type": "text", "unit": ""}])
    assert [c["header"] for c in preview["columns"]] == ["A650"]
    assert [(r["label"], r["attribute_key"]) for r in preview["rows"]] == [("CPU 모델", "cpu_model"), ("모르는 항목", None)]
    assert preview["unmatched_rows"] == 1


def test_component_template_keeps_only_that_kind(client):
    c, _ = client
    wb = openpyxl.load_workbook(filename=__import__("io").BytesIO(
        c.get("/specs/import/template", params={"owner_type": "component", "kind": "ssd"}).content))
    ws = wb.worksheets[0]
    categories = {ws.cell(r, 1).value for r in range(2, ws.max_row + 1)} - {None}
    assert categories <= {"저장장치", "기타"}
    assert ws.cell(2, 3).value != "상위 모델"



# ---------- 데스크톱 양식 (별도 파일) ----------

def test_desktop_template_follows_proposal_rows_and_saves_category(client, tmp_path):
    c, repo = client
    response = c.get("/specs/import/template", params={"owner_type": "product", "category": "desktop"})
    assert response.status_code == 200
    assert "spec_template_product_desktop.xlsx" in response.headers["content-disposition"]
    wb = openpyxl.load_workbook(filename=__import__("io").BytesIO(response.content))
    assert wb.sheetnames == ["데스크톱 사양", "작성 안내"]
    ws = wb.worksheets[0]
    assert [cell.value for cell in ws[1]][4:] == ["모델명1", "모델명2", "모델명3"]  # 노트북 제품(N5800)은 넣지 않는다
    sections = [ws.cell(r, 1).value for r in range(4, ws.max_row + 1) if ws.cell(r, 1).value]
    assert sections == ["CPU", "CPU Socket", "Chipset", "Memory", "Graphics", "HDD", "SSD", "ODD", "LAN", "Sound",
                        "PCI 확장", "파워", "전면 포트", "후면 포트", "케이스", "사이즈", "무게", "소비 전력량"]
    row_of = {ws.cell(r, 2).value: r for r in range(2, ws.max_row + 1)}

    # DT281 아래 Q670 보드 모델 둘. 칩셋은 병합(공통), 파워는 칸마다
    for col, model in enumerate(["DT281", "DT281 Q670", "DG481 Q670"], start=5):
        ws.cell(1, col, model)
    ws.cell(row_of["parent_model"], 6, "DT281")
    ws.cell(row_of["chipset"], 6, "Q670")
    ws.merge_cells(start_row=row_of["chipset"], start_column=6, end_row=row_of["chipset"], end_column=7)
    ws.cell(row_of["psu_w"], 6, "500W 80+ (700W 개별 상품화 가능)"), ws.cell(row_of["psu_w"], 7, "400W 80+")
    ws.cell(row_of["energy_kwh_year"], 6, "161.13 kWh/년 이하")
    ws.cell(row_of["front_ports"], 6, "USB 3.0 x 1ea, USB 2.0 x 2ea")

    preview = _upload(c, wb, tmp_path, "desktop.xlsx")
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert {col["category"] for col in body["columns"]} == {"desktop"}
    assert _apply_preview(c, body).status_code == 200

    by_model = {p["model"]: p for p in repo.list_products()}
    assert {by_model[m]["category"] for m in ("DT281", "DT281 Q670", "DG481 Q670")} == {"desktop"}
    assert by_model["N5800"]["category"] == "notebook"  # 다른 제품은 그대로
    dt = {s["attribute_key"]: s["value_num"] for s in repo.get_product(by_model["DT281 Q670"]["id"])["specs"]}
    assert dt["psu_w"] == 500.0 and dt["energy_kwh_year"] == 161.13
    assert repo.get_product(by_model["DT281 Q670"]["id"])["ancestors"][0]["model"] == "DT281"

    # 다시 받은 데스크톱 양식에는 데스크톱 제품만 트리 순서로 있다
    again = openpyxl.load_workbook(filename=__import__("io").BytesIO(
        c.get("/specs/import/template", params={"owner_type": "product", "category": "desktop"}).content)).worksheets[0]
    assert [cell.value for cell in again[1]][4:] == ["DG481 Q670", "DT281", "DT281 Q670"]


def test_notebook_template_upload_does_not_change_category(client, tmp_path):
    c, repo = client
    wb = openpyxl.load_workbook(filename=__import__("io").BytesIO(c.get("/specs/import/template").content))
    ws = wb.worksheets[0]
    row_of = {ws.cell(r, 2).value: r for r in range(2, ws.max_row + 1)}
    ws.cell(row_of["os"], 5, "Windows 11")
    body = _upload(c, wb, tmp_path).json()
    assert {col["category"] for col in body["columns"]} == {None}
    assert c.get("/specs/import/template", params={"category": "monitor"}).status_code == 400
