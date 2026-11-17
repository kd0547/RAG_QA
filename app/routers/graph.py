"""문서 그래프(Graph RAG) 조회·편집·재추출 API. 그래프 화면(frontend/src/knowledge)이 쓴다."""
from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Body, HTTPException, Query, Request
from urllib.parse import unquote

from graph_rag.service import index_all, index_file, search_graph
from repository import file_repo, graph_repo, page_repo
from repository.graph_repository import GraphEditError, GraphNotFoundError
from graph_rag.edit_service import EffectiveGraphService, GraphEditService, GraphConflictError, GraphValueConversionError
import config

router = APIRouter(prefix="/graph", tags=["graph"])
logger = logging.getLogger(__name__)


def _run(fn, *args, **kwargs):
    """저장소 예외를 HTTP 오류로 바꾼다."""
    try:
        return fn(*args, **kwargs)
    except GraphNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GraphConflictError as exc:
        raise HTTPException(status_code=409, detail={"code":"revision_conflict", "message":str(exc)}) from exc
    except GraphValueConversionError as exc:
        raise HTTPException(status_code=400, detail={"code":"value_conversion", "message":str(exc), "values":exc.values}) from exc
    except GraphEditError as exc:
        raise HTTPException(status_code=400, detail={"code":"invalid_graph_input", "message":str(exc)}) from exc


# ---------- 조회 ----------

@router.get("/schema")
def graph_schema() -> dict:
    """개체·관계 종류와 설명. 화면의 범례와 선택 목록에 쓴다."""
    return EffectiveGraphService(graph_repo.db).schema()


@router.get("/stats")
def graph_stats() -> dict:
    """종류별 개체 수, 출처별 관계 수, 차단한 관계 수, 그래프가 만들어진 파일 수."""
    return graph_repo.stats()


@router.get("/view")
def graph_view(
    entity_id: int | None = Query(None, description="이 개체를 중심으로 본다"),
    depth: int = Query(1, ge=1, le=3, description="중심 개체에서 몇 단계까지"),
    types: str | None = Query(None, description="쉼표로 구분한 개체 종류"),
    file_id: str | None = Query(None, description="이 문서에 나온 개체만"),
    limit: int = Query(150, ge=1, le=500),
    spec_values: str = Query("neighbors", pattern="^(neighbors|all)$", description="사양 값 노드: 고른 노드의 이웃만 / 모두"),
    hide_isolated_spec: bool = Query(True, description="관계 없는 사양 노드 숨기기"),
) -> dict:
    """그래프 화면용 노드·엣지."""
    type_list = [t for t in (types or "").split(",") if t]
    unknown = [t for t in type_list if t not in graph_repo.entity_type_keys()]
    if unknown:
        raise HTTPException(status_code=400, detail=f"없는 개체 종류입니다: {', '.join(unknown)}")
    return _run(graph_repo.view, entity_id=entity_id, depth=depth, types=type_list, file_id=file_id, limit=limit,
                spec_values=spec_values, hide_isolated_spec=hide_isolated_spec)


