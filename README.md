# Devin Orchestrator

A human-in-the-loop control plane that turns bounded **Apache Superset** maintenance
issues into reviewable pull requests using **Devin** — with a human approval gate at
every risky step.

> **Operating principle:** Devin *recommends*, a human *approves*, Devin *executes*,
> a human *merges*. No code is changed without explicit human approval. Devin's
> built-in Review bot auto-reviews every PR.

---

## What it does

For each GitHub issue, the orchestrator runs a two-stage pipeline backed by **separate
Devin sessions**, each with a role-specific prompt and ACU budget:

| Stage | Devin session | Allowed to | Output |
|-------|---------------|-----------|--------|
| **Triage** | read-only | analyze only — no edits, no PR | strict JSON readiness report |
| **Remediation** | code-changing | edit code, run tests, open a PR | a pull request |

Between **Triage** and **Remediation** there is a **human approval gate**: a maintainer
clicks *Approve* in the dashboard, or adds the `devin-remediate` label on GitHub.

Once remediation opens a PR, Devin's **built-in Review bot** automatically reviews it
— no orchestrator-managed review session needed.

### Two trigger paths

| Path | How it starts | What happens |
|------|---------------|--------------|
| **Label (event-driven)** | Human adds `devin-triage` or `devin-remediate` label on GitHub | GitHub Action fires → calls Devin API with full prompt + schema + ACU limits → comments session link on issue → backend discovers session by tag |
| **Dashboard (manual)** | Human enters issue # and clicks "Run triage" or "Approve" | Backend adds label → same Action fires |

Both paths converge at the same state machine. The dashboard shows the same data
regardless of how the session was triggered.

### Why this design

- **Structured output, not prose parsing.** The triage session is forced to return JSON
  matching a JSON Schema via Devin's `structured_output_schema`, so the orchestrator
  gets deterministic fields instead of scraping free text.
- **The PR comes from the session, not GitHub scraping.** The remediation session object
  exposes `pull_requests[]`, so the orchestrator reads the PR URL/state directly.
- **Bounded autonomy.** Each role has a `max_acu_limit` so a runaway session can't burn
  budget.
- **Human clarification loop.** When triage surfaces questions, the human answers via a
  GitHub comment.
- **Single session creation path.** Both the dashboard and direct label application on
  GitHub converge on the same GitHub Action to create Devin sessions. The backend only
  adds labels — it never calls the Devin API to create sessions directly. This eliminates
  duplicate sessions.

---

## Architecture

```
┌──────────────────────────┐          ┌──────────────────────────┐
│  GitHub Issue             │          │  React + Vite Dashboard  │
│                          │          │  localhost:3000 (Docker)  │
│  Human adds label:       │          │  localhost:5173 (dev)     │
│  devin-triage or         │          │                          │
│  devin-remediate         │          │  "Run triage" / "Approve"│
└──────────┬───────────────┘          └──────────┬───────────────┘
           │                                     │
           ▼                                     │
┌──────────────────────────┐   polls /api/issues │
│  GitHub Action            │   POST /api/triage  │
│  (in Superset fork)       │   POST /api/remediate
│                          │                     │
│  Calls Devin API directly│                     │
│  Tags: devin-orchestrator│                     │
│  + role + issue-N        │                     │
└──────────┬───────────────┘                     │
           │                                     │
           │  (backend discovers                 │
           │   via tag polling)                  │
           ▼                                     ▼
┌──────────────────────────────────────────────────────────────┐
│                    FastAPI Backend (port 8080)                │
│                                                              │
│  orchestrator.py  — state machine, discover_sessions(),      │
│                     stage handlers                            │
│  devin_client.py  — create/get/list session                  │
│  github_client.py — get_issue, add_label, comment            │
│  store.py         — SQLite persistence                       │
│  prompts/         — triage.md, remediation.md                │
└──────────┬──────────────────────────────────┬────────────────┘
           │                                  │
           ▼                                  ▼
┌──────────────────────┐        ┌──────────────────────────┐
│   Devin REST API     │        │     GitHub REST API      │
│   api.devin.ai       │        │     api.github.com       │
└──────────────────────┘        └──────────────────────────┘
```

### Session discovery

Every Devin session is tagged `["devin-orchestrator", "{role}", "issue-{N}"]`.

On every poll cycle (~8s), the backend calls `list_sessions()`, filters by the
`devin-orchestrator` tag, and matches sessions to issues via `issue-N` tags. Sessions
started by the GitHub Action are adopted into the state machine. The dashboard triggers
sessions indirectly by adding labels, which fire the same GitHub Action.

### Pipeline states

```
new → triaging → triaged → remediating → pr_open
                    │
                    ▼
                [human approval]

Any state → needs_attention (on error / no PR / invalid output)
```

### Labels (audit trail on GitHub issue)

| When | Label added |
|------|-------------|
| Triage starts | `devin-triage` |
| Triage completes | `devin-triaged` |
| Remediation approved | `devin-remediate` |
| PR opened | `devin-pr-open` |

### Comments (audit trail on GitHub issue)

| When | Comment posted |
|------|----------------|
| Triage session starts | "Devin triage session started: {url}" (posted by GitHub Action) |
| Triage completes | Triage report (readiness, risks, clarification, likely files) |
| Remediation session starts | "Devin remediation session started: {url}" (posted by GitHub Action) |

---

## Required credentials

All four must be set in `.env`:

