import type { Summary } from "../types";

const CARDS: { key: keyof Summary; label: string }[] = [
  { key: "total", label: "Tracked issues" },
  { key: "triaged", label: "Triaged" },
  { key: "approved", label: "Approved" },
  { key: "prs_open", label: "PRs opened" },
  { key: "reviewed", label: "Reviewed" },
  { key: "needs_attention", label: "Needs attention" },
];

export function KPICards({ summary }: { summary: Summary | null }) {
  return (
    <div className="kpi-row">
      {CARDS.map((c) => (
        <div className="kpi-card" key={c.key}>
          <div className="kpi-value">{summary ? summary[c.key] : "—"}</div>
          <div className="kpi-label">{c.label}</div>
        </div>
      ))}
    </div>
  );
}
