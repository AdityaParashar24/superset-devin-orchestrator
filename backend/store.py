"""SQLite-backed persistence for tracked issues.

A single-file store keeps the take-home easy to run: no external database to
provision. All reads/writes go through this module so the rest of the code never
touches SQL directly.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from models import Issue, Stage

_SCHEMA = """
CREATE TABLE IF NOT EXISTS issues (
    github_issue_num        INTEGER PRIMARY KEY,
    title                   TEXT NOT NULL,
    body                    TEXT DEFAULT '',
    state                   TEXT NOT NULL DEFAULT 'new',
    readiness_score         INTEGER,
    readiness_level         TEXT,
    recommendation          TEXT,
    likely_files            TEXT DEFAULT '[]',
    suggested_validation    TEXT,
    risk_notes              TEXT,
    remediation_prompt      TEXT,
    clarification_needed    TEXT DEFAULT '',
    triage_session_id       TEXT,
    triage_session_url      TEXT,
    remediation_session_id  TEXT,
    remediation_session_url TEXT,
    review_session_id       TEXT,
    review_session_url      TEXT,
    pr_url                  TEXT,
    pr_state                TEXT,
    review_verdict          TEXT,
    failure_reason          TEXT,
    acus_consumed           REAL DEFAULT 0,
    created_at              TEXT,
    updated_at              TEXT
);
"""

_IN_FLIGHT = {Stage.TRIAGING.value, Stage.REMEDIATING.value, Stage.REVIEWING.value}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @staticmethod
    def _row_to_issue(row: sqlite3.Row) -> Issue:
        data: dict[str, Any] = dict(row)
        data["likely_files"] = json.loads(data.get("likely_files") or "[]")
        return Issue(**data)

    def upsert_issue(self, issue: Issue) -> Issue:
        existing = self.get_issue(issue.github_issue_num)
        if existing is None:
            issue.created_at = _now()
        else:
            issue.created_at = existing.created_at
        issue.updated_at = _now()

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO issues (
                    github_issue_num, title, body, state, readiness_score,
                    readiness_level, recommendation, likely_files, suggested_validation,
                    risk_notes, remediation_prompt, clarification_needed, triage_session_id, triage_session_url,
                    remediation_session_id, remediation_session_url, review_session_id,
                    review_session_url, pr_url, pr_state, review_verdict, failure_reason,
                    acus_consumed, created_at, updated_at
                ) VALUES (
                    :github_issue_num, :title, :body, :state, :readiness_score,
                    :readiness_level, :recommendation, :likely_files, :suggested_validation,
                    :risk_notes, :remediation_prompt, :clarification_needed, :triage_session_id, :triage_session_url,
                    :remediation_session_id, :remediation_session_url, :review_session_id,
                    :review_session_url, :pr_url, :pr_state, :review_verdict, :failure_reason,
                    :acus_consumed, :created_at, :updated_at
                )
                ON CONFLICT(github_issue_num) DO UPDATE SET
                    title=excluded.title,
                    body=excluded.body,
                    state=excluded.state,
                    readiness_score=excluded.readiness_score,
                    readiness_level=excluded.readiness_level,
                    recommendation=excluded.recommendation,
                    likely_files=excluded.likely_files,
                    suggested_validation=excluded.suggested_validation,
                    risk_notes=excluded.risk_notes,
                    remediation_prompt=excluded.remediation_prompt,
                    clarification_needed=excluded.clarification_needed,
                    triage_session_id=excluded.triage_session_id,
                    triage_session_url=excluded.triage_session_url,
                    remediation_session_id=excluded.remediation_session_id,
                    remediation_session_url=excluded.remediation_session_url,
                    review_session_id=excluded.review_session_id,
                    review_session_url=excluded.review_session_url,
                    pr_url=excluded.pr_url,
                    pr_state=excluded.pr_state,
                    review_verdict=excluded.review_verdict,
                    failure_reason=excluded.failure_reason,
                    acus_consumed=excluded.acus_consumed,
                    updated_at=excluded.updated_at
                """,
                {**issue.model_dump(), "likely_files": json.dumps(issue.likely_files)},
            )
        return issue

    def get_issue(self, num: int) -> Issue | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM issues WHERE github_issue_num = ?", (num,)
            ).fetchone()
        return self._row_to_issue(row) if row else None

    def list_issues(self) -> list[Issue]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM issues ORDER BY github_issue_num"
            ).fetchall()
        return [self._row_to_issue(r) for r in rows]

    def list_in_flight(self) -> list[Issue]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM issues WHERE state IN (?, ?, ?)",
                tuple(_IN_FLIGHT),
            ).fetchall()
        return [self._row_to_issue(r) for r in rows]

    def delete_all(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM issues")
