"""제품·부품 사양 API. 경로는 /specs (화면 경로 /spec 과 겹치지 않게 복수형).

- /specs/meta                 분류·종류·상태 코드와 표시 이름
- /specs/attributes           속성 사전 CRUD, /defaults 로 기본 속성 추가
- /specs/products             제품 CRUD, /{id}/components 로 부품 연결
- /specs/components           부품 CRUD
- /specs/values               사양 값 추가·수정·삭제 (제품·부품 공통)
"""
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from entity.spec import ATTRIBUTE_CATEGORIES, COMPONENT_KINDS, DATA_TYPES, PRODUCT_CATEGORIES, PRODUCT_STATUSES
from repository import spec_repo
from repository.spec_repository import SpecConflictError, SpecNotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/specs", tags=["specs"])


def _run(action, *args, **kwargs):
    """저장소 예외를 HTTP 상태로 바꾼다. ValueError 400, 없음 404, 충돌 409."""
    try:
        return action(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SpecNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SpecConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


# ---------- 메타 ----------

@router.get("/meta")
def get_meta() -> dict:
    """화면의 선택 목록. 코드와 표시 이름을 백엔드 한 곳(entity/spec.py)에서 관리한다."""
    return {
        "attribute_categories": ATTRIBUTE_CATEGORIES,
        "data_types": DATA_TYPES,
        "product_categories": PRODUCT_CATEGORIES,
        "product_statuses": PRODUCT_STATUSES,
        "component_kinds": COMPONENT_KINDS,
    }


# ---------- 속성 사전 ----------

class AttributeCreate(BaseModel):
    key: str
    name: str
    category: str = "other"
    data_type: str = "text"
    unit: str = ""
    description: str = ""
    sort_order: int = 0


class AttributeUpdate(BaseModel):
    name: str | None = None
    category: str | None = None
    data_type: str | None = None
    unit: str | None = None
    description: str | None = None
    sort_order: int | None = None


@router.get("/attributes")
def list_attributes() -> list[dict]:
    return spec_repo.list_attributes()


@router.post("/attributes", status_code=201)
def create_attribute(body: AttributeCreate) -> dict:
    attribute = _run(spec_repo.create_attribute, **body.model_dump())
    logger.info("사양 속성 추가: %s", attribute["key"])
    return attribute


@router.post("/attributes/defaults")
def add_default_attributes() -> dict:
    added = spec_repo.add_default_attributes()
    logger.info("기본 사양 속성 추가: %d개", added)
    return {"added": added}


@router.put("/attributes/{key}")
def update_attribute(key: str, body: AttributeUpdate) -> dict:
    return _run(spec_repo.update_attribute, key, **body.model_dump(exclude_unset=True))


@router.delete("/attributes/{key}", status_code=204)
def delete_attribute(key: str) -> None:
    _run(spec_repo.delete_attribute, key)
    logger.info("사양 속성 삭제: %s", key)


# ---------- 제품 ----------

class ProductCreate(BaseModel):
    model: str
    name: str = ""
    category: str = "notebook"
    status: str = "active"
    note: str = ""


class ProductUpdate(BaseModel):
    model: str | None = None
    name: str | None = None
    category: str | None = None
    status: str | None = None
    note: str | None = None


class ComponentLink(BaseModel):
    component_id: str
    is_option: bool = False
    note: str = ""


@router.get("/products")
def list_products() -> list[dict]:
    return spec_repo.list_products()


@router.post("/products", status_code=201)
def create_product(body: ProductCreate) -> dict:
    product = _run(spec_repo.create_product, **body.model_dump())
    logger.info("제품 등록: %s (%s)", product["model"], product["id"])
    return product


@router.get("/products/{product_id}")
def get_product(product_id: str) -> dict:
    product = spec_repo.get_product(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="제품을 찾을 수 없습니다.")
    return product


@router.put("/products/{product_id}")
def update_product(product_id: str, body: ProductUpdate) -> dict:
    return _run(spec_repo.update_product, product_id, **body.model_dump(exclude_unset=True))


@router.delete("/products/{product_id}", status_code=204)
def delete_product(product_id: str) -> None:
    _run(spec_repo.delete_product, product_id)
    logger.info("제품 삭제: %s", product_id)


@router.put("/products/{product_id}/components")
def link_component(product_id: str, body: ComponentLink) -> dict:
    """제품에 부품을 넣거나 옵션 여부를 바꾼다. 바뀐 제품 상세를 돌려준다."""
    return _run(spec_repo.link_component, product_id, body.component_id, body.is_option, body.note)


@router.delete("/products/{product_id}/components/{component_id}")
def unlink_component(product_id: str, component_id: str) -> dict:
    return _run(spec_repo.unlink_component, product_id, component_id)


# ---------- 부품 ----------

class ComponentCreate(BaseModel):
    kind: str = "other"
    model: str
    vendor: str = ""
    note: str = ""


class ComponentUpdate(BaseModel):
    kind: str | None = None
    model: str | None = None
    vendor: str | None = None
    note: str | None = None


@router.get("/components")
def list_components(kind: str | None = None) -> list[dict]:
    return spec_repo.list_components(kind)


@router.post("/components", status_code=201)
def create_component(body: ComponentCreate) -> dict:
    component = _run(spec_repo.create_component, **body.model_dump())
    logger.info("부품 등록: %s %s (%s)", component["kind"], component["model"], component["id"])
    return component


@router.get("/components/{component_id}")
def get_component(component_id: str) -> dict:
    component = spec_repo.get_component(component_id)
    if component is None:
        raise HTTPException(status_code=404, detail="부품을 찾을 수 없습니다.")
    return component


@router.put("/components/{component_id}")
def update_component(component_id: str, body: ComponentUpdate) -> dict:
    return _run(spec_repo.update_component, component_id, **body.model_dump(exclude_unset=True))


@router.delete("/components/{component_id}", status_code=204)
def delete_component(component_id: str) -> None:
    _run(spec_repo.delete_component, component_id)
    logger.info("부품 삭제: %s", component_id)


# ---------- 사양 값 ----------

class SpecValueCreate(BaseModel):
    owner_type: str  # product | component
    owner_id: str
    attribute_key: str
    value_text: str
    is_option: bool = False
    note: str = ""
    source_file_id: str | None = None
    source_page: int | None = Field(default=None, ge=1)
    source_note: str = ""


class SpecValueUpdate(BaseModel):
    attribute_key: str | None = None
    value_text: str | None = None
    is_option: bool | None = None
    note: str | None = None
    source_file_id: str | None = None
    source_page: int | None = Field(default=None, ge=1)
    source_note: str | None = None


@router.post("/values", status_code=201)
def add_spec_value(body: SpecValueCreate) -> dict:
    return _run(spec_repo.add_spec, **body.model_dump())


@router.put("/values/{spec_id}")
def update_spec_value(spec_id: int, body: SpecValueUpdate) -> dict:
    return _run(spec_repo.update_spec, spec_id, **body.model_dump(exclude_unset=True))


@router.delete("/values/{spec_id}", status_code=204)
def delete_spec_value(spec_id: int) -> None:
    _run(spec_repo.delete_spec, spec_id)
