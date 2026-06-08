"""Core orchestration: turns GitHub issues into triage -> remediation -> review.

The orchestrator is a small state machine. Each `start_*` method launches a Devin
session for one role and records the session on the issue. A background poll loop
advances issues whenever their in-flight session finishes.

Design choices worth noting:
  * The triage session is forced to return strict JSON via `structured_output_schema`.
  * The PR is read directly off the remediation session's `pull_requests[]` — we do
    not scrape GitHub for it.
  * Devin recommends, a human approves (applies `devin-remediate` / clicks Approve),
    Devin executes, Devin self-reviews, a human merges.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

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
LABEL_REVIEWED = "devin-reviewed"

logger = logging.getLogger("orchestrator")

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

# JSON Schema (Draft 7) the triage session must satisfy.
TRIAGE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "readiness_score": {"type": "integer", "minimum": 0, "maximum": 100},
        "readiness_level": {"type": "string", "enum": ["High", "Medium", "Low"]},
        "recommendation": {
            "type": "string",
            "enum": ["Proceed", "Needs human clarification", "Not suitable"],
        },
        "likely_files": {"type": "array", "items": {"type": "string"}},
        "suggested_validation": {"type": "string"},
        "risk_notes": {"type": "string"},
        "remediation_prompt": {"type": "string"},
        "clarification_needed": {"type": "string"},
    },
    "required": [
        "readiness_score",
        "readiness_level",
        "recommendation",
        "likely_files",
        "suggested_validation",
        "risk_notes",
        "remediation_prompt",
        "clarification_needed",
    ],
}

REVIEW_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "verdict": {
            "type": "string",
            "enum": ["Approve", "Needs changes", "Needs human review"],
        },
        "concerns": {"type": "string"},
        "follow_ups": {"type": "string"},
    },
    "required": ["verdict", "concerns", "follow_ups"],
}

class StageError(RuntimeError):
    """Raised when an action is invalid for the issue's current stage."""


def _load_prompt(name: str) -> str:
    return (_PROMPTS_DIR / name).read_text(encoding="utf-8")


