"""Configuration loaded from environment variables / .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the repo root (one level up from backend/)
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ENV_PATH)

BASE_DIR = Path(__file__).resolve().parent


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
    triage_max_acu: int
    remediation_max_acu: int
    review_max_acu: int
    demo_mode: bool

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
        db_path=os.getenv("DB_PATH", str(BASE_DIR / "enablement.db")),
        poll_interval_seconds=int(os.getenv("POLL_INTERVAL_SECONDS", "20")),
        triage_max_acu=int(os.getenv("TRIAGE_MAX_ACU", "5")),
        remediation_max_acu=int(os.getenv("REMEDIATION_MAX_ACU", "30")),
        review_max_acu=int(os.getenv("REVIEW_MAX_ACU", "10")),
        # DEMO_MODE simulates Devin/GitHub so the dashboard works without credentials.
        demo_mode=os.getenv("DEMO_MODE", "false").lower() in ("1", "true", "yes"),
    )


settings = get_settings()
