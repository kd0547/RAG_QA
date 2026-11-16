"""제품·부품 사양 API. 경로는 /specs (화면 경로 /spec 과 겹치지 않게 복수형).

- /specs/meta                 분류·종류·상태 코드와 표시 이름
- /specs/attributes           속성 사전 CRUD, /defaults 로 기본 속성 추가
- /specs/products             제품 CRUD (parent_id로 하위 모델), /{id}/components 로 부품 연결
- /specs/components           부품 CRUD
- /specs/values               사양 값 추가·수정·삭제 (제품·부품 공통)
"""
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import config
import repository
from entity.spec import (
    ATTRIBUTE_CATEGORIES, COMPONENT_KINDS, DATA_TYPES, GRAPH_MODES, PRODUCT_CATEGORIES, PRODUCT_STATUSES,
)
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


def reseed_spec_graph(reason: str) -> None:
    """사양이 바뀌면 사양 DB를 그래프로 다시 투영한다 (지시서 GR4-6). 사양 저장 API 전부가 부른다.

    실패해도 사양 저장은 이미 끝났으므로 요청은 성공으로 둔다 (서버를 다시 시작하면 다시 투영한다).
    """
    if not config.GRAPH_SPEC_SEED_ENABLED:
        return
    try:
        logger.info("사양 변경(%s) 뒤 그래프 다시 투영: %s", reason, repository.graph_repo.project_specs())
    except Exception:
        logger.exception("사양 변경(%s) 뒤 그래프 다시 투영 실패", reason)


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
        "graph_modes": GRAPH_MODES,
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
    # 파생 모델이 상위 모델 값을 물려받아도 되는지. 인증(cert) 분류는 켤 수 없다 (400)
    inheritable: bool | None = None
    # 그래프 방식 (지시서 GR4-5): value_node | entity | none. entity면 관계 종류·도착 노드 종류
    graph_mode: str | None = None
    graph_relation_type: str | None = None
    graph_entity_type: str | None = None


@router.get("/attributes")
def list_attributes() -> list[dict]:
    return spec_repo.list_attributes()


@router.post("/attributes", status_code=201)
def create_attribute(body: AttributeCreate) -> dict:
    attribute = _run(spec_repo.create_attribute, **body.model_dump())
    logger.info("사양 속성 추가: %s", attribute["key"])
    reseed_spec_graph("속성 추가")
    return attribute


@router.post("/attributes/defaults")
def add_default_attributes() -> dict:
    added = spec_repo.add_default_attributes()
    logger.info("기본 사양 속성 추가: %d개", added)
    reseed_spec_graph("기본 속성 추가")
    return {"added": added}


@router.put("/attributes/{key}")
def update_attribute(key: str, body: AttributeUpdate) -> dict:
    attribute = _run(spec_repo.update_attribute, key, **body.model_dump(exclude_unset=True))
    reseed_spec_graph("속성 수정")
    return attribute


@router.delete("/attributes/{key}", status_code=204)
def delete_attribute(key: str) -> None:
    _run(spec_repo.delete_attribute, key)
    logger.info("사양 속성 삭제: %s", key)
    reseed_spec_graph("속성 삭제")


# ---------- 제품 ----------

class ProductCreate(BaseModel):
    model: str
    name: str = ""
    category: str = "notebook"
    status: str = "active"
    note: str = ""
    parent_id: str | None = None  # 상위 모델 id. 있으면 하위(파생) 모델로 등록한다


class ProductUpdate(BaseModel):
    model: str | None = None
    name: str | None = None
    category: str | None = None
    status: str | None = None
    note: str | None = None
    parent_id: str | None = None  # 넘기면 반영한다. null이면 최상위 모델로 올린다


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
    reseed_spec_graph("제품 등록")
    return product


@router.get("/products/{product_id}")
def get_product(product_id: str) -> dict:
    product = spec_repo.get_product(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="제품을 찾을 수 없습니다.")
    return product


@router.put("/products/{product_id}")
def update_product(product_id: str, body: ProductUpdate) -> dict:
    product = _run(spec_repo.update_product, product_id, **body.model_dump(exclude_unset=True))
    reseed_spec_graph("제품 수정")
    return product


@router.delete("/products/{product_id}", status_code=204)
def delete_product(product_id: str) -> None:
    _run(spec_repo.delete_product, product_id)
    logger.info("제품 삭제: %s", product_id)
    reseed_spec_graph("제품 삭제")


@router.put("/products/{product_id}/components")
def link_component(product_id: str, body: ComponentLink) -> dict:
    """제품에 부품을 넣거나 옵션 여부를 바꾼다. 바뀐 제품 상세를 돌려준다."""
    product = _run(spec_repo.link_component, product_id, body.component_id, body.is_option, body.note)
    reseed_spec_graph("부품 연결")
    return product


@router.delete("/products/{product_id}/components/{component_id}")
def unlink_component(product_id: str, component_id: str) -> dict:
    product = _run(spec_repo.unlink_component, product_id, component_id)
    reseed_spec_graph("부품 연결 해제")
    return product


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
    reseed_spec_graph("부품 등록")
    return component


@router.get("/components/{component_id}")
def get_component(component_id: str) -> dict:
    component = spec_repo.get_component(component_id)
    if component is None:
        raise HTTPException(status_code=404, detail="부품을 찾을 수 없습니다.")
    return component


@router.put("/components/{component_id}")
def update_component(component_id: str, body: ComponentUpdate) -> dict:
    component = _run(spec_repo.update_component, component_id, **body.model_dump(exclude_unset=True))
    reseed_spec_graph("부품 수정")  # 부품은 연결과 관계없이 모두 노드다 (GR4-1)
    return component


@router.delete("/components/{component_id}", status_code=204)
def delete_component(component_id: str) -> None:
    _run(spec_repo.delete_component, component_id)
    logger.info("부품 삭제: %s", component_id)
    reseed_spec_graph("부품 삭제")


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
    value = _run(spec_repo.add_spec, **body.model_dump())
    reseed_spec_graph("사양 값 추가")
    return value


@router.put("/values/{spec_id}")
def update_spec_value(spec_id: int, body: SpecValueUpdate) -> dict:
    value = _run(spec_repo.update_spec, spec_id, **body.model_dump(exclude_unset=True))
    reseed_spec_graph("사양 값 수정")
    return value


@router.delete("/values/{spec_id}", status_code=204)
def delete_spec_value(spec_id: int) -> None:
    _run(spec_repo.delete_spec, spec_id)
    reseed_spec_graph("사양 값 삭제")
