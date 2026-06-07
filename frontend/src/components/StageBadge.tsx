import type { Stage } from "../types";

const LABELS: Record<Stage, string> = {
  new: "New",
  triaging: "Triaging…",
  triaged: "Triaged",
  approved: "Approved",
  remediating: "Remediating…",
  pr_open: "PR opened",
  reviewing: "Reviewing…",
  reviewed: "Reviewed",
  needs_attention: "Needs attention",
};

export function StageBadge({ stage }: { stage: Stage }) {
  return <span className={`badge badge-${stage}`}>{LABELS[stage]}</span>;
}

export function ReadinessBadge({
  level,
  score,
}: {
  level: string | null;
  score: number | null;
}) {
  if (level == null || score == null) return <span className="muted">—</span>;
  return (
    <span className={`readiness readiness-${level.toLowerCase()}`}>
      {level} {score}
    </span>
  );
}
