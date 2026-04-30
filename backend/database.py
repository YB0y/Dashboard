import motor.motor_asyncio
import logging

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_url: str):
        self.client = motor.motor_asyncio.AsyncIOMotorClient(db_url)
        self.db = self.client.get_database()
        self.repos = self.db["Gittensor"]
        self.issues = self.db["issues"]
        self.notifications = self.db["notifications"]
        self.settings_coll = self.db["settings"]

    async def init(self):
        await self.repos.create_index("full_name", unique=True)
        await self.repos.create_index("weight")
        await self.repos.create_index("pinned")
        await self.repos.create_index("last_issue_at")
        await self.issues.create_index("github_id", unique=True)
        await self.issues.create_index("repo_full_name")
        await self.issues.create_index("state")
        await self.issues.create_index("read")
        await self.issues.create_index("created_at")
        await self.issues.create_index("author_role")
        await self.notifications.create_index("read")
        await self.notifications.create_index("created_at")

        # Drop legacy tier indexes if present
        for coll in (self.repos, self.issues, self.notifications):
            try:
                await coll.drop_index("tier_1")
            except Exception:
                pass

        # Strip stale tier field from existing docs
        for coll in (self.repos, self.issues, self.notifications):
            await coll.update_many({"tier": {"$exists": True}}, {"$unset": {"tier": ""}})

        # Ensure all repos have required fields
        for field, default in [("pinned", False), ("last_issue_at", "")]:
            result = await self.repos.update_many(
                {field: {"$exists": False}},
                {"$set": {field: default}},
            )
            if result.modified_count:
                logger.info("Set %s=%r on %d repos missing the field", field, default, result.modified_count)

        logger.info("MongoDB connected and indexes created")

    async def close(self):
        self.client.close()
