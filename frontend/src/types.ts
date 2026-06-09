export type Stage =
  | "new"
  | "triaging"
  | "triaged"
  | "approved"
  | "remediating"
  | "pr_open"
  | "needs_attention";

export interface Issue {
  github_issue_num: number;
  title: string;
  body: string;
  state: Stage;
  readiness_score: number | null;
  readiness_level: string | null;
  recommendation: string | null;
  likely_files: string[];
  risk_notes: string | null;
  clarification_needed: string | null;
  triage_session_url: string | null;
  remediation_session_url: string | null;
  pr_url: string | null;
  pr_state: string | null;
  failure_reason: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface Summary {
  total: number;
  triaged: number;
  approved: number;
  prs_open: number;
  needs_attention: number;
}

export interface Health {
  status: string;
  configured: boolean;
  repo: string;
}
