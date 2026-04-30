from datetime import datetime, timezone
from backend.database import Database


async def create_notification(db: Database, issue_doc: dict) -> None:
    await db.notifications.insert_one({
        "github_id": issue_doc["github_id"],
        "repo_full_name": issue_doc["repo_full_name"],
        "issue_number": issue_doc["number"],
        "issue_title": issue_doc["title"],
        "issue_url": issue_doc["html_url"],
        "author": issue_doc["author"],
        "read": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })


async def get_notifications(db: Database, unread_only: bool = False, limit: int = 50) -> list[dict]:
    query: dict = {}
    if unread_only:
        query["read"] = False
    cursor = db.notifications.find(query, {"_id": 0}).sort("created_at", -1).limit(limit)
    return await cursor.to_list(length=limit)


async def mark_notification_read(db: Database, github_id: int) -> None:
    await db.notifications.update_one({"github_id": github_id}, {"$set": {"read": True}})


async def mark_all_notifications_read(db: Database) -> None:
    await db.notifications.update_many({"read": False}, {"$set": {"read": True}})


async def get_unread_count(db: Database) -> int:
    return await db.notifications.count_documents({"read": False})
