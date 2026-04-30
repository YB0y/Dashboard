from datetime import datetime, timezone
from backend.database import Database
import logging

logger = logging.getLogger(__name__)


async def mark_repo_closed_except(db: Database, repo_full_name: str, open_github_ids: list[int]) -> int:
    """For one repo: flip every state=open doc to closed unless its github_id is in the given list.

    Used after a full /issues?state=open scan to bring DB in sync with GitHub.
    Returns the number of docs updated.
    """
    result = await db.issues.update_many(
        {
            "repo_full_name": repo_full_name,
            "state": "open",
            "github_id": {"$nin": open_github_ids},
        },
        {"$set": {"state": "closed"}},
    )
    return result.modified_count


async def upsert_issues(db: Database, repo_full_name: str, weight: float, gh_issues: list[dict]) -> list[dict]:
    """Insert new issues. Returns list of newly inserted issue docs."""
    new_issues = []
    for issue in gh_issues:
        labels = [l["name"] for l in issue.get("labels", [])]
        doc = {
            "github_id": issue["id"],
            "repo_full_name": repo_full_name,
            "weight": weight,
            "number": issue["number"],
            "title": issue["title"],
            "body": (issue.get("body", "") or "")[:500],
            "author": issue["user"]["login"],
            "author_avatar": issue["user"].get("avatar_url", ""),
            "author_role": issue.get("author_association", "NONE"),
            "labels": labels,
            "state": issue["state"],
            "html_url": issue["html_url"],
            "created_at": issue["created_at"],
            "updated_at": issue["updated_at"],
            "first_seen_at": datetime.now(timezone.utc).isoformat(),
            "read": False,
        }
        try:
            result = await db.issues.update_one(
                {"github_id": issue["id"]},
                {"$setOnInsert": doc},
                upsert=True,
            )
            if result.upserted_id:
                doc["_id"] = str(result.upserted_id)
                new_issues.append(doc)
        except Exception as e:
            logger.warning("Issue upsert FAILED for %s#%s id=%s: %s", repo_full_name, issue.get("number"), issue.get("id"), e)
            continue
    return new_issues


async def get_issues(
    db: Database,
    repo_full_name: str | None = None,
    read_filter: str | None = None,
    limit: int = 50,
    skip: int = 0,
) -> list[dict]:
    query: dict = {"state": "open"}

    if repo_full_name:
        query["repo_full_name"] = repo_full_name

    if read_filter == "unread":
        query["read"] = False
    elif read_filter == "read":
        query["read"] = True

    cursor = db.issues.find(query, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit)
    return await cursor.to_list(length=limit)


async def get_issue_count(
    db: Database,
    repo_full_name: str | None = None,
    read_filter: str | None = None,
) -> int:
    query: dict = {"state": "open"}
    if repo_full_name:
        query["repo_full_name"] = repo_full_name
    if read_filter == "unread":
        query["read"] = False
    elif read_filter == "read":
        query["read"] = True
    return await db.issues.count_documents(query)


async def mark_issue_read(db: Database, github_id: int) -> None:
    await db.issues.update_one({"github_id": github_id}, {"$set": {"read": True}})


async def mark_all_issues_read(db: Database, repo_full_name: str | None = None) -> None:
    query: dict = {"read": False}
    if repo_full_name:
        query["repo_full_name"] = repo_full_name
    await db.issues.update_many(query, {"$set": {"read": True}})


async def get_unread_count(db: Database) -> int:
    return await db.issues.count_documents({"read": False})
