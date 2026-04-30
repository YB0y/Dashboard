from fastapi import APIRouter, Request

from backend.services.issue_service import (
    get_issues, get_issue_count, mark_issue_read, mark_all_issues_read, get_unread_count,
)

router = APIRouter(prefix="/api", tags=["issues"])


@router.get("/issues")
async def list_issues(
    request: Request,
    repo: str | None = None,
    read_filter: str | None = None,
    limit: int = 50,
    skip: int = 0,
):
    db = request.app.state.db
    items = await get_issues(db, repo, read_filter, limit, skip)
    total = await get_issue_count(db, repo, read_filter)
    return {"issues": items, "total": total}


@router.get("/issues/unread-count")
async def unread_count(request: Request):
    db = request.app.state.db
    count = await get_unread_count(db)
    return {"count": count}


@router.post("/issues/{github_id}/read")
async def mark_read(request: Request, github_id: int):
    db = request.app.state.db
    await mark_issue_read(db, github_id)
    return {"ok": True}


@router.post("/issues/read-all")
async def mark_all_read(
    request: Request,
    repo: str | None = None,
):
    db = request.app.state.db
    await mark_all_issues_read(db, repo)
    return {"ok": True}
