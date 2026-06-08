"""Thin async wrapper around the Devin REST API (v3).

Only the endpoints needed by the orchestrator:
  * POST /organizations/{org}/sessions          -> create a session
  * GET  /organizations/{org}/sessions/{id}     -> poll status, PR, structured output
  * GET  /organizations/{org}/sessions          -> list sessions (for discovery)
  * DELETE /organizations/{org}/sessions/{id}   -> stop a session
"""

from __future__ import annotations

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

        V3 does not support server-side tag filtering, so we fetch all
        sessions and filter client-side. The V3 response shape is
        ``{"items": [...]}``.
        """
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(
                f"{self.base}/organizations/{self.org_id}/sessions",
                headers=self._headers,
            )
            resp.raise_for_status()
            data = resp.json()
        all_sessions = data.get("items", [])
        if not tags:
            return all_sessions
        tag_set = set(tags)
        return [s for s in all_sessions if tag_set.issubset(set(s.get("tags") or []))]

    async def stop_session(self, session_id: str) -> None:
        """Stop a running session via DELETE (session ID needs devin- prefix)."""
        devin_id = session_id if session_id.startswith("devin-") else f"devin-{session_id}"
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.delete(
                f"{self.base}/organizations/{self.org_id}/sessions/{devin_id}",
                headers=self._headers,
            )
            resp.raise_for_status()
