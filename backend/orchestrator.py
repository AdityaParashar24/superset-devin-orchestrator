"""Core orchestration: turns GitHub issues into triage -> remediation -> PR.

The orchestrator is a small state machine. Each `start_*` method launches a Devin
session for one role and records the session on the issue. A background poll loop
advances issues whenever their in-flight session finishes.

Design choices worth noting:
  * The triage session is forced to return strict JSON via `structured_output_schema`.
  * The PR is read directly off the remediation session's `pull_requests[]` — we do
    not scrape GitHub for it.
  * Devin recommends, a human approves (applies `devin-remediate` / clicks Approve),
    Devin executes, Devin Review bot reviews, a human merges.
"""

from __future__ import annotations

import logging
import re

from config import Settings
from devin_client import DevinClient
from github_client import (
    LABEL_REMEDIATE,
    LABEL_TRIAGE,
    GitHubClient,
)
from models import Issue, Stage, TriageReport

LABEL_TRIAGED = "devin-triaged"
LABEL_PR_OPEN = "devin-pr-open"

logger = logging.getLogger("orchestrator")

class StageError(RuntimeError):
    """Raised when an action is invalid for the issue's current stage."""


class Orchestrator:
    def __init__(
        self,
        settings: Settings,
        store,  # avoid circular import; duck-typed Store
        devin: DevinClient,
        github: GitHubClient,
    ) -> None:
        self.settings = settings
        self.store = store
        self.devin = devin
        self.github = github
        self.repo = settings.github_repo or "owner/repo"

    # ----- ingestion -------------------------------------------------------
    async def ingest_issue(self, num: int, title: str = "", body: str = "") -> Issue:
        """Create/refresh a tracked issue, pulling details from GitHub if needed."""
        existing = self.store.get_issue(num)
        if not title or not body:
            try:
                gh = await self.github.get_issue(num)
                if "pull_request" in gh:
                    raise StageError(
                        f"#{num} is a pull request, not an issue."
                    )
                title = title or gh.get("title", f"Issue #{num}")
                body = body or (gh.get("body") or "")
            except StageError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not fetch issue %s from GitHub: %s", num, exc)
                title = title or f"Issue #{num}"
        issue = existing or Issue(github_issue_num=num, title=title, body=body)
        issue.title = title or issue.title
        issue.body = body or issue.body
        return self.store.upsert_issue(issue)

    # ----- stage: triage ---------------------------------------------------
    async def start_triage(self, num: int) -> Issue:
        """Add the devin-triage label; the GitHub Action creates the session.

        The backend's ``discover_sessions()`` poll loop will adopt the session
        once the Action starts it, and ``_advance()`` will process the result.
        """
        issue = await self.ingest_issue(num)
        if issue.state not in (Stage.NEW,):
            raise StageError(
                f"Issue #{num} must be NEW to start triage (is {issue.state})."
            )
        issue.state = Stage.TRIAGING
        issue.failure_reason = None
        self.store.upsert_issue(issue)
        await self._safe_add_label(num, LABEL_TRIAGE)
        return issue

    # ----- stage: remediation (human approval gate) ------------------------
    async def start_remediation(self, num: int) -> Issue:
        """Add the devin-remediate label; the GitHub Action creates the session.

        The backend's ``discover_sessions()`` poll loop will adopt the session
        once the Action starts it, and ``_advance()`` will process the result.
        """
        issue = self.store.get_issue(num)
        if issue is None:
            raise StageError(f"Issue #{num} is not tracked yet.")
        if issue.state not in (Stage.TRIAGED, Stage.APPROVED):
            raise StageError(
                f"Issue #{num} must be TRIAGED before remediation (is {issue.state})."
            )
        issue.state = Stage.REMEDIATING
        issue.failure_reason = None
        self.store.upsert_issue(issue)
        await self._safe_add_label(num, LABEL_REMEDIATE)
        return issue

    # ----- polling ---------------------------------------------------------
    async def poll_once(self) -> None:
        """Discover externally-started sessions, then advance in-flight issues.

        Loops until no issue changes state so that a fully-completed pipeline
        (triage → remediation) can catch up in a single poll cycle
        instead of requiring one cycle per stage.
        """
        max_rounds = 10  # safety cap to avoid infinite loops
        for _ in range(max_rounds):
            await self.discover_sessions()
            progressed = False
            for issue in self.store.list_in_flight():
                old_state = issue.state
                try:
                    await self._advance(issue)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Error advancing issue #%s: %s", issue.github_issue_num, exc)
                    continue
                refreshed = self.store.get_issue(issue.github_issue_num)
                if refreshed and refreshed.state != old_state:
                    progressed = True
            if not progressed:
                break

    async def _advance(self, issue: Issue) -> None:
        session_id, handler = {
            Stage.TRIAGING: (issue.triage_session_id, self._on_triage_done),
            Stage.REMEDIATING: (issue.remediation_session_id, self._on_remediation_done),
        }[issue.state]

        if not session_id:
            return
        session = await self.devin.get_session(session_id)
        status = session.get("status")

        if status in ("error", "suspended"):
            issue.state = Stage.NEEDS_ATTENTION
            issue.failure_reason = session.get("status_detail") or status
            self.store.upsert_issue(issue)
            return
        if status in ("exit", "blocked"):
            await handler(issue, session)
        elif status == "running" and self._session_looks_done(issue, session):
            await handler(issue, session)

    async def _on_triage_done(self, issue: Issue, session: dict) -> None:
        raw = session.get("structured_output") or {}
        try:
            report = TriageReport(**raw)
            issue.readiness_score = report.readiness_score
            issue.readiness_level = report.readiness_level.value
            issue.recommendation = report.recommendation
            issue.likely_files = report.likely_files
            issue.suggested_validation = report.suggested_validation
            issue.risk_notes = report.risk_notes
            issue.remediation_prompt = report.remediation_prompt
            issue.clarification_needed = report.clarification_needed
            issue.state = Stage.TRIAGED
        except Exception as exc:  # noqa: BLE001
            logger.warning("Triage output invalid for #%s: %s", issue.github_issue_num, exc)
            issue.state = Stage.NEEDS_ATTENTION
            issue.failure_reason = "Triage returned no/invalid structured output."
        self.store.upsert_issue(issue)
        # Post triage report + label on GitHub (skip if already posted)
        already_posted = await self._has_label(issue.github_issue_num, LABEL_TRIAGED)
        await self._safe_add_label(issue.github_issue_num, LABEL_TRIAGED)
        if issue.state == Stage.TRIAGED and not already_posted:
            comment = (
                f"### Triage Report\n\n"
                f"**Readiness:** {issue.readiness_level} ({issue.readiness_score}/100) "
                f"· {issue.recommendation}\n\n"
            )
            if issue.risk_notes:
                comment += f"**Risks:** {issue.risk_notes}\n\n"
            if issue.clarification_needed and issue.clarification_needed != "None":
                comment += f"**Clarification needed:**\n{issue.clarification_needed}\n\n"
            if issue.likely_files:
                comment += f"**Likely files:** {', '.join(issue.likely_files)}\n"
            await self._safe_comment(issue.github_issue_num, comment)

    async def _on_remediation_done(self, issue: Issue, session: dict) -> None:
        prs = session.get("pull_requests") or []
        if prs:
            issue.pr_url = prs[0].get("pr_url")
            issue.pr_state = prs[0].get("pr_state")
            issue.state = Stage.PR_OPEN
            self.store.upsert_issue(issue)
            if not await self._has_label(issue.github_issue_num, LABEL_PR_OPEN):
                await self._safe_add_label(issue.github_issue_num, LABEL_PR_OPEN)
        else:
            issue.state = Stage.NEEDS_ATTENTION
            issue.failure_reason = "Remediation session finished without opening a PR."
            self.store.upsert_issue(issue)

    # ----- helpers ---------------------------------------------------------
    async def _safe_comment(self, num: int, body: str) -> None:
        try:
            await self.github.comment(num, body)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not comment on issue #%s: %s", num, exc)

    async def _safe_add_label(self, num: int, label: str) -> None:
        try:
            await self.github.add_label(num, label)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not add label %s to #%s: %s", label, num, exc)

    async def _has_label(self, num: int, label: str) -> bool:
        """Check if a label is already on the issue (to avoid duplicate comments)."""
        try:
            return label in await self.github.get_labels(num)
        except Exception:  # noqa: BLE001
            return False

    # ----- session discovery (for label-triggered sessions) ----------------
    async def discover_sessions(self) -> None:
        """Find Devin sessions started externally (e.g. by a GitHub Action).

        Lists sessions tagged 'devin-orchestrator' and matches them to tracked
        issues via 'issue-N' tags. Any session not already recorded on an issue
        is adopted into the state machine.
        """
        try:
            sessions = await self.devin.list_sessions(tags=["devin-orchestrator"])
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not list Devin sessions: %s", exc)
            return

        known_sids = set()
        for issue in self.store.list_issues():
            for sid in (issue.triage_session_id, issue.remediation_session_id):
                if sid:
                    known_sids.add(sid)

        for s in sessions:
            sid = s.get("session_id", "")
            if sid in known_sids:
                continue
            tags = s.get("tags") or []
            issue_num = None
            for tag in tags:
                m = re.match(r"^issue-(\d+)$", tag)
                if m:
                    issue_num = int(m.group(1))
                    break
            if issue_num is None:
                continue

            is_triage = "triage" in tags
            is_remediation = "remediation" in tags

            issue = self.store.get_issue(issue_num)
            status = s.get("status", "")

            if issue is None:
                # Only auto-ingest from running sessions to avoid resurrecting
                # issues from old exited sessions on a fresh DB.
                if status not in ("running", "blocked"):
                    continue
                try:
                    issue = await self.ingest_issue(issue_num)
                except Exception:  # noqa: BLE001
                    continue

            url = s.get("url", f"https://app.devin.ai/sessions/{sid}")

            # Only adopt a session if the issue is in (or past) the
            # expected stage for that role.  This prevents a restart from
            # attaching remediation/review URLs to an issue still triaging.
            if is_triage and not issue.triage_session_id:
                issue.triage_session_id = sid
                issue.triage_session_url = url
                if issue.state == Stage.NEW:
                    issue.state = Stage.TRIAGING
                self.store.upsert_issue(issue)
            elif is_remediation and not issue.remediation_session_id and issue.state in (
                Stage.TRIAGED, Stage.APPROVED, Stage.REMEDIATING,
            ):
                issue.remediation_session_id = sid
                issue.remediation_session_url = url
                if issue.state in (Stage.TRIAGED, Stage.APPROVED):
                    issue.state = Stage.REMEDIATING
                self.store.upsert_issue(issue)

    @staticmethod
    def _session_looks_done(issue: Issue, session: dict) -> bool:
        """Check if a session has produced its expected output even if still 'running'."""
        if issue.state == Stage.TRIAGING:
            return bool(session.get("structured_output"))
        if issue.state == Stage.REMEDIATING:
            return bool(session.get("pull_requests"))
        return False