"""Configuration loaded from environment variables / .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the repo root (one level up from backend/)
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ENV_PATH)


@dataclass(frozen=True)
class Settings:
    """Runtime settings for the orchestrator backend."""

    devin_api_key: str
    devin_org_id: str
    devin_api_base: str
    github_token: str
    github_repo: str
    db_path: str
    poll_interval_seconds: int

    @property
    def configured(self) -> bool:
        """True when the live integrations have the credentials they need."""
        return bool(self.devin_api_key and self.devin_org_id and self.github_token)


def get_settings() -> Settings:
    """Build a Settings object from the current environment."""
    return Settings(
        devin_api_key=os.getenv("DEVIN_API_KEY", ""),
        devin_org_id=os.getenv("DEVIN_ORG_ID", ""),
        devin_api_base=os.getenv("DEVIN_API_BASE", "https://api.devin.ai/v3"),
        github_token=os.getenv("GITHUB_TOKEN", ""),
        github_repo=os.getenv("GITHUB_REPO", ""),
        db_path=os.getenv("DB_PATH", "orchestrator.db"),
        poll_interval_seconds=int(os.getenv("POLL_INTERVAL_SECONDS", "8")),
    )


settings = get_settings()
