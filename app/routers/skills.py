"""업무 절차 API (지시서 I5). 화면은 /skill, API는 /skills.

- 사용 중 절차(저장소 + DB 승인본) 조회, 생성 초안 검토(수정·승인·반려), 승인본 고치기(새 버전)·사용 중지
- 문의 유형 관리(초안 요청, 절차 불필요 표시, 합치기)와 분석된 문의 목록
- 저장소 절차(skills/)의 본문은 화면에서 고치지 않는다 (파일을 고치면 다음 실행부터 반영). 고치기·retire 요청은 400.
  대신 끄기·다시 켜기(/skills/{name}/disable, /enable)로 답변·초안 생성에서 뺄 수 있다. 파일은 그대로 둔다.
- 승인·반려·사용 중지는 상태 조건부 UPDATE라 두 번 눌러도 한 번만 처리된다.
- 로그인 기능이 없어 승인자는 요청 IP(reviewed_by)로만 남는다.
- 응답에 메일 본문 전체를 넣지 않는다. 사례는 제목과 검토 화면 링크용 task_id만.

고정 경로(/skills/drafts, /skills/types, /skills/analysis)를 /skills/{name}보다 먼저 선언한다.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import config
from agent import skill_author, skills
from repository import skill_repo
from repository.skill_repository import UNAPPROVED_STATUSES

router = APIRouter()

USAGE_DAYS = 30
OPEN_DRAFT_STATUSES = ("generating", "draft", "error")


def _client_ip(request: Request) -> str | None:
    """감사용 요청자 IP. 로그인 기능이 없어 승인자를 구분할 수 있는 값은 이것뿐이다."""
    return request.client.host if request.client else None


def _display_name(doc: dict) -> str | None:
    """생성 중·실패 행의 임시 이름은 화면에 보이지 않는다."""
    return None if skill_author.is_placeholder_name(doc.get("name")) else doc.get("name")


def _check_summary(check: dict | None) -> dict | None:
    if check is None:
        return None
    return {"ok": bool(check.get("ok")), "errors": len(check.get("errors") or []), "warnings": len(check.get("warnings") or [])}


def _type_ref(type_id: int | None) -> dict | None:
    if type_id is None:
        return None
    found = skill_repo.get_type(type_id)
    return {"type_id": type_id, "label": found["label"] if found else None, "state": found["state"] if found else None}


def _draft_item(doc: dict) -> dict:
    return {
        "doc_id": doc["doc_id"], "name": _display_name(doc), "version": doc["version"] or None, "status": doc["status"],
        "origin": doc["origin"], "type": _type_ref(doc.get("type_id")), "created_at": doc["created_at"],
        "check": _check_summary(doc.get("check")), "error": doc.get("error"), "description": doc.get("description"),
    }


def _history_item(doc: dict) -> dict:
    return {
        "doc_id": doc["doc_id"], "version": doc["version"], "status": doc["status"], "origin": doc["origin"],
        "digest": doc.get("digest"), "created_at": doc["created_at"], "reviewed_at": doc.get("reviewed_at"),
        "reviewed_by": doc.get("reviewed_by"), "review_note": doc.get("review_note"),
    }


def _doc_or_404(doc_id: int) -> dict:
    doc = skill_repo.get_doc(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="SKILL 초안을 찾을 수 없습니다.")
    return doc


def _draft_detail(doc: dict) -> dict:
    base = skill_repo.latest_approved(doc["name"]) if _display_name(doc) else None
    return {
        **_draft_item(doc),
        "body": doc.get("body"),
        "check": doc.get("check"),
        "cases": skill_repo.case_summaries(doc.get("source_tasks") or []),
        "base_version": base["version"] if base and base["doc_id"] != doc["doc_id"] else None,
        "reviewed_at": doc.get("reviewed_at"), "reviewed_by": doc.get("reviewed_by"), "review_note": doc.get("review_note"),
        "model": doc.get("model"),
    }


def _repo_or_400(name: str, action: str) -> None:
    if name in skills.repo_skills() or name == skills.AUTHOR_SKILL:
        raise HTTPException(status_code=400, detail=f"저장소 SKILL(skills/{name})은 화면에서 {action}할 수 없습니다. 본문은 파일에서 고치고, 멈추려면 끄기를 씁니다.")


# ---------------------------------------------------------------- 사용 중 절차

@router.get("/skills")
def list_skills() -> dict:
    """저장소 절차(꺼진 것·작성 절차 포함) + 사용 중인 DB 절차. 화면은 enabled·author로 묶어 보인다."""
    since = (datetime.now() - timedelta(days=USAGE_DAYS)).isoformat()
    usage = skill_repo.skill_usage_since(since)
    active_docs = {d["name"]: d for d in skill_repo.active_skill_docs()}
    disabled = skill_repo.disabled_skills()
    items = []
    for skill in [*skills.repo_skills().values(), *skills.db_skills().values()]:
        doc = active_docs.get(skill.name) if skill.origin == "db" else None
        off = disabled.get(skill.name) if skill.origin == "repo" else None
        items.append({
            "name": skill.name, "description": skill.description, "channels": list(skill.channels),
            "origin": skill.origin, "version": skill.version, "digest": skill.digest,
            "server_applied": skill.name in skills.SERVER_CHOSEN and skill.origin == "repo",
            "author": skills.AUTHOR_CHANNEL in skill.channels,
            "enabled": off is None, "disabled_at": off["disabled_at"] if off else None,
            "files": list(skill.files),
            "uses_30d": usage.get(skill.name, 0),
            "doc_id": doc["doc_id"] if doc else None, "type": _type_ref(doc.get("type_id")) if doc else None,
            "approved_at": doc.get("reviewed_at") if doc else None,
        })
    items.sort(key=lambda i: (i["author"], not i["enabled"], i["origin"] != "repo", not i["server_applied"], i["name"]))
    return {
        "items": items,
        "load_errors": [{"folder": folder, "reason": reason} for folder, reason in sorted(skills.repo_errors().items())],
        "loaded_at": skills.loaded_at(),
        "author": skills.author_skill_status(),
        "settings": {
            "analysis_enabled": config.REQUEST_ANALYSIS_ENABLED, "auto_draft": config.SKILL_DRAFT_AUTO,
            "min_cases": config.SKILL_DRAFT_MIN_CASES, "usage_days": USAGE_DAYS,
        },
    }


# ---------------------------------------------------------------- 초안

class DraftEdit(BaseModel):
    description: str
    body: str


class ApproveBody(BaseModel):
    note: str | None = None


class RejectBody(BaseModel):
    reason: str


@router.get("/skills/drafts")
def list_drafts(status: str | None = None) -> dict:
    statuses = tuple(s.strip() for s in (status or ",".join(UNAPPROVED_STATUSES)).split(",") if s.strip())
    unknown = [s for s in statuses if s not in UNAPPROVED_STATUSES]
    if unknown or not statuses:
        raise HTTPException(status_code=400, detail=f"status는 {', '.join(UNAPPROVED_STATUSES)} 중에서 고릅니다.")
    return {"items": [_draft_item(d) for d in skill_repo.list_docs(statuses)], "author": skills.author_skill_status()}


@router.get("/skills/drafts/{doc_id}")
def get_draft(doc_id: int) -> dict:
    return _draft_detail(_doc_or_404(doc_id))


@router.put("/skills/drafts/{doc_id}")
def edit_draft(doc_id: int, edit: DraftEdit) -> dict:
    doc = _doc_or_404(doc_id)
    if doc["status"] != "draft":
        raise HTTPException(status_code=409, detail="검토 대기(draft) 초안만 고칠 수 있습니다.")
    description = edit.description.strip()
    body = skills.normalize_body(edit.body)
    check = skill_author.recheck_doc(doc, description, body)
    if not skill_repo.update_draft(doc_id, description, body, skills.body_digest(body), check):
        raise HTTPException(status_code=409, detail="그 사이 초안 상태가 바뀌었습니다. 새로 고쳐 보세요.")
    return _draft_detail(skill_repo.get_doc(doc_id))


@router.post("/skills/drafts/{doc_id}/approve")
def approve_draft(doc_id: int, request: Request, payload: ApproveBody | None = None) -> dict:
    doc = _doc_or_404(doc_id)
    if doc["status"] != "draft":
        raise HTTPException(status_code=409, detail="이미 처리된 초안입니다.")
    # 승인 시점의 상태(저장소 절차, 다른 유형의 이름)로 다시 검사한다
    check = skill_author.recheck_doc(doc, doc.get("description") or "", doc.get("body") or "")
    outcome = skill_repo.approve_doc(doc_id, _client_ip(request), payload.note if payload else None, check)
    if outcome == "has_errors":
        skill_repo.set_check(doc_id, check)
        raise HTTPException(status_code=400, detail="검사 오류가 있어 승인할 수 없습니다: " + " / ".join(check["errors"]))
    if outcome == "not_draft":
        raise HTTPException(status_code=409, detail="이미 처리된 초안입니다.")
    if outcome == "stale":
        raise HTTPException(status_code=409, detail="같은 이름의 더 새 버전이 이미 승인되었거나 사용 중지되었습니다.")
    if outcome == "not_found":
        raise HTTPException(status_code=404, detail="SKILL 초안을 찾을 수 없습니다.")
    return _draft_detail(skill_repo.get_doc(doc_id))


@router.post("/skills/drafts/{doc_id}/reject")
def reject_draft(doc_id: int, payload: RejectBody, request: Request) -> dict:
    reason = payload.reason.strip()
    if not reason:
        raise HTTPException(status_code=400, detail="반려 사유를 적어 주세요.")
    outcome = skill_repo.reject_doc(doc_id, _client_ip(request), reason)
    if outcome == "not_found":
        raise HTTPException(status_code=404, detail="SKILL 초안을 찾을 수 없습니다.")
    if outcome != "ok":
        raise HTTPException(status_code=409, detail="검토 대기(draft)·생성 실패(error) 초안만 반려할 수 있습니다.")
    return _draft_detail(skill_repo.get_doc(doc_id))


# ---------------------------------------------------------------- 문의 유형

class TypeState(BaseModel):
    state: str


class TypeMerge(BaseModel):
    into: int


@router.get("/skills/types")
def list_types() -> dict:
    analyses = skill_repo.list_analysis()
    mismatch: dict[int, int] = {}
    for a in analyses:
        if a["status"] == "ok" and a["mismatch"] and a["type_id"] is not None:
            mismatch[a["type_id"]] = mismatch.get(a["type_id"], 0) + 1
    items = []
    for t in skill_repo.list_types():
        drafts = skill_repo.docs_for_type(t["type_id"], OPEN_DRAFT_STATUSES)
        items.append({
            "type_id": t["type_id"], "label": t["label"], "description": t["description"],
            "skill_name": t["skill_name"], "state": t["state"], "merged_into": t["merged_into"], "origin": t["origin"],
            "case_count": t["case_count"], "mismatch_count": mismatch.get(t["type_id"], 0),
            "recent_cases": skill_repo.recent_cases(t["type_id"]) if t["state"] != "merged" else [],
            "open_drafts": [{"doc_id": d["doc_id"], "status": d["status"], "name": _display_name(d)} for d in drafts],
            "has_rejected": bool(skill_repo.docs_for_type(t["type_id"], ("rejected",))),
            "created_at": t["created_at"],
        })
    pending = sum(1 for a in analyses if a["status"] == "error")
    return {"items": items, "author": skills.author_skill_status(),
            "analysis": {"total": len(analyses), "errors": pending}}


@router.post("/skills/types/{type_id}/draft", status_code=202)
def request_type_draft(type_id: int):
    result = skill_author.request_draft(type_id)
    if "error" in result:
        raise HTTPException(status_code=result["status_code"], detail=result["error"])
    return JSONResponse(status_code=202, content={
        "doc_id": result["doc_id"], "already": result["already"],
        "message": "초안 생성을 요청했습니다. 분석 스레드가 메일 처리가 없을 때 만듭니다.",
    })


@router.post("/skills/types/{type_id}/state")
def set_type_state(type_id: int, payload: TypeState) -> dict:
    if payload.state not in ("open", "no_skill_needed"):
        raise HTTPException(status_code=400, detail="state는 open 또는 no_skill_needed입니다.")
    outcome = skill_repo.set_type_state(type_id, payload.state)
    if outcome == "not_found":
        raise HTTPException(status_code=404, detail="문의 유형을 찾을 수 없습니다.")
    if outcome == "merged":
        raise HTTPException(status_code=409, detail="다른 유형으로 합쳐진 유형입니다.")
    return skill_repo.get_type(type_id)


@router.post("/skills/types/{type_id}/merge")
def merge_type(type_id: int, payload: TypeMerge) -> dict:
    outcome = skill_repo.merge_type(type_id, payload.into)
    errors = {
        "same": (400, "같은 유형으로는 합칠 수 없습니다."),
        "not_found": (404, "문의 유형을 찾을 수 없습니다."),
        "merged": (409, "이미 다른 유형으로 합쳐진 유형입니다."),
        "target_merged": (409, "합칠 대상이 이미 다른 유형으로 합쳐졌습니다."),
    }
    if outcome in errors:
        code, detail = errors[outcome]
        raise HTTPException(status_code=code, detail=detail)
    return {"merged": skill_repo.get_type(type_id), "into": skill_repo.get_type(payload.into)}


# ---------------------------------------------------------------- 분석된 문의

@router.get("/skills/analysis")
def list_analysis(
    type_id: int | None = None,
    mismatch: bool | None = None,
    limit: int = Query(50, ge=1, le=500),
) -> dict:
    rows = skill_repo.list_analysis(type_id=type_id)
    if mismatch is not None:
        rows = [r for r in rows if r["mismatch"] == mismatch]
    return {
        "items": [{
            "task_id": r["task_id"], "subject": r["subject"], "task_status": r["task_status"],
            "received_at": r["received_at"], "status": r["status"],
            "type": {"type_id": r["type_id"], "label": r["type_label"]} if r["type_id"] is not None else None,
            "covered_by": r["covered_by"], "used_skills": r["used_skills"], "mismatch": r["mismatch"],
            "reason": r["reason"], "error": r["error"], "attempts": r["attempts"], "analyzed_at": r["analyzed_at"],
        } for r in rows[:limit]],
        "total": len(rows),
    }


# ---------------------------------------------------------------- 절차 하나 (이름 경로는 마지막에)

@router.get("/skills/{name}")
def get_skill(name: str) -> dict:
    repo = skills.repo_skills().get(name)
    if repo is not None:
        off = skill_repo.disabled_skills().get(name)
        return {
            "name": repo.name, "description": repo.description, "channels": list(repo.channels), "origin": "repo",
            "version": None, "digest": repo.digest, "body": repo.body, "read_only": True,
            "server_applied": repo.name in skills.SERVER_CHOSEN, "active": off is None, "history": [],
            "author": skills.AUTHOR_CHANNEL in repo.channels, "enabled": off is None,
            "disabled_at": off["disabled_at"] if off else None, "disabled_by": off["disabled_by"] if off else None,
            "files": list(repo.files),
        }
    history = [d for d in skill_repo.history(name) if d["status"] != "generating"]
    if not history or skill_author.is_placeholder_name(name):
        raise HTTPException(status_code=404, detail="SKILL을 찾을 수 없습니다.")
    active = skill_repo.active_doc(name)
    shown = active or skill_repo.latest_approved(name) or history[-1]
    return {
        "name": name, "description": shown.get("description"), "channels": list(skills.DB_CHANNELS), "origin": "db",
        "version": shown["version"], "digest": shown.get("digest"), "body": shown.get("body"), "read_only": False,
        "server_applied": False, "active": active is not None, "doc_id": shown["doc_id"],
        "type": _type_ref(shown.get("type_id")),
        "open_draft": (lambda d: d and {"doc_id": d["doc_id"], "version": d["version"]})(skill_repo.open_draft_for_name(name)),
        "history": [_history_item(d) for d in history],
    }


@router.post("/skills/{name}/drafts")
def new_version_draft(name: str) -> dict:
    _repo_or_400(name, "고치기")
    existing = skill_repo.open_draft_for_name(name)
    if existing is not None:
        return {**_draft_detail(existing), "already": True}
    base = skill_repo.latest_approved(name)
    if base is None:
        raise HTTPException(status_code=404, detail="승인된 적이 있는 DB SKILL이 아닙니다.")
    check = skill_author.recheck_doc(base, base.get("description") or "", base.get("body") or "")
    doc_id = skill_repo.new_version_from_approved(name, check, skills.body_digest(base.get("body") or ""))
    return {**_draft_detail(skill_repo.get_doc(doc_id)), "already": False}


@router.post("/skills/{name}/retire")
def retire_skill(name: str, request: Request) -> dict:
    _repo_or_400(name, "사용 중지")
    if skill_repo.retire(name, _client_ip(request)) is None:
        raise HTTPException(status_code=409, detail="사용 중인 DB SKILL이 아닙니다 (이미 사용 중지됐거나 승인된 적이 없습니다).")
    return get_skill(name)


def _repo_skill_or_error(name: str) -> None:
    """끄기·켜기는 저장소 절차만. DB 절차는 사용 중지(retire)를 쓴다."""
    if name in skills.repo_skills():
        return
    if skill_repo.history(name):
        raise HTTPException(status_code=400, detail="생성 SKILL은 '사용 중지'로 멈춥니다 (끄기는 저장소 SKILL만).")
    raise HTTPException(status_code=404, detail="SKILL을 찾을 수 없습니다.")


@router.post("/skills/{name}/disable")
def disable_repo_skill(name: str, request: Request) -> dict:
    """저장소 절차를 끈다: 답변(서버 적용·선택 목록·load_skill)과 초안 생성에서 빠진다. 파일은 그대로다. 이미 꺼져 있으면 그대로 돌려준다."""
    _repo_skill_or_error(name)
    skill_repo.disable_skill(name, _client_ip(request))
    return get_skill(name)


@router.post("/skills/{name}/enable")
def enable_repo_skill(name: str) -> dict:
    """꺼 둔 저장소 절차를 다시 켠다. 끄면서 끊은 문의 유형 연결은 되살리지 않는다."""
    _repo_skill_or_error(name)
    skill_repo.enable_skill(name)
    return get_skill(name)
