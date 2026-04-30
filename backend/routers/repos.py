from fastapi import APIRouter, Request

from backend.services.repo_service import get_all_repos, get_repo_count, get_dashboard_stats, pin_repo

router = APIRouter(prefix="/api", tags=["repos"])


@router.get("/repos")
async def list_repos(
    request: Request,
    skip: int = 0,
    limit: int = 50,
    sort_by: str = "weight",
    search: str | None = None,
):
    db = request.app.state.db
    repos = await get_all_repos(db, skip, limit, sort_by, search)
    total = await get_repo_count(db, search)
    return {"repos": repos, "total": total}


@router.post("/repos/{full_name:path}/pin")
async def toggle_pin(request: Request, full_name: str):
    db = request.app.state.db
    pinned = await pin_repo(db, full_name)
    return {"full_name": full_name, "pinned": pinned}


@router.get("/stats")
async def stats(request: Request):
    db = request.app.state.db
    return await get_dashboard_stats(db)