def _triage_report_text(issue: Issue) -> str:
    return (
        f"readiness_score: {issue.readiness_score}\n"
        f"readiness_level: {issue.readiness_level}\n"
        f"recommendation: {issue.recommendation}\n"
        f"likely_files: {', '.join(issue.likely_files)}\n"
        f"suggested_validation: {issue.suggested_validation}\n"
        f"risk_notes: {issue.risk_notes}\n"
        f"remediation_prompt: {issue.remediation_prompt}\n"
        f"clarification_needed: {issue.clarification_needed}\n"
    )


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
                title = title or gh.get("title", f"Issue #{num}")
                body = body or (gh.get("body") or "")
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not fetch issue %s from GitHub: %s", num, exc)
                title = title or f"Issue #{num}"
        issue = existing or Issue(github_issue_num=num, title=title, body=body)
        issue.title = title or issue.title
        issue.body = body or issue.body
        return self.store.upsert_issue(issue)

    # ----- stage: triage ---------------------------------------------------
    async def start_triage(self, num: int) -> Issue:
        issue = await self.ingest_issue(num)
        # Reset prior triage data (supports re-triage)
        issue.readiness_score = None
        issue.readiness_level = None
        issue.recommendation = None
        issue.likely_files = []
        issue.suggested_validation = None
        issue.risk_notes = None
        issue.remediation_prompt = None
        issue.clarification_needed = None
        prompt = _load_prompt("triage.md").format(
            repo=self.repo,
            issue_number=issue.github_issue_num,
            issue_title=issue.title,
            issue_body=issue.body or "(no description provided)",
        )
        session = await self.devin.create_session(
            prompt=prompt,
            repos=[self.repo],
            title=f"Triage: Superset issue #{num}",
            max_acu_limit=self.settings.triage_max_acu,
            structured_output_schema=TRIAGE_SCHEMA,
            tags=["enablement-console", "triage", f"issue-{num}"],
        )
        issue.triage_session_id = session["session_id"]
        issue.triage_session_url = session.get("url")
        issue.state = Stage.TRIAGING
        issue.failure_reason = None
        self.store.upsert_issue(issue)
        await self._safe_add_label(num, LABEL_TRIAGE)
        await self._safe_comment(
            num, f"Devin triage session started: {issue.triage_session_url}"
        )
        return issue

    # ----- stage: remediation (human approval gate) ------------------------
    async def start_remediation(self, num: int, add_label: bool = True) -> Issue:
        issue = self.store.get_issue(num)
        if issue is None:
            raise StageError(f"Issue #{num} is not tracked yet.")
        if issue.state not in (Stage.TRIAGED, Stage.APPROVED):
            raise StageError(
                f"Issue #{num} must be TRIAGED before remediation (is {issue.state})."
            )

        # Re-fetch issue with comments so remediation sees human clarification
        try:
            gh = await self.github.get_issue_with_comments(num)
            issue.body = gh.get("body") or issue.body
            self.store.upsert_issue(issue)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not re-fetch issue #%s with comments: %s", num, exc)

        if add_label:
            # Approval is recorded as the devin-remediate label on the issue.
            await self._safe_add_label(num, LABEL_REMEDIATE)

        prompt = _load_prompt("remediation.md").format(
            repo=self.repo,
            issue_number=issue.github_issue_num,
            issue_title=issue.title,
            issue_body=issue.body or "(no description provided)",
            triage_report=_triage_report_text(issue),
            suggested_validation=issue.suggested_validation or "the project's test suite",
        )
        session = await self.devin.create_session(
            prompt=prompt,
            repos=[self.repo],
            title=f"Remediate: Superset issue #{num}",
            max_acu_limit=self.settings.remediation_max_acu,
            tags=["enablement-console", "remediation", f"issue-{num}"],
        )
        issue.remediation_session_id = session["session_id"]
        issue.remediation_session_url = session.get("url")
        issue.state = Stage.REMEDIATING
        issue.failure_reason = None
        self.store.upsert_issue(issue)
        await self._safe_comment(
            num, f"Devin remediation session started: {issue.remediation_session_url}"
        )
        return issue

    # ----- stage: review ---------------------------------------------------
    async def start_review(self, num: int) -> Issue:
        issue = self.store.get_issue(num)
        if issue is None:
            raise StageError(f"Issue #{num} is not tracked yet.")
        if not issue.pr_url:
            raise StageError(f"Issue #{num} has no PR to review yet.")

        prompt = _load_prompt("review.md").format(
            repo=self.repo,
            pr_url=issue.pr_url,
            issue_number=issue.github_issue_num,
            issue_title=issue.title,
            triage_report=_triage_report_text(issue),
        )
        session = await self.devin.create_session(
            prompt=prompt,
            repos=[self.repo],
            title=f"Review: Superset issue #{num}",
            max_acu_limit=self.settings.review_max_acu,
            structured_output_schema=REVIEW_SCHEMA,
            tags=["enablement-console", "review", f"issue-{issue.github_issue_num}"],
        )
        issue.review_session_id = session["session_id"]
        issue.review_session_url = session.get("url")
        issue.state = Stage.REVIEWING
        issue.failure_reason = None
        self.store.upsert_issue(issue)
        return issue

    # ----- polling ---------------------------------------------------------
    async def poll_once(self) -> None:
        """Discover externally-started sessions, then advance in-flight issues."""
        await self.discover_sessions()
        for issue in self.store.list_in_flight():
            try:
                await self._advance(issue)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Error advancing issue #%s: %s", issue.github_issue_num, exc)

    async def _advance(self, issue: Issue) -> None:
        session_id, handler = {
            Stage.TRIAGING: (issue.triage_session_id, self._on_triage_done),
            Stage.REMEDIATING: (issue.remediation_session_id, self._on_remediation_done),
            Stage.REVIEWING: (issue.review_session_id, self._on_review_done),
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
            logger.info("Session %s produced output while running; stopping.", session_id)
            try:
                await self.devin.stop_session(session_id)
            except Exception:  # noqa: BLE001
                logger.warning("Could not stop session %s", session_id)
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
        # Post triage report + label on GitHub
        await self._safe_add_label(issue.github_issue_num, LABEL_TRIAGED)
        if issue.state == Stage.TRIAGED:
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
            await self._safe_add_label(issue.github_issue_num, LABEL_PR_OPEN)
            # Auto-kick the review session once a PR exists.
            await self.start_review(issue.github_issue_num)
        else:
            issue.state = Stage.NEEDS_ATTENTION
            issue.failure_reason = "Remediation session finished without opening a PR."
            self.store.upsert_issue(issue)

    async def _on_review_done(self, issue: Issue, session: dict) -> None:
        out = session.get("structured_output") or {}
        issue.review_verdict = out.get("verdict", "Needs human review")
        issue.state = Stage.REVIEWED
        self.store.upsert_issue(issue)
        # Post review verdict + label on GitHub
        await self._safe_add_label(issue.github_issue_num, LABEL_REVIEWED)
        comment = f"### Review Verdict: {issue.review_verdict}\n\n"
        concerns = out.get("concerns", "")
        follow_ups = out.get("follow_ups", "")
        if concerns and concerns != "None":
            comment += f"**Concerns:** {concerns}\n\n"
        if follow_ups and follow_ups != "None":
            comment += f"**Follow-ups:** {follow_ups}\n"
        await self._safe_comment(issue.github_issue_num, comment)

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

    # ----- session discovery (for label-triggered sessions) ----------------
    async def discover_sessions(self) -> None:
        """Find Devin sessions started externally (e.g. by a GitHub Action).

        Lists sessions tagged 'enablement-console' and matches them to tracked
        issues via 'issue-N' tags. Any session not already recorded on an issue
        is adopted into the state machine.
        """
        try:
            sessions = await self.devin.list_sessions(tags=["enablement-console"])
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not list Devin sessions: %s", exc)
            return

        known_sids = set()
        for issue in self.store.list_issues():
            for sid in (issue.triage_session_id, issue.remediation_session_id, issue.review_session_id):
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
            is_review = "review" in tags

            issue = self.store.get_issue(issue_num)
            if issue is None:
                # Auto-ingest the issue so it appears on the dashboard
                try:
                    issue = await self.ingest_issue(issue_num)
                except Exception:  # noqa: BLE001
                    continue

            url = s.get("url", f"https://app.devin.ai/sessions/{sid}")

            if is_triage and not issue.triage_session_id:
                issue.triage_session_id = sid
                issue.triage_session_url = url
                if issue.state == Stage.NEW:
                    issue.state = Stage.TRIAGING
                self.store.upsert_issue(issue)
                logger.info("Discovered triage session %s for issue #%s", sid, issue_num)
            elif is_remediation and not issue.remediation_session_id:
                issue.remediation_session_id = sid
                issue.remediation_session_url = url
                if issue.state in (Stage.TRIAGED, Stage.APPROVED):
                    issue.state = Stage.REMEDIATING
                self.store.upsert_issue(issue)
                logger.info("Discovered remediation session %s for issue #%s", sid, issue_num)
            elif is_review and not issue.review_session_id:
                issue.review_session_id = sid
                issue.review_session_url = url
                if issue.state == Stage.PR_OPEN:
                    issue.state = Stage.REVIEWING
                self.store.upsert_issue(issue)
                logger.info("Discovered review session %s for issue #%s", sid, issue_num)

    @staticmethod
    def _session_looks_done(issue: Issue, session: dict) -> bool:
        """Check if a session has produced its expected output even if still 'running'."""
        if issue.state == Stage.TRIAGING:
            return bool(session.get("structured_output"))
        if issue.state == Stage.REMEDIATING:
            return bool(session.get("pull_requests"))
        if issue.state == Stage.REVIEWING:
            return bool(session.get("structured_output"))
        return False