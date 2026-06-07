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
from pathlib import Path

from config import Settings
from devin_client import DevinClient
from github_client import (
    LABEL_GENERATED,
    LABEL_REMEDIATE,
    GitHubClient,
)
from models import Issue, Stage, TriageReport

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
            tags=["enablement-console", "triage"],
        )
        issue.triage_session_id = session["session_id"]
        issue.triage_session_url = session.get("url")
        issue.state = Stage.TRIAGING
        issue.failure_reason = None
        self.store.upsert_issue(issue)
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
            tags=["enablement-console", "remediation"],
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
            tags=["enablement-console", "review"],
        )
        issue.review_session_id = session["session_id"]
        issue.review_session_url = session.get("url")
        issue.state = Stage.REVIEWING
        issue.failure_reason = None
        self.store.upsert_issue(issue)
        return issue

    # ----- polling ---------------------------------------------------------
    async def poll_once(self) -> None:
        """Advance every in-flight issue based on its session status."""
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
        issue.acus_consumed = float(session.get("acus_consumed") or issue.acus_consumed)
        status = session.get("status")

        if status in ("error", "suspended"):
            issue.state = Stage.NEEDS_ATTENTION
            issue.failure_reason = session.get("status_detail") or status
            self.store.upsert_issue(issue)
            return
        if status == "exit":
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

    async def _on_remediation_done(self, issue: Issue, session: dict) -> None:
        prs = session.get("pull_requests") or []
        if prs:
            issue.pr_url = prs[0].get("pr_url")
            issue.pr_state = prs[0].get("pr_state")
            issue.state = Stage.PR_OPEN
            self.store.upsert_issue(issue)
            await self._safe_add_label_pr(issue)
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

    async def _safe_add_label_pr(self, issue: Issue) -> None:
        # PR labels could be applied here via the GitHub PR API; the remediation
        # prompt already instructs Devin to self-apply `devin-generated`.
        logger.info("PR opened for #%s, expected label: %s", issue.github_issue_num, LABEL_GENERATED)
