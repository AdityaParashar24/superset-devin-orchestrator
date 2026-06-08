"""FastAPI entrypoint for the Superset Maintenance Enablement Console.

Exposes the orchestrator over HTTP and runs a background poll loop that advances
in-flight issues. The React frontend consumes these endpoints.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from devin_client import build_devin_client
from github_client import build_github_client
from models import CreateIssueRequest, Issue
from orchestrator import Orchestrator, StageError
from store import Store

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")

store = Store(settings.db_path)
devin = build_devin_client(settings)
github = build_github_client(settings)
orchestrator = Orchestrator(settings, store, devin, github)


async def _poll_loop() -> None:
    while True:
        try:
            await orchestrator.poll_once()
        except Exception:  # noqa: BLE001
            logger.exception("poll loop error")
        await asyncio.sleep(settings.poll_interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_poll_loop())
    logger.info(
        "Console started | demo_mode=%s | configured=%s | repo=%s",
        settings.demo_mode,
        settings.configured,
        settings.github_repo or "(unset)",
    )
    yield
    task.cancel()


app = FastAPI(title="Superset Maintenance Enablement Console", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----- read endpoints ------------------------------------------------------
@app.get("/api/health")
async def health() -> dict:
    return {
        "status": "ok",
        "demo_mode": settings.demo_mode,
        "configured": settings.configured,
        "repo": settings.github_repo,
    }


@app.get("/api/issues", response_model=list[Issue])
async def list_issues() -> list[Issue]:
    return store.list_issues()


@app.get("/api/issues/{num}", response_model=Issue)
async def get_issue(num: int) -> Issue:
    issue = store.get_issue(num)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not tracked")
    return issue


@app.get("/api/summary")
async def summary() -> dict:
    issues = store.list_issues()
    def count(*states: str) -> int:
        return sum(1 for i in issues if i.state in states)

    return {
        "total": len(issues),
        "triaged": count("triaged", "approved", "remediating", "pr_open", "reviewing", "reviewed"),
        "approved": count("approved", "remediating", "pr_open", "reviewing", "reviewed"),
        "prs_open": count("pr_open", "reviewing", "reviewed"),
        "reviewed": count("reviewed"),
        "needs_attention": count("needs_attention"),
    }


# ----- action endpoints ----------------------------------------------------
@app.post("/api/issues", response_model=Issue)
async def create_issue(req: CreateIssueRequest) -> Issue:
    return await orchestrator.ingest_issue(req.github_issue_num)


@app.post("/api/triage/{num}", response_model=Issue)
async def triage(num: int) -> Issue:
    try:
        return await orchestrator.start_triage(num)
    except StageError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/remediate/{num}", response_model=Issue)
async def remediate(num: int) -> Issue:
    try:
        return await orchestrator.start_remediation(num)
    except StageError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/review/{num}", response_model=Issue)
async def review(num: int) -> Issue:
    try:
        return await orchestrator.start_review(num)
    except StageError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/poll")
async def poll_now() -> dict:
    await orchestrator.poll_once()
    return {"status": "polled"}



