import type { Issue } from "../types";
import { ReadinessBadge, StageBadge } from "./StageBadge";

interface Props {
  issues: Issue[];
  selected: number | null;
  busy: number | null;
  onSelect: (n: number) => void;
  onTriage: (n: number) => void;
  onApprove: (n: number) => void;
}

function ActionCell({
  issue,
  busy,
  onTriage,
  onApprove,
}: {
  issue: Issue;
  busy: number | null;
  onTriage: (n: number) => void;
  onApprove: (n: number) => void;
}) {
  const n = issue.github_issue_num;
  const isBusy = busy === n;
  if (issue.state === "new") {
    return (
      <button disabled={isBusy} onClick={() => onTriage(n)}>
        {isBusy ? "…" : "Run triage"}
      </button>
    );
  }
  if (issue.state === "triaged") {
    return (
      <button className="primary" disabled={isBusy} onClick={() => onApprove(n)}>
        {isBusy ? "…" : "Approve"}
      </button>
    );
  }
  return <span className="muted">—</span>;
}

export function IssueTable(props: Props) {
  const { issues, selected, busy, onSelect, onTriage, onApprove } = props;
  return (
    <table className="issue-table">
      <thead>
        <tr>
          <th>Issue</th>
          <th>Triage</th>
          <th>Stage</th>
          <th>PR</th>
          <th>Action</th>
        </tr>
      </thead>
      <tbody>
        {issues.map((issue) => (
          <tr
            key={issue.github_issue_num}
            className={selected === issue.github_issue_num ? "selected" : ""}
            onClick={() => onSelect(issue.github_issue_num)}
          >
            <td>
              <span className="issue-num">#{issue.github_issue_num}</span>{" "}
              <span className="issue-title">{issue.title}</span>
            </td>
            <td>
              <ReadinessBadge
                level={issue.readiness_level}
                score={issue.readiness_score}
              />
            </td>
            <td>
              <StageBadge stage={issue.state} />
            </td>
            <td>
              {issue.pr_url ? (
                <a href={issue.pr_url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>
                  PR
                </a>
              ) : (
                <span className="muted">—</span>
              )}
            </td>
            <td onClick={(e) => e.stopPropagation()}>
              <ActionCell
                issue={issue}
                busy={busy}
                onTriage={onTriage}
                onApprove={onApprove}
              />
            </td>
          </tr>
        ))}
        {issues.length === 0 && (
          <tr>
            <td colSpan={5} className="muted center">
              No issues tracked yet. Add one to begin.
            </td>
          </tr>
        )}
      </tbody>
    </table>
  );
}
