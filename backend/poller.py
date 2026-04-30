import asyncio
import logging
import httpx
from datetime import datetime, timezone, timedelta

from backend.database import Database
from backend.github_client import GitHubClient
from backend.websocket_manager import WebSocketManager
from backend.config import Settings
from backend.services.repo_service import sync_repos_from_config, update_repo_metadata, get_dashboard_stats, bump_repo_activity
from backend.services.issue_service import upsert_issues, mark_repo_closed_except
from backend.services.notification_service import create_notification

logger = logging.getLogger(__name__)

SEARCH_BATCH_SIZE = 40

# Overlap buffer: search 30 minutes before the last search time
# to give GitHub Search more time to index newly created issues.
# Deduplication via github_id prevents duplicates.
OVERLAP_MINUTES = 30

# Reconciliation: per-repo REST /issues?since=... fallback for anything Search misses.
# The first pass after restart looks back this far so the very first window covers any
# issue created moments before the process started.
RECONCILE_INITIAL_LOOKBACK_MINUTES = 30
# Every subsequent pass overlaps the previous window by this much, so no issue can fall
# between two consecutive scans even with GitHub propagation delay.
RECONCILE_OVERLAP_MINUTES = 15
# Sleep between repo calls within a reconciliation chunk (gentle pacing).
RECONCILE_REPO_DELAY_SECONDS = 0.3
# Sleep between full reconciliation cycles.
RECONCILE_CYCLE_DELAY_SECONDS = 5

# Only track issues from these author associations (maintainers/contributors)
MAINTAINER_ROLES = {"OWNER", "MEMBER", "COLLABORATOR", "CONTRIBUTOR"}


