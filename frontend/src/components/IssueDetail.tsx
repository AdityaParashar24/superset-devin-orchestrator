import type { Issue, Stage } from "../types";

const ORDER: Stage[] = [
  "new",
  "triaged",
  "approved",
  "pr_open",
  "reviewed",
];

const STEP_LABELS: { stage: Stage; label: string }[] = [
  { stage: "new", label: "Intake — issue created" },
  { stage: "triaged", label: "Devin triage — readiness report" },
  { stage: "approved", label: "Human approval — devin-remediate" },
  { stage: "pr_open", label: "Devin remediation — PR opened" },
  { stage: "reviewed", label: "Devin review — verdict posted" },
];

function stageIndex(stage: Stage): number {
  // Map transient stages onto their nearest completed milestone.
  const map: Record<Stage, Stage> = {
    new: "new",
    triaging: "new",
    triaged: "triaged",
    approved: "approved",
    remediating: "approved",
    pr_open: "pr_open",
    reviewing: "pr_open",
    reviewed: "reviewed",
    needs_attention: "new",
  };
  return ORDER.indexOf(map[stage]);
}

export function IssueDetail({ issue }: { issue: Issue | null }) {
  if (!issue) {
    return (
      <div className="detail empty muted">
        Select an issue to see its full triage → remediation → review journey.
      </div>
    );
  }

  const current = stageIndex(issue.state);
  const isActive = ["triaging", "remediating", "reviewing"].includes(issue.state);

  return (
    <div className="detail">
      <h2>
        #{issue.github_issue_num} — {issue.title}
      </h2>
      <p className="detail-body">{issue.body}</p>

      {issue.failure_reason && (
        <div className="alert">⚠ {issue.failure_reason}</div>
      )}

      <div className="timeline">
        {STEP_LABELS.map((step, i) => {
          const done = i <= current;
          const active = isActive && i === current + 1;
          return (
            <div
              key={step.stage}
              className={`tl-step ${done ? "done" : ""} ${active ? "active" : ""}`}
            >
              <span className="tl-dot" />
              <span className="tl-label">{step.label}</span>
            </div>
          );
        })}
      </div>

      {issue.readiness_score != null && (
        <div className="card">
          <h3>Triage report</h3>
          <div className="kv">
            <span>Readiness</span>
            <span>
              {issue.readiness_level} ({issue.readiness_score}/100) ·{" "}
              {issue.recommendation}
            </span>
          </div>
          <div className="kv">
            <span>Risks</span>
            <span>{issue.risk_notes}</span>
          </div>
        </div>
      )}

      {issue.clarification_needed && (
        <div className="card" style={{ borderLeft: "3px solid var(--amber)" }}>
          <h3>Clarification needed</h3>
          <p>{issue.clarification_needed}</p>
        </div>
      )}

      <div className="card">
        <h3>Sessions & links</h3>
        <ul className="links">
          {issue.triage_session_url && (
            <li>
              <a href={issue.triage_session_url} target="_blank" rel="noreferrer">
                Triage session ↗
              </a>
            </li>
          )}
          {issue.remediation_session_url && (
            <li>
              <a href={issue.remediation_session_url} target="_blank" rel="noreferrer">
                Remediation session ↗
              </a>
            </li>
          )}
          {issue.review_session_url && (
            <li>
              <a href={issue.review_session_url} target="_blank" rel="noreferrer">
                Review session ↗
              </a>
            </li>
          )}
          {issue.pr_url && (
            <li>
              Pull request:{" "}
              <a href={issue.pr_url} target="_blank" rel="noreferrer">
                {issue.pr_url}
              </a>{" "}
              ({issue.pr_state})
            </li>
          )}
          {issue.review_verdict && (
            <li>
              Review verdict: <strong>{issue.review_verdict}</strong>
            </li>
          )}
        </ul>
        <div className="kv">
          <span>ACUs consumed</span>
          <span>{issue.acus_consumed.toFixed(1)}</span>
        </div>
      </div>
    </div>
  );
}
