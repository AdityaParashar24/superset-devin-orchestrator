"""Seed the store with three demo issues at different pipeline stages.

Useful for demos/screenshots so the dashboard shows a full pipeline without having
to run every Devin session live. Run:  python seed.py
"""

from __future__ import annotations

from config import settings
from models import Issue, Stage
from store import Store

REPO = settings.github_repo or "AdityaParashar24/superset"


def _pr(num: int) -> str:
    return f"https://github.com/{REPO}/pull/{num}"


def _session(slug: str) -> str:
    return f"https://app.devin.ai/sessions/devin-demo{slug}"


DEMO_ISSUES = [
    # Issue fully through the pipeline: PR opened + reviewed.
    Issue(
        github_issue_num=12,
        title="pandas_postprocessing rank() fails silently on single-row/column data",
        body="When a heatmap applies rank normalization and the filtered data leaves "
        "only one row/column, rank.py returns NaN with no meaningful error.",
        state=Stage.REVIEWED,
        readiness_score=86,
        readiness_level="High",
        recommendation="Proceed",
        likely_files=[
            "superset/utils/pandas_postprocessing/rank.py",
            "tests/unit_tests/pandas_postprocessing/",
        ],
        suggested_validation="pytest tests/unit_tests/pandas_postprocessing/",
        risk_notes="Rank behavior is shared across post-processing paths; verify other "
        "charts are unaffected.",
        remediation_prompt="Handle the single-row/column rank edge case in rank.py and "
        "add a regression test.",
        triage_session_id="devin-demo12a",
        triage_session_url=_session("12a"),
        remediation_session_id="devin-demo12b",
        remediation_session_url=_session("12b"),
        review_session_id="devin-demo12c",
        review_session_url=_session("12c"),
        pr_url=_pr(101),
        pr_state="open",
        review_verdict="Needs human review",
        acus_consumed=18.4,
    ),
    # Issue mid-flight: remediation produced a PR, review still running.
    Issue(
        github_issue_num=13,
        title="ExportTagsCommand inconsistent with ExportModelsCommand validation",
        body="superset/commands/tag/export.py skips the _validate() step other export "
        "commands perform, so invalid/orphaned tags can be exported silently.",
        state=Stage.PR_OPEN,
        readiness_score=72,
        readiness_level="Medium",
        recommendation="Proceed",
        likely_files=[
            "superset/commands/tag/export.py",
            "tests/unit_tests/tags/",
        ],
        suggested_validation="pytest tests/unit_tests/tags/",
        risk_notes="Adding validation may surface previously-silent failures in exports.",
        remediation_prompt="Add a _validate() step to ExportTagsCommand consistent with "
        "other export commands; add a unit test.",
        triage_session_id="devin-demo13a",
        triage_session_url=_session("13a"),
        remediation_session_id="devin-demo13b",
        remediation_session_url=_session("13b"),
        pr_url=_pr(102),
        pr_state="open",
        acus_consumed=9.1,
    ),
    # Issue waiting at the human approval gate.
    Issue(
        github_issue_num=14,
        title="Re-enable or document skipped tests in test_ocient.py",
        body="tests/unit_tests/db_engine_specs/test_ocient.py has skipped tests that "
        "were never re-enabled. Investigate and re-enable or document the skip reason.",
        state=Stage.TRIAGED,
        readiness_score=64,
        readiness_level="Medium",
        recommendation="Needs human clarification",
        likely_files=["tests/unit_tests/db_engine_specs/test_ocient.py"],
        suggested_validation="pytest tests/unit_tests/db_engine_specs/test_ocient.py",
        risk_notes="May require the Ocient driver which is not installed in CI; could "
        "stay skipped with a documented reason.",
        remediation_prompt="Investigate the skipped Ocient tests; re-enable if the "
        "blocker is resolved, otherwise add a clear skip reason.",
        triage_session_id="devin-demo14a",
        triage_session_url=_session("14a"),
        acus_consumed=2.3,
    ),
]


def main() -> None:
    store = Store(settings.db_path)
    store.delete_all()
    for issue in DEMO_ISSUES:
        store.upsert_issue(issue)
    print(f"Seeded {len(DEMO_ISSUES)} demo issues into {settings.db_path}")


if __name__ == "__main__":
    main()
