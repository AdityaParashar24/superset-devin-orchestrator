import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import type { Health, Issue, Summary } from "./types";
import { KPICards } from "./components/KPICards";
import { IssueTable } from "./components/IssueTable";
import { IssueDetail } from "./components/IssueDetail";

const POLL_MS = 5000;

export default function App() {
  const [issues, setIssues] = useState<Issue[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [iss, sum] = await Promise.all([api.listIssues(), api.summary()]);
      setIssues(iss);
      setSummary(sum);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    api.health().then(setHealth).catch(() => undefined);
    refresh();
    const t = setInterval(refresh, POLL_MS);
    return () => clearInterval(t);
  }, [refresh]);

  const run = useCallback(
    async (n: number, fn: (n: number) => Promise<Issue>) => {
      setBusy(n);
      setError(null);
      try {
        await fn(n);
        await refresh();
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setBusy(null);
      }
    },
    [refresh],
  );

  const selectedIssue = useMemo(
    () => issues.find((i) => i.github_issue_num === selected) ?? null,
    [issues, selected],
  );

  return (
    <div className="app">
      <header className="topbar">
        <div>
          <h1>Superset Maintenance Enablement Console</h1>
          <p className="subtitle">
            Autonomous maintenance workflow with human approval gates · Devin
            recommends → human approves → Devin executes → Devin reviews → human
            merges
          </p>
        </div>
        <div className="status">
          {health && (
            <>
              <span className={`pill ${health.demo_mode ? "demo" : "live"}`}>
                {health.demo_mode ? "DEMO MODE" : "LIVE"}
              </span>
              <span className="repo">{health.repo || "repo unset"}</span>
            </>
          )}
        </div>
      </header>

      {error && <div className="alert top">⚠ {error}</div>}

      <KPICards summary={summary} />

      <div className="toolbar">
        <h2>Detected remediation candidates</h2>
        <div>
          <button onClick={refresh}>Refresh</button>
          <button className="primary" onClick={() => setShowAdd((s) => !s)}>
            + Add issue
          </button>
        </div>
      </div>

      {showAdd && <AddIssue onAdded={() => { setShowAdd(false); refresh(); }} />}

      <div className="layout">
        <div className="left">
          <IssueTable
            issues={issues}
            selected={selected}
            busy={busy}
            onSelect={setSelected}
            onTriage={(n) => run(n, api.triage)}
            onApprove={(n) => run(n, api.remediate)}
            onReview={(n) => run(n, api.review)}
          />
        </div>
        <div className="right">
          <IssueDetail issue={selectedIssue} />
        </div>
      </div>
    </div>
  );
}

function AddIssue({ onAdded }: { onAdded: () => void }) {
  const [num, setNum] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const submit = async () => {
    setErr(null);
    const n = parseInt(num, 10);
    if (!n) {
      setErr("Enter a valid GitHub issue number.");
      return;
    }
    try {
      await api.createIssue(n, "", "");
      onAdded();
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  return (
    <div className="add-issue card">
      <h3>Track a GitHub issue</h3>
      <p className="muted" style={{ margin: "0 0 8px", fontSize: "0.85rem" }}>
        Enter the issue number — title and description are fetched from GitHub automatically.
      </p>
      <div className="form-row">
        <input
          placeholder="Issue # (e.g. 42)"
          value={num}
          onChange={(e) => setNum(e.target.value)}
          type="number"
          min={1}
        />
        <button className="primary" onClick={submit}>
          Add
        </button>
      </div>
      {err && <div className="alert">{err}</div>}
    </div>
  );
}