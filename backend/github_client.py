"""Minimal GitHub REST wrapper for the orchestrator.

Responsibilities are intentionally narrow: read an issue, add/remove labels, and
post a comment linking the Devin session. PR detection is NOT done here — that
comes straight off the Devin session object (session.pull_requests[]).

When DEMO_MODE is on, a no-op fake is returned so the console runs credential-free.
"""

from __future__ import annotations

from typing import Any

import httpx

from config import Settings

LABEL_TRIAGE = "devin-triage"
LABEL_REMEDIATE = "devin-remediate"
LABEL_GENERATED = "devin-generated"


class GitHubClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.repo = settings.github_repo
        self.base = "https://api.github.com"

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def get_issue(self, num: int) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self.base}/repos/{self.repo}/issues/{num}",
                headers=self._headers,
            )
            resp.raise_for_status()
            return resp.json()

    async def get_issue_with_comments(self, num: int) -> dict[str, Any]:
        """Fetch issue body + all comments, merged into a single body string."""
        issue = await self.get_issue(num)
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self.base}/repos/{self.repo}/issues/{num}/comments",
                headers=self._headers,
            )
            resp.raise_for_status()
            comments = resp.json()
        if comments:
            comment_text = "\n\n".join(
                f"**Comment by {c['user']['login']}:**\n{c['body']}"
                for c in comments
            )
            issue["body"] = (issue.get("body") or "") + "\n\n---\n## Comments\n" + comment_text
        return issue

    async def add_label(self, num: int, label: str) -> None:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.base}/repos/{self.repo}/issues/{num}/labels",
                headers=self._headers,
                json={"labels": [label]},
            )
            resp.raise_for_status()

    async def comment(self, num: int, body: str) -> None:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.base}/repos/{self.repo}/issues/{num}/comments",
                headers=self._headers,
                json={"body": body},
            )
            resp.raise_for_status()


class FakeGitHubClient(GitHubClient):
    """No-op GitHub client for DEMO_MODE."""

    async def get_issue(self, num: int) -> dict[str, Any]:
        return {
            "number": num,
            "title": f"Demo issue #{num}",
            "body": "Demo issue body (DEMO_MODE).",
        }

    async def get_issue_with_comments(self, num: int) -> dict[str, Any]:  # noqa: D102
        return await self.get_issue(num)

    async def add_label(self, num: int, label: str) -> None:  # noqa: D102
        return None

    async def comment(self, num: int, body: str) -> None:  # noqa: D102
        return None


def build_github_client(settings: Settings) -> GitHubClient:
    if settings.demo_mode:
        return FakeGitHubClient(settings)
    return GitHubClient(settings)
