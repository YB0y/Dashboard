import os
import json
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class Settings:
    github_pats: list[str] = field(default_factory=list)
    polling_interval: int = 60
    db_url: str = ""
    host: str = "0.0.0.0"
    port: int = 8000
    repos_config_path: str = "./repos.json"
    slack_webhook_url: str = ""

    @property
    def github_pat(self) -> str:
        """Backward compat: return the first PAT."""
        return self.github_pats[0] if self.github_pats else ""

    @classmethod
    def from_env(cls) -> "Settings":
        # Collect all GITHUB_PAT, GITHUB_PAT_2, GITHUB_PAT_3, ... env vars
        pats: list[str] = []
        first = os.getenv("GITHUB_PAT", "")
        if first:
            pats.append(first)
        for i in range(2, 20):
            pat = os.getenv(f"GITHUB_PAT_{i}", "")
            if pat:
                pats.append(pat)

        return cls(
            github_pats=pats,
            polling_interval=int(os.getenv("POLLING_INTERVAL_SECONDS", "60")),
            db_url=os.getenv("DB", ""),
            host=os.getenv("HOST", "0.0.0.0"),
            port=int(os.getenv("PORT", "8000")),
            slack_webhook_url=os.getenv("SLACK_WEBHOOK_URL", ""),
        )

    def load_repos(self) -> dict:
        """Load repos.json - format: {"owner/repo": {"weight": 10.0}}"""
        config_path = Path(self.repos_config_path)
        if not config_path.exists():
            return {}
        with open(config_path, "r") as f:
            return json.load(f)
