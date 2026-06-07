# Superset Maintenance Enablement Console

A human-in-the-loop control plane that turns bounded **Apache Superset** maintenance
issues into reviewable pull requests using **Devin** — with a human approval gate at
every risky step.

> **Operating principle:** Devin *recommends*, a human *approves*, Devin *executes*,
> Devin *self-reviews*, a human *merges*. No code is changed without explicit human
> approval.

![pipeline](docs/dashboard.png)

---

## What it does

For each GitHub issue, the console runs a three-stage pipeline backed by **separate
Devin sessions**, each with a role-specific prompt and ACU budget:

| Stage | Devin session | Allowed to | Output |
|-------|---------------|-----------|--------|
| **Triage** | read-only | analyze only — no edits, no PR | strict JSON readiness report |
| **Remediation** | code-changing | edit code, run tests, open a PR | a pull request |
| **Review** | comment-only | review the PR — no merge, no push | a verdict |

Between **Triage** and **Remediation** there is a **human approval gate**: a maintainer
clicks *Approve remediation* (or applies the `devin-remediate` label).

### Why this design

- **Structured output, not prose parsing.** The triage session is forced to return JSON
  matching a JSON Schema via Devin's `structured_output_schema`, so the orchestrator gets
  deterministic fields (`readiness_score`, `likely_files`, `remediation_prompt`, …) instead
  of scraping free text.
- **The PR comes from the session, not GitHub scraping.** The remediation session object
  exposes `pull_requests[]`, so the orchestrator reads the PR URL/state directly.
- **Bounded autonomy.** Each role has a `max_acu_limit` so a runaway session can't burn
  budget.

---

## Architecture

```
GitHub issue (label: devin-triage / devin-remediate)
        │
        ▼
.github/workflows/devin-on-label.yml   ──POST /api/webhook/github──►  FastAPI backend
                                                                          │
   React + Vite dashboard  ◄──polls /api/issues, /api/summary──────────  │
        │  (Approve / Run triage / Run review buttons)                    │
        └────────────────────POST /api/triage|remediate|review──────────►│
                                                                          ▼
                                                            Devin REST API (v3)
                                                   triage · remediation · review sessions
```

- **backend/** — FastAPI app, SQLite store, orchestrator state machine, Devin + GitHub
  clients, and the three role prompts.
- **frontend/** — React + Vite dashboard (KPI cards, pipeline table, per-issue timeline).
- **.github/workflows/devin-on-label.yml** — public-repo trigger (Devin's native GitHub
  automations are private-repo only).

### Pipeline states

```
new → triaging → triaged → approved → remediating → pr_open → reviewing → reviewed
                                  └──────────► needs_attention (on error / no PR)
```

---

## Quick start

### 0. Prerequisites
- Python 3.11+
- Node 18+

### 1. Configure
```bash
cp .env.example .env
# edit .env — or leave DEMO_MODE=true to run with simulated Devin/GitHub
```

### 2. Backend
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Optional: seed 3 demo issues at different pipeline stages
python seed.py

uvicorn main:app --reload --port 8000
```

### 3. Frontend
```bash
cd frontend
npm install
npm run dev           # http://localhost:5173 (proxies /api to :8000)
```

Open http://localhost:5173.

---

## Demo mode vs. live mode

The console runs in two modes, controlled by `DEMO_MODE` in `.env`:

- **`DEMO_MODE=true`** — Devin and GitHub are simulated in-process. Sessions auto-complete
  after a few seconds with realistic triage reports and fake PRs. Lets you click the whole
  pipeline end-to-end with **zero credentials**. Great for demos/screenshots.
- **`DEMO_MODE=false`** — real Devin sessions and real GitHub calls. Requires:
  - `DEVIN_API_KEY` — a Devin service-user token (`app.devin.ai` → Settings → Service Users)
  - `DEVIN_ORG_ID` — your org id (`org-…`)
  - `GITHUB_TOKEN` — PAT with `issues:write` + `pull_requests:read`
  - `GITHUB_REPO` — e.g. `AdityaParashar24/superset`

---

## Going live on a public fork

Devin's *native* GitHub automations only fire on **private** repos. For a public fork, the
included GitHub Action is the equivalent: on `issues.labeled`, it forwards the issue to the
backend's `/api/webhook/github`, which starts the right Devin session.

Add two repo secrets in GitHub (Settings → Secrets → Actions):
- `BACKEND_URL` — public URL of the deployed backend
- `BACKEND_SECRET` — must match the backend's `BACKEND_SECRET`

Then apply `devin-triage` (and later `devin-remediate`) to an issue.

---

## API reference

| Method | Path | Purpose |
|--------|------|---------|
| GET  | `/api/health` | mode + config status |
| GET  | `/api/issues` | all tracked issues |
| GET  | `/api/issues/{n}` | one issue |
| GET  | `/api/summary` | KPI counts + ACUs |
| POST | `/api/issues` | track a new issue |
| POST | `/api/triage/{n}` | start a triage session |
| POST | `/api/remediate/{n}` | approve → start remediation (the human gate) |
| POST | `/api/review/{n}` | start a review session |
| POST | `/api/poll` | force a poll tick |
| POST | `/api/webhook/github` | called by the GitHub Action (Bearer `BACKEND_SECRET`) |

---

## Candidate issues (Superset)

Real, bounded issues in the fork that this console was designed around:

1. **`pandas_postprocessing` rank edge case** — `superset/utils/pandas_postprocessing/rank.py`
2. **`ExportTagsCommand` validation consistency** — `superset/commands/tag/export.py`
3. **Re-enable skipped tests** — `tests/unit_tests/db_engine_specs/test_ocient.py`

---

## Project layout

```
superset-devin-enablement-console/
├── .env.example
├── .github/workflows/devin-on-label.yml
├── backend/
│   ├── main.py            # FastAPI app + routes + poll loop
│   ├── orchestrator.py    # state machine, triage schema, stage handlers
│   ├── devin_client.py    # Devin REST wrapper (+ DEMO_MODE simulator)
│   ├── github_client.py   # issue/label/comment (+ DEMO_MODE no-op)
│   ├── store.py           # SQLite CRUD
│   ├── models.py          # Pydantic models + enums
│   ├── config.py          # .env loader
│   ├── seed.py            # stage demo issues
│   └── prompts/{triage,remediation,review}.md
└── frontend/              # React + Vite dashboard
```