@router.get("/entities")
def list_entities(
    type: str | None = Query(None, description="개체 종류 (product, certification ...)"),
    q: str | None = Query(None, description="이름·별칭 일부"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[dict]:
    keys = graph_repo.entity_type_keys()
    if type is not None and type not in keys:
        raise HTTPException(status_code=400, detail=f"없는 개체 종류입니다: {type} (가능: {', '.join(keys)})")
    return graph_repo.list_entities(type, q, limit, offset)


@router.get("/entities/{entity_id}")
def get_entity(entity_id: int) -> dict:
    """개체 하나의 별칭, 관계(출처 포함), 나온 문서 페이지."""
    entity = graph_repo.get_entity(entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="개체를 찾을 수 없습니다.")
    entity["spec"] = _spec_of(entity)
    return entity


def _spec_of(entity: dict) -> dict | None:
    """사양 DB 제품·부품 노드의 그때 사양 값 (GR4-7, agent.spec_service.effective_specs). 읽지 못하면 None."""
    if entity.get("ref_type") not in ("product", "component") or not entity.get("ref_id"):
        return None
    try:
        from agent.spec_service import effective_specs
        return effective_specs(entity["ref_type"], entity["ref_id"])
    except Exception:
        logger.warning("그래프 개체의 사양 값을 읽지 못함: %s", entity.get("id"), exc_info=True)
        return None


@router.get("/search")
def graph_search(q: str = Query(..., min_length=1), group_id: str | None = None) -> dict:
    """에이전트의 graph_search 도구와 같은 결과. 검색이 어떻게 펼쳐지는지 확인할 때 쓴다."""
    return search_graph(q, group_id=group_id)


# ---------- 편집 ----------

def _edit(request: Request, command: str, identity=None, data=None):
    if not config.GRAPH_EDIT_ENABLED:
        raise HTTPException(status_code=403, detail="그래프 편집 기능이 비활성화되어 있습니다.")
    return _run(GraphEditService(graph_repo.db).execute, command, identity, data,
                actor=unquote(request.headers.get("X-Graph-Actor", "")),
                session=request.headers.get("X-Graph-Session", ""),
                request_key=request.headers.get("Idempotency-Key"))


@router.post("/entities", status_code=201)
def create_entity(request: Request, body: dict = Body(...)):
    return _edit(request, "create_entity", data=body)


@router.patch("/entities/{entity_id}")
def update_entity(entity_id: int, request: Request, body: dict = Body(...)):
    """이름·별칭·종류(type)를 바꾼다. 종류를 바꾸면 type_locked=1 (사양 투영이 되돌리지 않는다). 규칙과 다르면 warnings."""
    result = _edit(request, "update_entity", entity_id, body)
    entity = get_entity(entity_id)
    entity["warnings"] = result.get("warnings", [])
    return entity


@router.post("/entities/{entity_id}/reset-spec")
def reset_spec_entity(entity_id: int, request: Request, body: dict = Body(...)):
    """사양 DB 기준으로 되돌리기: 이 사양 노드에 대한 사람의 편집을 지우고 다시 투영한다. 사양 DB는 바뀌지 않는다."""
    result = _edit(request, "reset_spec_entity", entity_id, body)
    if config.GRAPH_SPEC_SEED_ENABLED:
        graph_repo.project_specs()
    entity = get_entity(entity_id)
    entity["reset"] = {k: result.get(k) for k in ("cleared_exclusions", "removed_replacements")}
    return entity


@router.get("/rule-warnings")
def rule_warnings():
    """허용 종류를 어기는 관계, 식별자 규칙을 어기는 개체 (출처별). 사람이 의도한 것이면 그대로 둔다."""
    return EffectiveGraphService(graph_repo.db).rule_warnings()


@router.get("/entities/{entity_id}/delete-impact")
def delete_impact(entity_id: int):
    return _run(EffectiveGraphService(graph_repo.db).impact, entity_id)


@router.delete("/entities/{entity_id}")
def delete_entity(entity_id: int, request: Request, expected_revision: int | None = None):
    return _edit(request, "delete_entity", entity_id, {"expected_revision":expected_revision})


@router.post("/entities/{entity_id}/restore")
def restore_entity(entity_id: int, request: Request, body: dict = Body(...)):
    return _edit(request, "restore_entity", entity_id, body)


@router.post("/entities/{entity_id}/merge")
def merge_entity(entity_id: int, request: Request, body: dict = Body(...)):
    result = _edit(request, "merge_entity", entity_id, body)
    return graph_repo.get_entity(result["id"])


@router.get("/entity-types")
def entity_types():
    return graph_schema()["entity_types"]


@router.post("/entity-types", status_code=201)
def create_entity_type(request: Request, body: dict = Body(...)):
    return _edit(request, "create_entity_type", data=body)


@router.patch("/entity-types/{key}")
def update_entity_type(key: str, request: Request, body: dict = Body(...)):
    return _edit(request, "update_entity_type", key, body)


@router.post("/entity-types/{key}/merge")
def merge_entity_type(key: str, request: Request, body: dict = Body(...)):
    """이 종류의 개체를 모두 다른 종류(body.into)로 옮기고 종류를 지운다."""
    return _edit(request, "merge_entity_type", key, body)


@router.delete("/entity-types/{key}")
def delete_entity_type(key: str, request: Request, expected_revision: int | None = None):
    """개체가 0개면 지운다. 있으면 400과 합치기 안내."""
    return _edit(request, "delete_entity_type", key, {"expected_revision": expected_revision})


@router.get("/relation-types")
def relation_types():
    return graph_schema()["relation_types"]


@router.post("/relation-types", status_code=201)
def create_relation_type(request: Request, body: dict = Body(...)):
    return _edit(request, "create_relation_type", data=body)


@router.patch("/relation-types/{key}")
def update_relation_type(key: str, request: Request, body: dict = Body(...)):
    return _edit(request, "update_relation_type", key, body)


@router.get("/property-definitions")
def property_definitions():
    return graph_schema()["property_definitions"]


@router.post("/property-definitions", status_code=201)
def create_property_definition(request: Request, body: dict = Body(...)):
    return _edit(request, "create_property_definition", data=body)


@router.patch("/property-definitions/{property_id}")
def update_property_definition(property_id: int, request: Request, body: dict = Body(...)):
    return _edit(request, "update_property_definition", property_id, body)


@router.get("/entities/{entity_id}/properties")
def properties(entity_id: int):
    get_entity(entity_id)
    return EffectiveGraphService(graph_repo.db).properties(entity_id)


@router.post("/entities/{entity_id}/properties", status_code=201)
def create_property(entity_id: int, request: Request, body: dict = Body(...)):
    return _edit(request, "create_property", entity_id, body)


@router.patch("/entities/{entity_id}/properties/{value_id}")
def update_property(entity_id: int, value_id: int, request: Request, body: dict = Body(...)):
    return _edit(request, "update_property", value_id, {**body,"entity_id":entity_id})


@router.delete("/entities/{entity_id}/properties/{value_id}")
def delete_property(entity_id: int, value_id: int, request: Request, expected_revision: int | None = None):
    return _edit(request, "delete_property", value_id, {"entity_id":entity_id,"expected_revision":expected_revision})


@router.post("/relations", status_code=201)
def create_relation(request: Request, body: dict = Body(...)):
    return _edit(request, "create_relation", data=body)


@router.patch("/relations/{relation_id}")
def update_relation(relation_id: int, request: Request, body: dict = Body(...)):
    return _edit(request, "update_relation", relation_id, body)


@router.delete("/relations/{relation_id}")
def delete_relation(relation_id: int, request: Request, expected_revision: int | None = None, scope: str = "all"):
    return _edit(request, "delete_relation", relation_id, {"expected_revision":expected_revision,"scope":scope})


@router.post("/relations/{relation_id}/restore")
def restore_relation(relation_id: int, request: Request, body: dict = Body(...)):
    return _edit(request, "restore_relation", relation_id, body)


@router.get("/changes")
def changes(kind: str | None = None, target_id: str | None = None,
            limit: int = Query(100,ge=1,le=500), offset: int = Query(0,ge=0)):
    return EffectiveGraphService(graph_repo.db).changes(kind,target_id,limit,offset)


@router.get("/deleted")
def deleted(limit: int = Query(100,ge=1,le=500), offset: int = Query(0,ge=0)):
    return EffectiveGraphService(graph_repo.db).deleted(limit,offset)


@router.get("/entities/{entity_id}/facts")
def facts(entity_id: int):
    return _run(EffectiveGraphService(graph_repo.db).facts, entity_id)

# ---------- 재추출 ----------

@router.post("/rebuild", status_code=202)
def rebuild_graph(background: BackgroundTasks, file_id: str | None = None) -> dict:
    """저장된 페이지 텍스트로 그래프를 다시 만든다. file_id가 없으면 모든 파일. 페이지마다 LLM을 불러 백그라운드로 돈다.

    사람이 넣은 관계와 지운(차단한) 관계는 유지된다.
    """
    if file_id is None:
        background.add_task(index_all)
        return {"scheduled": "all"}
    file = file_repo.get_file_by_id(file_id)
    if file is None:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    if file.review_status != "done":
        raise HTTPException(status_code=409, detail="검수 대기 파일입니다. 파일 검수에서 [검수 완료]를 누르면 그래프를 뽑습니다.")
    if not page_repo.has_pages(file_id):
        raise HTTPException(status_code=409, detail="페이지 텍스트가 없는 파일입니다. 먼저 POST /file/{file_id}/pages/import를 실행하세요.")
    background.add_task(index_file, file_id)
    return {"scheduled": file_id}
