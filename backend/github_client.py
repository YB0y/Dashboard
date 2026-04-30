import httpx
import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# GitHub Search API caps at 1000 results total, 100 per page
MAX_SEARCH_PAGES = 10


class GitHubClient:
    def __init__(self, pat: str):
        self.headers = {
            "Authorization": f"Bearer {pat}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        self._client = httpx.AsyncClient(
            base_url="https://api.github.com",
            headers=self.headers,
            timeout=30.0,
            follow_redirects=True,
        )
        # REST API rate limit (5000/hr)
        self.rate_limit_remaining: int = 5000
        self.rate_limit_reset: datetime | None = None
        # Search API rate limit (30/min) - tracked separately
        self.search_remaining: int = 30
        self.search_reset: datetime | None = None

    async def close(self):
        await self._client.aclose()

    def _update_rate_limit(self, response: httpx.Response):
        self.rate_limit_remaining = int(
            response.headers.get("X-RateLimit-Remaining", 5000)
        )
        reset_ts = response.headers.get("X-RateLimit-Reset")
        if reset_ts:
            self.rate_limit_reset = datetime.fromtimestamp(int(reset_ts), tz=timezone.utc)

    def _update_search_limit(self, response: httpx.Response):
        self.search_remaining = int(
            response.headers.get("X-RateLimit-Remaining", 30)
        )
        reset_ts = response.headers.get("X-RateLimit-Reset")
        if reset_ts:
            self.search_reset = datetime.fromtimestamp(int(reset_ts), tz=timezone.utc)

    def is_rate_limited(self) -> bool:
        if self.rate_limit_remaining <= 10:
            if self.rate_limit_reset and datetime.now(timezone.utc) < self.rate_limit_reset:
                return True
        return False

    async def _wait_for_search_limit(self):
        """Wait until search rate limit resets if needed."""
        if self.search_remaining <= 1 and self.search_reset:
            wait = (self.search_reset - datetime.now(timezone.utc)).total_seconds()
            if wait > 0:
                logger.info("Search rate limited, waiting %.0fs...", wait)
                await asyncio.sleep(min(wait + 1, 65))

    async def search_issues_batch(
        self, repo_names: list[str], since: str, per_page: int = 100
    ) -> list[dict]:
        """
        Use GitHub Search API to find new issues across multiple repos.
        Paginates through ALL pages to never miss results.
        Retries on 422 by splitting the batch in half.
        Waits and retries on 403 (rate limit).
        """
        await self._wait_for_search_limit()

        repo_qualifiers = " ".join(f"repo:{name}" for name in repo_names)
        q = f"is:issue is:open created:>={since} {repo_qualifiers}"

        all_items: list[dict] = []

        for page in range(1, MAX_SEARCH_PAGES + 1):
            await self._wait_for_search_limit()

            response = await self._client.get(
                "/search/issues",
                params={
                    "q": q,
                    "sort": "created",
                    "order": "desc",
                    "per_page": per_page,
                    "page": page,
                },
            )
            self._update_search_limit(response)

            if response.status_code == 200:
                data = response.json()
                items = data.get("items", [])
                total_count = data.get("total_count", 0)
                all_items.extend(items)

                # Stop if we've fetched everything
                if len(all_items) >= total_count or len(items) < per_page:
                    break

            elif response.status_code == 422:
                # Query too long — split batch in half and retry recursively
                if len(repo_names) <= 1:
                    logger.warning("422 even with single repo %s, skipping", repo_names)
                    return all_items
                mid = len(repo_names) // 2
                logger.info("422: splitting %d repos into two halves and retrying", len(repo_names))
                left = await self.search_issues_batch(repo_names[:mid], since, per_page)
                right = await self.search_issues_batch(repo_names[mid:], since, per_page)
                all_items.extend(left)
                all_items.extend(right)
                return all_items

            elif response.status_code == 403:
                # Rate limited — wait and retry this page
                logger.warning("Search 403 on page %d. Waiting for reset...", page)
                self.search_remaining = 0
                await self._wait_for_search_limit()
                # Retry same page — decrement loop counter won't work, so use recursion
                # But only for this page's remaining data
                remaining = await self._fetch_remaining_pages(q, page, per_page)
                all_items.extend(remaining)
                return all_items

            else:
                logger.error("Search API error: %d on page %d", response.status_code, page)
                break

        return all_items

    async def _fetch_remaining_pages(
        self, q: str, start_page: int, per_page: int
    ) -> list[dict]:
        """Continue fetching from start_page after a rate limit recovery."""
        items: list[dict] = []
        for page in range(start_page, MAX_SEARCH_PAGES + 1):
            await self._wait_for_search_limit()
            response = await self._client.get(
                "/search/issues",
                params={
                    "q": q,
                    "sort": "created",
                    "order": "desc",
                    "per_page": per_page,
                    "page": page,
                },
            )
            self._update_search_limit(response)

            if response.status_code == 200:
                data = response.json()
                page_items = data.get("items", [])
                total_count = data.get("total_count", 0)
                items.extend(page_items)
                if len(items) >= total_count or len(page_items) < per_page:
                    break
            elif response.status_code == 403:
                logger.warning("403 again on page %d, waiting...", page)
                self.search_remaining = 0
                await self._wait_for_search_limit()
                continue
            else:
                logger.error("Search API error: %d on page %d", response.status_code, page)
                break
        return items

    async def get_repo(self, full_name: str) -> dict | None:
        if self.is_rate_limited():
            return None
        response = await self._client.get(f"/repos/{full_name}")
        self._update_rate_limit(response)
        if response.status_code == 200:
            return response.json()
        return None

    async def get_issues(
        self, full_name: str, since: str | None = None, per_page: int = 30
    ) -> list[dict]:
        """Fallback: fetch issues for a single repo (used for initial load)."""
        if self.is_rate_limited():
            return []
        params: dict = {
            "state": "open",
            "sort": "created",
            "direction": "desc",
            "per_page": per_page,
            "page": 1,
        }
        if since:
            params["since"] = since
        response = await self._client.get(f"/repos/{full_name}/issues", params=params)
        self._update_rate_limit(response)
        if response.status_code == 200:
            items = response.json()
            return [i for i in items if "pull_request" not in i]
        return []

    async def get_all_open_issues(self, full_name: str, max_pages: int = 30) -> list[dict]:
        """Paginate ALL open issues (excludes PRs). Used for one-time full backfill.

        Each page hits the REST budget once. Stops at the first short page or max_pages.
        """
        all_items: list[dict] = []
        for page in range(1, max_pages + 1):
            if self.is_rate_limited():
                logger.warning("Rate limited mid-backfill of %s at page %d", full_name, page)
                break
            response = await self._client.get(
                f"/repos/{full_name}/issues",
                params={
                    "state": "open",
                    "sort": "created",
                    "direction": "desc",
                    "per_page": 100,
                    "page": page,
                },
            )
            self._update_rate_limit(response)
            if response.status_code != 200:
                logger.warning("Backfill %s page %d -> HTTP %d", full_name, page, response.status_code)
                break
            page_items = response.json()
            non_pr = [i for i in page_items if "pull_request" not in i]
            all_items.extend(non_pr)
            if len(page_items) < 100:
                break
        return all_items