class Poller:
    def __init__(
        self,
        db: Database,
        gh_clients: list[GitHubClient],
        ws_manager: WebSocketManager,
        settings: Settings,
    ):
        self.db = db
        self.gh_clients = gh_clients
        self.ws = ws_manager
        self.settings = settings
        self._running = False
        self._metadata_index = 0
        self._round_count = 0
        self._all_repos: list[dict] = []
        self._repo_map: dict[str, dict] = {}

        # Per-batch timestamps for the Search-API loop
        self._batch_timestamps: dict[int, str] = {}

        # Per-repo cutoffs for the REST-API reconciliation loop
        self._reconcile_since: dict[str, str] = {}

        # Lock for DB writes (upsert + broadcast) to avoid race conditions
        self._db_lock = asyncio.Lock()

        # Background reconciliation task handle
        self._reconcile_task: asyncio.Task | None = None
        # One-time full backfill task handle
        self._backfill_task: asyncio.Task | None = None

    async def start(self):
        self._running = True
        count = await sync_repos_from_config(self.db, self.settings)
        logger.info("Poller started. %d repos synced. %d PATs available.", count, len(self.gh_clients))

        # Load all repos directly from DB, ordered by weight desc
        cursor = self.db.repos.find({}, {"_id": 0}).sort("weight", -1)
        self._all_repos = await cursor.to_list(length=99999)
        self._repo_map = {r["full_name"]: r for r in self._all_repos}
        # Case-insensitive lookup: lowercase -> canonical full_name
        self._repo_name_lower = {r["full_name"].lower(): r["full_name"] for r in self._all_repos}

        logger.info("Loaded %d repos (sorted by weight desc)", len(self._all_repos))

        # Build batches of repo names
        all_names = [r["full_name"] for r in self._all_repos]
        self._batches = [
            all_names[i : i + SEARCH_BATCH_SIZE]
            for i in range(0, len(all_names), SEARCH_BATCH_SIZE)
        ]

        # Initialize all batch timestamps to 2 hours ago
        init_time = (
            datetime.now(timezone.utc) - timedelta(hours=2)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        for i in range(len(self._batches)):
            self._batch_timestamps[i] = init_time

        # Distribute batches across workers
        num_workers = len(self.gh_clients)
        self._worker_assignments: list[list[int]] = [[] for _ in range(num_workers)]
        for i in range(len(self._batches)):
            self._worker_assignments[i % num_workers].append(i)

        logger.info(
            "Split %d batches across %d workers: %s",
            len(self._batches),
            num_workers,
            [len(a) for a in self._worker_assignments],
        )

        # Broadcast initial stats
        stats = await get_dashboard_stats(self.db)
        await self.ws.broadcast({"event": "stats_update", **stats})

        # No initial full backfill — only track issues created from now on.
        # Start the REST-based reconciliation loop (safety net against Search-API misses).
        self._reconcile_task = asyncio.create_task(self._reconciliation_loop())

        # Main loop
        while self._running:
            try:
                self._round_count += 1
                logger.info("=== Round %d: %d workers scanning %d batches ===",
                            self._round_count, num_workers, len(self._batches))

                # Launch all workers in parallel
                tasks = []
                for worker_id in range(num_workers):
                    task = asyncio.create_task(
                        self._worker_run(
                            worker_id,
                            self.gh_clients[worker_id],
                            self._worker_assignments[worker_id],
                        )
                    )
                    tasks.append(task)

                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Sum up results
                round_total_new = 0
                for worker_id, result in enumerate(results):
                    if isinstance(result, Exception):
                        logger.exception("Worker %d failed: %s", worker_id, result)
                    else:
                        round_total_new += result

                # Round complete — broadcast stats
                await self._broadcast_stats()

                if round_total_new:
                    logger.info("Round %d complete: %d new issues found", self._round_count, round_total_new)
                else:
                    logger.info("Round %d complete: no new issues", self._round_count)

                # Log rate limits for all workers
                for i, gh in enumerate(self.gh_clients):
                    logger.info(
                        "  Worker %d — Search remaining: %d, REST remaining: %d",
                        i, gh.search_remaining, gh.rate_limit_remaining,
                    )

                # Every 10 rounds, refresh some repo metadata
                if self._round_count % 10 == 0:
                    await self._slow_metadata_cycle()

            except Exception:
                logger.exception("Error in poll round")

            if not self._running:
                break

            # Brief pause between full rounds
            await asyncio.sleep(5)

    async def _worker_run(
        self, worker_id: int, gh: GitHubClient, batch_indices: list[int]
    ) -> int:
        """A single worker processes its assigned batches sequentially using its own PAT."""
        worker_new = 0

        for batch_idx in batch_indices:
            if not self._running:
                break

            batch_names = self._batches[batch_idx]

            # Per-batch timestamp with overlap buffer
            raw_since = self._batch_timestamps[batch_idx]
            since_dt = datetime.fromisoformat(raw_since.replace("Z", "+00:00"))
            buffered_since = (since_dt - timedelta(minutes=OVERLAP_MINUTES)).strftime("%Y-%m-%dT%H:%M:%SZ")

            new_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            # Search using this worker's PAT
            issues = await gh.search_issues_batch(batch_names, buffered_since)

            # Update timestamp after successful search
            self._batch_timestamps[batch_idx] = new_timestamp

            if not issues:
                continue

            # Process ALL found issues (lock to avoid concurrent DB write races)
            batch_new = 0
            for issue in issues:
                repo_full_raw = issue.get("repository_url", "").replace(
                    "https://api.github.com/repos/", ""
                )
                # Normalize to the canonical name from repos.json (case-insensitive)
                repo_full = self._repo_name_lower.get(repo_full_raw.lower(), repo_full_raw)
                repo_info = self._repo_map.get(repo_full, {})
                weight = repo_info.get("weight", 0)

                batch_new += await self._upsert_and_notify(repo_full, weight, [issue])

            if batch_new:
                logger.info("Worker %d | Batch %d/%d: found %d new issues",
                            worker_id, batch_idx + 1, len(self._batches), batch_new)
            worker_new += batch_new

        return worker_new

    async def stop(self):
        self._running = False
        for t in (self._reconcile_task, self._backfill_task):
            if t:
                t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass

    async def _upsert_and_notify(self, repo_full: str, weight: float, issues: list[dict]) -> int:
        """Upsert issues and fan out notifications for any that are new. Returns count of new issues."""
        new_count = 0
        async with self._db_lock:
            new = await upsert_issues(self.db, repo_full, weight, issues)
            if new:
                await bump_repo_activity(self.db, repo_full)
            for issue_doc in new:
                await create_notification(self.db, issue_doc)
                await self.ws.broadcast({
                    "event": "new_issue",
                    "repo_full_name": repo_full,
                    "issue_title": issue_doc["title"],
                    "issue_number": issue_doc["number"],
                    "issue_url": issue_doc["html_url"],
                    "author": issue_doc["author"],
                    "author_role": issue_doc.get("author_role", ""),
                    "weight": weight,
                    "labels": issue_doc.get("labels", []),
                })
                # Slack notification: maintainer issues in higher-weight repos (>= 0.1)
                if (
                    weight >= 0.1
                    and issue_doc.get("author_role", "NONE") in {"OWNER", "MEMBER", "COLLABORATOR"}
                    and self.settings.slack_webhook_url
                    and await self._slack_enabled()
                ):
                    asyncio.create_task(
                        self._send_slack_notification(repo_full, issue_doc, weight)
                    )
                new_count += 1
        return new_count

    async def _initial_full_backfill(self):
        """One-time pass: paginate ALL open issues for every repo and upsert.

        Brings the DB up to parity with GitHub on first run; later runs are mostly no-ops
        because upsert_issues skips existing github_id docs.
        """
        # Distribute repos round-robin across the GH clients
        num_workers = len(self.gh_clients)
        chunks: list[list[dict]] = [[] for _ in range(num_workers)]
        for i, r in enumerate(self._all_repos):
            chunks[i % num_workers].append(r)

        logger.info(
            "Full backfill starting: %d repos in %d chunks (%s)",
            len(self._all_repos), num_workers, [len(c) for c in chunks],
        )

        async def backfill_chunk(worker_id: int, gh: GitHubClient, repos: list[dict]):
            chunk_new = 0
            for repo in repos:
                if not self._running:
                    break
                full_name = repo["full_name"]
                weight = repo.get("weight", 0)
                try:
                    items = await gh.get_all_open_issues(full_name)
                except Exception:
                    logger.exception("Backfill fetch failed for %s", full_name)
                    continue
                if items is not None:
                    new = await self._upsert_and_notify(full_name, weight, items) if items else 0
                    open_ids = [i["id"] for i in items]
                    closed_count = await mark_repo_closed_except(self.db, full_name, open_ids)
                    if new or closed_count:
                        chunk_new += new
                        logger.info(
                            "Backfill worker %d: %s -> %d new, %d marked closed (of %d open on GitHub)",
                            worker_id, full_name, new, closed_count, len(items),
                        )
                # Gentle pacing
                await asyncio.sleep(0.2)
            logger.info("Backfill worker %d: chunk done, %d new total", worker_id, chunk_new)
            return chunk_new

        tasks = [
            asyncio.create_task(backfill_chunk(i, self.gh_clients[i], chunks[i]))
            for i in range(num_workers)
        ]
        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            grand_total = sum(r for r in results if isinstance(r, int))
            logger.info("Full backfill complete: %d new issues stored across all repos", grand_total)
        except asyncio.CancelledError:
            for t in tasks:
                t.cancel()
            raise

    async def _reconciliation_loop(self):
        """REST-API safety net: per-repo /issues?since=... that catches anything Search misses.

        Splits all repos round-robin across the 5 PATs and runs one chunk-loop per token.
        Each repo gets re-checked every ~RECONCILE_CYCLE_DELAY_SECONDS + chunk_size * RECONCILE_REPO_DELAY_SECONDS.
        """
        init_since = (
            datetime.now(timezone.utc) - timedelta(minutes=RECONCILE_INITIAL_LOOKBACK_MINUTES)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        for repo in self._all_repos:
            self._reconcile_since[repo["full_name"]] = init_since

        num_workers = len(self.gh_clients)
        chunks: list[list[dict]] = [[] for _ in range(num_workers)]
        for i, r in enumerate(self._all_repos):
            chunks[i % num_workers].append(r)

        logger.info(
            "Reconciliation loop started: %d repos in %d chunks (%s)",
            len(self._all_repos), num_workers, [len(c) for c in chunks],
        )

        tasks = [
            asyncio.create_task(
                self._reconcile_chunk_loop(worker_id, self.gh_clients[worker_id], chunks[worker_id])
            )
            for worker_id in range(num_workers)
        ]
        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        except asyncio.CancelledError:
            for t in tasks:
                t.cancel()
            raise

    async def _reconcile_chunk_loop(self, worker_id: int, gh: GitHubClient, repos: list[dict]):
        """For each repo in this worker's chunk, repeatedly fetch /issues?since=... and upsert."""
        while self._running:
            cycle_new = 0
            for repo in repos:
                if not self._running:
                    break
                full_name = repo["full_name"]
                weight = repo.get("weight", 0)

                raw_since = self._reconcile_since.get(full_name)
                if not raw_since:
                    raw_since = (
                        datetime.now(timezone.utc) - timedelta(minutes=RECONCILE_INITIAL_LOOKBACK_MINUTES)
                    ).strftime("%Y-%m-%dT%H:%M:%SZ")
                try:
                    since_dt = datetime.fromisoformat(raw_since.replace("Z", "+00:00"))
                except ValueError:
                    since_dt = datetime.now(timezone.utc) - timedelta(minutes=RECONCILE_INITIAL_LOOKBACK_MINUTES)

                buffered_since = (
                    since_dt - timedelta(minutes=RECONCILE_OVERLAP_MINUTES)
                ).strftime("%Y-%m-%dT%H:%M:%SZ")
                new_cutoff = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

                if gh.is_rate_limited():
                    await asyncio.sleep(5)
                    continue

                try:
                    items = await gh.get_issues(full_name, since=buffered_since, per_page=100)
                except Exception:
                    logger.exception("Reconcile fetch failed for %s", full_name)
                    await asyncio.sleep(1)
                    continue

                self._reconcile_since[full_name] = new_cutoff

                if items:
                    new = await self._upsert_and_notify(full_name, weight, items)
                    if new:
                        cycle_new += new
                        logger.info(
                            "Reconcile worker %d: backfilled %d issues for %s",
                            worker_id, new, full_name,
                        )

                await asyncio.sleep(RECONCILE_REPO_DELAY_SECONDS)

            if cycle_new:
                logger.info(
                    "Reconcile worker %d: cycle complete, %d new issues this pass",
                    worker_id, cycle_new,
                )

            await asyncio.sleep(RECONCILE_CYCLE_DELAY_SECONDS)

    async def _broadcast_stats(self):
        stats = await get_dashboard_stats(self.db)
        await self.ws.broadcast({"event": "stats_update", **stats})

    async def _slack_enabled(self) -> bool:
        doc = await self.db.settings_coll.find_one({"_id": "slack"})
        if doc is None:
            return True
        return bool(doc.get("enabled", True))

    async def _send_slack_notification(self, repo_full: str, issue_doc: dict, weight: float):
        """Send a Slack webhook notification for a new maintainer issue."""
        try:
            text = (
                f":rotating_light: *New maintainer issue* in `{repo_full}` (weight {weight:.2f})\n"
                f"*<{issue_doc['html_url']}|#{issue_doc['number']}: {issue_doc['title']}>*\n"
                f"Author: `{issue_doc['author']}` ({issue_doc.get('author_role', 'NONE')})"
            )
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    self.settings.slack_webhook_url,
                    json={"text": text},
                )
                if resp.status_code != 200:
                    logger.warning("Slack webhook returned %d: %s", resp.status_code, resp.text)
        except Exception:
            logger.exception("Failed to send Slack notification")

    async def _slow_metadata_cycle(self):
        """Update repo stars/forks/description for 30 repos. Uses first client."""
        gh = self.gh_clients[0]
        batch_size = 30
        start = self._metadata_index
        end = min(start + batch_size, len(self._all_repos))
        batch = self._all_repos[start:end]

        if end >= len(self._all_repos):
            self._metadata_index = 0
        else:
            self._metadata_index = end

        updated = 0
        for repo in batch:
            if gh.is_rate_limited():
                break
            gh_data = await gh.get_repo(repo["full_name"])
            if gh_data:
                await update_repo_metadata(self.db, repo["full_name"], gh_data)
                updated += 1

        if updated:
            logger.info("Metadata refresh: updated %d repos (%d-%d)", updated, start, end)
