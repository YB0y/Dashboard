from fastapi import APIRouter, Request

from backend.services.notification_service import (
    get_notifications, get_unread_count, mark_notification_read, mark_all_notifications_read,
)

router = APIRouter(prefix="/api", tags=["notifications"])


@router.get("/notifications")
async def list_notifications(request: Request, unread_only: bool = False, limit: int = 50):
    db = request.app.state.db
    return await get_notifications(db, unread_only, limit)


@router.get("/notifications/count")
async def unread_count(request: Request):
    db = request.app.state.db
    count = await get_unread_count(db)
    return {"count": count}


@router.post("/notifications/{github_id}/read")
async def mark_read(request: Request, github_id: int):
    db = request.app.state.db
    await mark_notification_read(db, github_id)
    return {"ok": True}


@router.post("/notifications/read-all")
async def mark_all_read(request: Request):
    db = request.app.state.db
    await mark_all_notifications_read(db)
    return {"ok": True}
