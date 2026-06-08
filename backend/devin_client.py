"""Thin async wrapper around the Devin REST API (v3).

Only two endpoints are needed for the orchestrator:
  * POST /organizations/{org}/sessions          -> create a session
  * GET  /organizations/{org}/sessions/{id}     -> poll status, PR, structured output

When DEMO_MODE is on, a fake in-memory implementation is used instead so the whole
console can be demoed without real credentials.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

import httpx

from config import Settings


class DevinClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base = settings.devin_api_base.rstrip("/")
        self.org_id = settings.devin_org_id

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.devin_api_key}",
            "Content-Type": "application/json",
        }

    async def create_session(
        self,
        prompt: str,
        repos: list[str],
        *,
        title: str | None = None,
        playbook_id: str | None = None,
        max_acu_limit: int | None = None,
        structured_output_schema: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"prompt": prompt, "repos": repos}
        if title:
            body["title"] = title
        if playbook_id:
            body["playbook_id"] = playbook_id
        if max_acu_limit:
            body["max_acu_limit"] = max_acu_limit
        if structured_output_schema:
            body["structured_output_schema"] = structured_output_schema
            body["structured_output_required"] = True
        if tags:
            body["tags"] = tags

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self.base}/organizations/{self.org_id}/sessions",
                headers=self._headers,
                json=body,
            )
            resp.raise_for_status()
            return resp.json()

    async def get_session(self, session_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(
                f"{self.base}/organizations/{self.org_id}/sessions/{session_id}",
                headers=self._headers,
            )
            resp.raise_for_status()
            return resp.json()

    async def list_sessions(self, tags: list[str] | None = None) -> list[dict[str, Any]]:
        """List sessions, optionally filtered by tags.

        V1 supports server-side tag filtering; V3 does not. We use the V1
        endpoint for listing because it natively supports ?tags= filtering
        and returns a ``sessions`` array.
        """
        params: dict[str, Any] = {"limit": 100}
        if tags:
            params["tags"] = tags  # V1 accepts tags as a list
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(
                "https://api.devin.ai/v1/sessions",
                headers=self._headers,
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
        return data.get("sessions", [])

    async def stop_session(self, session_id: str) -> None:
        """Stop a running session via DELETE (session ID needs devin- prefix)."""
        devin_id = session_id if session_id.startswith("devin-") else f"devin-{session_id}"
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.delete(
                f"{self.base}/organizations/{self.org_id}/sessions/{devin_id}",
                headers=self._headers,
            )
            resp.raise_for_status()


class FakeDevinClient(DevinClient):
    """In-memory simulator used when DEMO_MODE is enabled.

    Sessions start "running" and flip to "exit" after a short delay, producing a
    plausible structured triage report or a fake PR depending on the prompt.
    """

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self._sessions: dict[str, dict[str, Any]] = {}

    async def create_session(self, prompt: str, repos: list[str], **kwargs: Any) -> dict[str, Any]:
        await asyncio.sleep(0.1)
        sid = f"devin-{uuid.uuid4().hex[:12]}"
        is_triage = kwargs.get("structured_output_schema") is not None
        is_review = "reviewer" in prompt.lower() or "review the pr" in prompt.lower()
        kind = "triage" if is_triage else ("review" if is_review else "remediation")
        self._sessions[sid] = {
            "session_id": sid,
            "url": f"https://app.devin.ai/sessions/{sid}",
            "status": "running",
            "status_detail": "working",
            "pull_requests": [],
            "structured_output": None,
            "acus_consumed": 0.0,
            "tags": kwargs.get("tags", []),
            "_kind": kind,
            "_created": time.time(),
            "_repo": repos[0] if repos else "owner/repo",
        }
        return self._public(self._sessions[sid])

    async def get_session(self, session_id: str) -> dict[str, Any]:
        s = self._sessions.get(session_id)
        if s is None:
            raise httpx.HTTPStatusError("not found", request=None, response=None)  # type: ignore[arg-type]
        # Simulate completion ~5s after creation.
        if s["status"] == "running" and time.time() - s["_created"] > 5:
            s["status"] = "exit"
            s["status_detail"] = "finished"
            s["acus_consumed"] = round(2.5, 2)
            if s["_kind"] == "triage":
                s["structured_output"] = {
                    "readiness_score": 86,
                    "readiness_level": "High",
                    "recommendation": "Proceed",
                    "clarification_needed": "",
                    "likely_files": [
                        "superset/utils/pandas_postprocessing/rank.py",
                        "tests/unit_tests/pandas_postprocessing/",
                    ],
                    "suggested_validation": "pytest tests/unit_tests/pandas_postprocessing/",
                    "risk_notes": "Rank behavior is shared across post-processing paths; "
                    "verify other charts are unaffected.",
                    "remediation_prompt": "Fix the single-row/column rank normalization "
                    "edge case in rank.py; add a regression test.",
                }
            elif s["_kind"] == "remediation":
                s["pull_requests"] = [
                    {
                        "pr_url": f"https://github.com/{s['_repo']}/pull/{int(time.time()) % 900 + 100}",
                        "pr_state": "open",
                    }
                ]
            elif s["_kind"] == "review":
                s["structured_output"] = {"verdict": "Needs human review"}
        return self._public(s)

    async def list_sessions(self, tags: list[str] | None = None) -> list[dict[str, Any]]:
        return [self._public(s) for s in self._sessions.values()]

    async def stop_session(self, session_id: str) -> None:
        s = self._sessions.get(session_id)
        if s:
            s["status"] = "exit"

    @staticmethod
    def _public(s: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in s.items() if not k.startswith("_")}


def build_devin_client(settings: Settings) -> DevinClient:
    if settings.demo_mode:
        return FakeDevinClient(settings)
    return DevinClient(settings)
