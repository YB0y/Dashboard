from datetime import datetime, timezone
from pymongo import UpdateOne
from backend.database import Database
from backend.config import Settings
import logging

logger = logging.getLogger(__name__)


async def sync_repos_from_config(db: Database, settings: Settings) -> int:
    """Load all repos from repos.json into MongoDB Gittensor collection using bulk_write."""
    repos_data = settings.load_repos()
    if not repos_data:
        return 0

    now = datetime.now(timezone.utc).isoformat()
    operations = []
    alias_to_full_name: dict[str, str] = {}
    for full_name, info in repos_data.items():
        parts = full_name.split("/", 1)
        owner = parts[0]
        name = parts[1] if len(parts) > 1 else full_name
        weight = info.get("weight", 0.0)
        aliases = info.get("aliases", [])
        if isinstance(aliases, str):
            aliases = [aliases]
        for alias in aliases:
            if alias and alias != full_name:
                alias_to_full_name[alias] = full_name

        operations.append(UpdateOne(
            {"full_name": full_name},
            {
                "$set": {
                    "full_name": full_name,
                    "owner": owner,
                    "name": name,
                    "weight": weight,
                    "url": f"https://github.com/{full_name}",
                },
                "$setOnInsert": {
                    "description": "",
                    "stars": 0,
                    "forks": 0,
                    "open_issues_count": 0,
                    "last_pushed_at": "",
                    "last_polled_at": "",
                    "last_issue_at": "",
                    "pinned": False,
                    "created_at": now,
                },
                "$unset": {"tier": ""},
            },
            upsert=True,
        ))

    if operations:
        result = await db.repos.bulk_write(operations, ordered=False)
        logger.info(
            "Bulk sync: %d upserted, %d matched (already existed)",
            result.upserted_count, result.matched_count,
        )

    for alias, full_name in alias_to_full_name.items():
        target_info = repos_data.get(full_name, {})
        target_weight = target_info.get("weight", 0.0)
        issue_result = await db.issues.update_many(
            {"repo_full_name": alias},
            {"$set": {"repo_full_name": full_name, "weight": target_weight}},
        )
        notification_result = await db.notifications.update_many(
            {"repo_full_name": alias},
            {"$set": {"repo_full_name": full_name}},
        )
        await db.repos.delete_many({"full_name": alias})
        if issue_result.modified_count or notification_result.modified_count:
            logger.info(
                "Migrated alias %s -> %s (%d issues, %d notifications)",
                alias,
                full_name,
                issue_result.modified_count,
                notification_result.modified_count,
            )

    # Remove repos from DB that are no longer in repos.json
    config_names = set(repos_data.keys())
    stale_repos = await db.repos.distinct("full_name", {"full_name": {"$nin": list(config_names)}})
    if stale_repos:
        await db.repos.delete_many({"full_name": {"$in": stale_repos}})
        await db.issues.delete_many({"repo_full_name": {"$in": stale_repos}})
        await db.notifications.delete_many({"repo_full_name": {"$in": stale_repos}})
        logger.info("Removed %d stale repos (and their issues/notifications) not in repos.json", len(stale_repos))

    logger.info("Synced %d repos from config to MongoDB", len(operations))
    return len(operations)


async def update_repo_metadata(db: Database, full_name: str, gh_data: dict) -> None:
    await db.repos.update_one(
        {"full_name": full_name},
        {"$set": {
            "url": gh_data.get("html_url", ""),
            "description": gh_data.get("description", "") or "",
            "stars": gh_data.get("stargazers_count", 0),
            "forks": gh_data.get("forks_count", 0),
            "open_issues_count": gh_data.get("open_issues_count", 0),
            "last_pushed_at": gh_data.get("pushed_at", ""),
            "last_polled_at": datetime.now(timezone.utc).isoformat(),
        }},
    )


MAINTAINER_ROLES = ["OWNER", "MEMBER", "COLLABORATOR", "CONTRIBUTOR"]


async def get_unread_counts_by_repo(db: Database) -> dict[str, dict[str, int]]:
    """Return {repo_full_name: {maintainer_unread: N, normal_unread: N}} for repos with unread issues."""
    pipeline = [
        {"$match": {"read": False, "state": "open"}},
        {"$group": {
            "_id": "$repo_full_name",
            "maintainer_unread": {
                "$sum": {
                    "$cond": [{"$in": ["$author_role", MAINTAINER_ROLES]}, 1, 0]
                }
            },
            "normal_unread": {
                "$sum": {
                    "$cond": [{"$in": ["$author_role", MAINTAINER_ROLES]}, 0, 1]
                }
            },
        }},
    ]
    result = {}
    async for doc in db.issues.aggregate(pipeline):
        result[doc["_id"]] = {
            "maintainer_unread": doc["maintainer_unread"],
            "normal_unread": doc["normal_unread"],
        }
    return result


async def bump_repo_activity(db: Database, full_name: str) -> None:
    """Update last_issue_at to now when a new issue is found."""
    await db.repos.update_one(
        {"full_name": full_name},
        {"$set": {"last_issue_at": datetime.now(timezone.utc).isoformat()}},
    )


async def pin_repo(db: Database, full_name: str) -> bool:
    """Toggle pin status for a repo. Returns new pinned state."""
    repo = await db.repos.find_one({"full_name": full_name}, {"pinned": 1})
    new_state = not bool(repo.get("pinned", False)) if repo else False
    await db.repos.update_one(
        {"full_name": full_name},
        {"$set": {"pinned": new_state}},
    )
    return new_state


async def get_all_repos(
    db: Database, skip: int = 0, limit: int = 50,
    sort_by: str = "weight", search: str | None = None,
) -> list[dict]:
    query: dict = {}
    if search:
        query["full_name"] = {"$regex": search, "$options": "i"}

    sort_fields = {
        "weight": "weight",
        "stars": "stars",
        "recent": "last_issue_at",
    }
    sort_field = sort_fields.get(sort_by, "last_issue_at")
    # Sort pinned repos first, then by chosen field
    cursor = db.repos.find(query, {"_id": 0}).sort([
        ("pinned", -1),
        (sort_field, -1),
    ]).skip(skip).limit(limit)
    repos = await cursor.to_list(length=limit)

    # Attach split unread issue counts
    unread_map = await get_unread_counts_by_repo(db)
    for repo in repos:
        counts = unread_map.get(repo["full_name"], {"maintainer_unread": 0, "normal_unread": 0})
        repo["maintainer_unread"] = counts["maintainer_unread"]
        repo["normal_unread"] = counts["normal_unread"]
        repo["unread_count"] = counts["maintainer_unread"] + counts["normal_unread"]
        repo.setdefault("pinned", False)

    return repos


async def get_repo_count(db: Database, search: str | None = None) -> int:
    query: dict = {}
    if search:
        query["full_name"] = {"$regex": search, "$options": "i"}
    return await db.repos.count_documents(query)


async def get_dashboard_stats(db: Database) -> dict:
    total_repos = await db.repos.count_documents({})
    total_open_issues = await db.issues.count_documents({"state": "open"})
    unread_issues = await db.issues.count_documents({"read": False})

    return {
        "total_repos": total_repos,
        "total_open_issues": total_open_issues,
        "unread_issues": unread_issues,
    }
