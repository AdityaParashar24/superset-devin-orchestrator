import type { Health, Issue, Summary } from "./types";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(detail.detail || `Request failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => req<Health>("/health"),
  summary: () => req<Summary>("/summary"),
  listIssues: () => req<Issue[]>("/issues"),
  getIssue: (n: number) => req<Issue>(`/issues/${n}`),
  triage: (n: number) => req<Issue>(`/triage/${n}`, { method: "POST" }),
  remediate: (n: number) => req<Issue>(`/remediate/${n}`, { method: "POST" }),
  review: (n: number) => req<Issue>(`/review/${n}`, { method: "POST" }),
  createIssue: (github_issue_num: number, title: string, body: string) =>
    req<Issue>("/issues", {
      method: "POST",
      body: JSON.stringify({ github_issue_num, title, body }),
    }),
};
