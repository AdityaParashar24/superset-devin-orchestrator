"""Domain models and enums for the Devin Orchestrator."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Stage(str, Enum):
    """Pipeline stages an issue moves through."""

    NEW = "new"
    TRIAGING = "triaging"
    TRIAGED = "triaged"
    APPROVED = "approved"
    REMEDIATING = "remediating"
    PR_OPEN = "pr_open"
    NEEDS_ATTENTION = "needs_attention"


class ReadinessLevel(str, Enum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class TriageReport(BaseModel):
    """Structured output we require from the triage Devin session."""

    readiness_score: int = Field(ge=0, le=100)
    readiness_level: ReadinessLevel
    recommendation: str
    likely_files: list[str] = Field(default_factory=list)
    suggested_validation: str = ""
    risk_notes: str = ""
    remediation_prompt: str = ""
    clarification_needed: str = ""


class Issue(BaseModel):
    """An issue tracked through the remediation pipeline."""

    github_issue_num: int
    title: str
    body: str = ""
    state: Stage = Stage.NEW

    readiness_score: int | None = None
    readiness_level: str | None = None
    recommendation: str | None = None
    likely_files: list[str] = Field(default_factory=list)
    suggested_validation: str | None = None
    risk_notes: str | None = None
    remediation_prompt: str | None = None
    clarification_needed: str | None = None
    triage_session_id: str | None = None
    triage_session_url: str | None = None
    remediation_session_id: str | None = None
    remediation_session_url: str | None = None
    pr_url: str | None = None
    pr_state: str | None = None
    failure_reason: str | None = None

    created_at: str | None = None
    updated_at: str | None = None


class CreateIssueRequest(BaseModel):
    github_issue_num: int
