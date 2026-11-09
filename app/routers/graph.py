"""문서 그래프(Graph RAG) 조회·편집·재추출 API. 그래프 화면(frontend/src/knowledge)이 쓴다."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel

from graph_rag.service import index_all, index_file, search_graph
from graph_rag.types import ENTITY_TYPES, RELATION_TYPES
from repository import file_repo, graph_repo, page_repo
from repository.graph_repository import GraphEditError, GraphNotFoundError

router = APIRouter(prefix="/graph", tags=["graph"])


def _run(fn, *args, **kwargs):
    """저장소 예외를 HTTP 오류로 바꾼다."""
    try:
        return fn(*args, **kwargs)
    except GraphNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GraphEditError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------- 조회 ----------

@router.get("/schema")
def graph_schema() -> dict:
    """개체·관계 종류와 설명. 화면의 범례와 선택 목록에 쓴다."""
    return {
        "entity_types": [{"key": k, "description": v} for k, v in ENTITY_TYPES.items()],
        "relation_types": [{"key": k, "description": v} for k, v in RELATION_TYPES.items()],
    }


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
) -> dict:
    """그래프 화면용 노드·엣지."""
    type_list = [t for t in (types or "").split(",") if t]
    unknown = [t for t in type_list if t not in ENTITY_TYPES]
    if unknown:
        raise HTTPException(status_code=400, detail=f"없는 개체 종류입니다: {', '.join(unknown)}")
    return _run(graph_repo.view, entity_id=entity_id, depth=depth, types=type_list, file_id=file_id, limit=limit)


@router.get("/entities")
def list_entities(
    type: str | None = Query(None, description="개체 종류 (product, certification ...)"),
    q: str | None = Query(None, description="이름·별칭 일부"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[dict]:
    if type is not None and type not in ENTITY_TYPES:
        raise HTTPException(status_code=400, detail=f"없는 개체 종류입니다: {type} (가능: {', '.join(ENTITY_TYPES)})")
    return graph_repo.list_entities(type, q, limit, offset)


@router.get("/entities/{entity_id}")
def get_entity(entity_id: int) -> dict:
    """개체 하나의 별칭, 관계(출처 포함), 나온 문서 페이지."""
    entity = graph_repo.get_entity(entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="개체를 찾을 수 없습니다.")
    return entity


@router.get("/search")
def graph_search(q: str = Query(..., min_length=1), group_id: str | None = None) -> dict:
    """에이전트의 graph_search 도구와 같은 결과. 검색이 어떻게 펼쳐지는지 확인할 때 쓴다."""
    return search_graph(q, group_id=group_id)


# ---------- 편집 ----------

class NewEntityBody(BaseModel):
    type: str
    name: str


class RelationCreateBody(BaseModel):
    source_id: int
    type: str
    target_id: int | None = None       # 기존 개체로 잇기
    new_target: NewEntityBody | None = None  # 새 개체를 만들어 잇기 (같은 이름이 있으면 그 개체)
    file_id: str | None = None         # 근거 문서 (선택)
    page: int | None = None


class RelationUpdateBody(BaseModel):
    type: str | None = None
    reverse: bool = False              # 방향 뒤집기


class EntityUpdateBody(BaseModel):
    name: str


class EntityMergeBody(BaseModel):
    target_id: int                     # 이 개체로 합친다 (요청 경로의 개체는 지워진다)


@router.post("/relations", status_code=201)
def create_relation(body: RelationCreateBody) -> dict:
    """사람이 관계를 넣는다. 문서를 다시 뽑아도 유지된다."""
    new_target = (body.new_target.type, body.new_target.name) if body.new_target else None
    return _run(
        graph_repo.add_relation, body.source_id, body.type,
        target_id=body.target_id, new_target=new_target, file_id=body.file_id, page=body.page,
    )


@router.patch("/relations/{relation_id}")
def update_relation(relation_id: int, body: RelationUpdateBody) -> dict:
    """관계 종류를 바꾸거나 방향을 뒤집는다. 원래 관계는 다시 뽑아도 되살아나지 않는다."""
    return _run(graph_repo.update_relation, relation_id, rel_type=body.type, reverse=body.reverse)


@router.delete("/relations/{relation_id}")
def delete_relation(relation_id: int) -> dict:
    """관계를 지운다. 같은 두 개체 사이의 같은 종류 관계는 모두 지우고, 다시 뽑아도 되살아나지 않게 한다."""
    return {"deleted": _run(graph_repo.delete_relation, relation_id)}


@router.patch("/entities/{entity_id}")
def rename_entity(entity_id: int, body: EntityUpdateBody) -> dict:
    """개체 이름을 바꾼다. 옛 이름은 별칭으로 남는다."""
    return _run(graph_repo.rename_entity, entity_id, body.name)


@router.post("/entities/{entity_id}/merge")
def merge_entity(entity_id: int, body: EntityMergeBody) -> dict:
    """이 개체를 target_id 개체에 합친다. 합친 결과 개체를 돌려준다."""
    return _run(graph_repo.merge_entities, entity_id, body.target_id)


# ---------- 재추출 ----------

@router.post("/rebuild", status_code=202)
def rebuild_graph(background: BackgroundTasks, file_id: str | None = None) -> dict:
    """저장된 페이지 텍스트로 그래프를 다시 만든다. file_id가 없으면 모든 파일. 페이지마다 LLM을 불러 백그라운드로 돈다.

    사람이 넣은 관계와 지운(차단한) 관계는 유지된다.
    """
    if file_id is None:
        background.add_task(index_all)
        return {"scheduled": "all"}
    if file_repo.get_file_by_id(file_id) is None:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    if not page_repo.has_pages(file_id):
        raise HTTPException(status_code=409, detail="페이지 텍스트가 없는 파일입니다. 먼저 POST /file/{file_id}/pages/import를 실행하세요.")
    background.add_task(index_file, file_id)
    return {"scheduled": file_id}
