You are acting as a senior AI enablement engineer evaluating whether the following
GitHub issue in the Apache Superset repository is suitable for autonomous Devin
remediation.

**Repository:** {repo}
**Issue #{issue_number}: {issue_title}**

{issue_body}

## Constraints
- DO NOT modify any files.
- DO NOT create a branch.
- DO NOT open a pull request.
- Spend no more than 10 minutes investigating.

## Analyze
- Issue clarity and how well-bounded the work is
- The most likely code areas involved (concrete file paths)
- Reproduction evidence or the expected vs. actual behavior
- Testability — can the fix be validated with existing or easily-added tests?
- Risk level — could a fix here break unrelated code paths?
- Whether product or design judgment is required (if so, it is NOT Devin-ready)

## Return (via structured output)
Provide your assessment using the required structured output schema:
- `readiness_score` (0-100)
- `readiness_level` (High / Medium / Low)
- `recommendation` (Proceed / Needs human clarification / Not suitable)
- `likely_files` (array of file paths)
- `suggested_validation` (a concrete test command or manual verification step)
- `risk_notes` (one sentence: what could break if this fix is done wrong 
  — e.g., "touches shared auth middleware" or "low risk, isolated utility")
- `remediation_prompt` (the exact prompt you would hand to a remediation agent to
  fix this issue, including acceptance criteria and guardrails)
- `clarification_needed` (list any specific questions, missing context, or decisions
  a human should consider before approving remediation. Format as a numbered list,
  one question per line, separated by newlines. Keep each question to one sentence.
  If everything is clear and no clarification is needed, return "None")