| Variable | Where to get it |
|----------|----------------|
| `DEVIN_API_KEY` | app.devin.ai → Settings → Service Users |
| `DEVIN_ORG_ID` | app.devin.ai → Settings → Organization (starts with `org-`) |
| `GITHUB_TOKEN` | GitHub PAT with `issues:write` + `pull_requests:read` on the target repo |
| `GITHUB_REPO` | `owner/repo` of the Superset fork (e.g. `AdityaParashar24/superset`) |

### Optional settings

| Variable | Default | Description |
|----------|---------|-------------|
| `POLL_INTERVAL_SECONDS` | `8` | How often the backend polls Devin for session updates |
| `TRIAGE_MAX_ACU` | `5` | Max ACU budget for triage sessions |
| `REMEDIATION_MAX_ACU` | `30` | Max ACU budget for remediation sessions |

---

## Quick start (Docker — recommended)

### 1. Clone & configure
```bash
git clone https://github.com/AdityaParashar24/superset-devin-orchestrator.git
cd superset-devin-orchestrator
cp .env.example .env
```

Edit `.env` — fill in the four required values (see [Required credentials](#required-credentials)).

### 2. Run
```bash
docker compose up --build
```

Open http://localhost:3000.

- Frontend (nginx): port **3000**
- Backend (FastAPI): port **8080**

### 3. Reset (clear all tracked issues)
```bash
docker compose down -v        # removes the DB volume
docker compose up --build     # starts fresh
```

---

## Quick start (without Docker)

### 0. Prerequisites
- Python 3.11+
- Node 18+

### 1. Configure
```bash
cp .env.example .env
# edit .env with your credentials (see "Required credentials" above)
```

### 2. Backend
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8080
```

### 3. Frontend
```bash
cd frontend
npm install
npm run dev           # http://localhost:5173 (proxies /api to :8080)
```

Open http://localhost:5173.

---

## GitHub Action setup (event-driven label trigger)

To enable the label-driven path (where adding `devin-triage` on an issue auto-starts
triage), add the GitHub Action to your **Superset fork** (not this repo):

1. Copy `.github/workflows/devin-on-label.yml` to `<superset-fork>/.github/workflows/`
2. Add **repository secrets** to the fork:
   - `DEVIN_API_KEY` — same service-user token as above
   - `DEVIN_ORG_ID` — same org ID
3. Create labels on the fork: `devin-triage`, `devin-remediate`

Now applying `devin-triage` to an issue fires a triage session automatically.
The dashboard's "Run triage" button also adds this label, triggering the same Action.

---

## API reference

| Method | Path | Purpose |
|--------|------|---------|
| GET  | `/api/health` | Config status (configured / not configured) |
| GET  | `/api/issues` | All tracked issues with full state |
| GET  | `/api/issues/{n}` | Single issue detail |
| GET  | `/api/summary` | KPI counts (triaged, approved, PRs open, needs attention) |
| POST | `/api/issues` | Track a new issue `{"github_issue_num": 7}` |
| POST | `/api/triage/{n}` | Add `devin-triage` label → triggers triage session |
| POST | `/api/remediate/{n}` | Add `devin-remediate` label → triggers remediation (the human gate) |
| POST | `/api/poll` | Force a poll tick (discovery + advancement) |

---

## Candidate issues (Superset)

Real, bounded issues in the fork that this orchestrator was designed around:

1. **`pandas_postprocessing` rank edge case** — `superset/utils/pandas_postprocessing/rank.py`
2. **`ExportTagsCommand` validation consistency** — `superset/commands/tag/export.py`
3. **Re-enable skipped tests** — `tests/unit_tests/db_engine_specs/test_ocient.py`

---

## Project layout

```
superset-devin-orchestrator/
├── .env.example             # All configurable env vars with comments
├── docker-compose.yml       # One-command setup
├── backend/
│   ├── main.py              # FastAPI app + routes + poll loop
│   ├── orchestrator.py      # State machine, discover_sessions(), stage handlers
│   ├── devin_client.py      # Devin REST wrapper (v3)
│   ├── github_client.py     # Issue/label/comment operations
│   ├── store.py             # SQLite CRUD
│   ├── models.py            # Pydantic models + Stage enum
│   ├── config.py            # .env loader
│   ├── requirements.txt     # Python dependencies
│   ├── Dockerfile           # Backend container
│   └── prompts/
│       ├── triage.md        # Read-only analysis prompt
│       └── remediation.md   # Fix + open PR prompt
└── frontend/
    ├── src/                 # React + TypeScript components
    ├── package.json
    ├── vite.config.ts       # Dev proxy to backend :8080
    ├── Dockerfile           # Frontend container (nginx)
    └── nginx.conf           # Reverse proxy for /api → backend
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Ghost issue reappears after restart | Old Devin sessions still exist. Run `docker compose down -v && docker compose up --build` to wipe the DB. The backend only auto-ingests from **running** sessions — old exited sessions won't resurrect. |
| "Not configured" pill on dashboard | One or more of `DEVIN_API_KEY`, `DEVIN_ORG_ID`, `GITHUB_TOKEN` is empty in `.env`. |
| Duplicate comments on GitHub issue | Ensure you're on the latest version — PR #15 added deduplication checks. |
| Backend crash: "Incorrect number of bindings" | Ensure you're on the latest version — PR #16 fixed this. |
| Triage session URL not appearing | The session is created asynchronously by the GitHub Action. Wait ~8s for the next poll cycle to discover it. |
