from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/settings", tags=["settings"])


async def _get_slack_enabled(db) -> bool:
    doc = await db.settings_coll.find_one({"_id": "slack"})
    if doc is None:
        return True
    return bool(doc.get("enabled", True))


@router.get("/slack")
async def get_slack(request: Request):
    db = request.app.state.db
    enabled = await _get_slack_enabled(db)
    webhook_configured = bool(request.app.state.settings.slack_webhook_url)
    return {"enabled": enabled, "webhook_configured": webhook_configured}


@router.put("/slack")
async def set_slack(request: Request):
    body = await request.json()
    enabled = bool(body.get("enabled", True))
    db = request.app.state.db
    await db.settings_coll.update_one(
        {"_id": "slack"},
        {"$set": {"enabled": enabled}},
        upsert=True,
    )
    return {"enabled": enabled}
