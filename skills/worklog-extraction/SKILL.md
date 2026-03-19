---
name: worklog-extraction
description: Use when the user describes time spent in natural language and you need to derive YouTrack worklog actions, especially for daily summaries and mixed notes.
---

# Worklog Extraction

Use this skill when the input contains durations, calls, fixes, support work, or day-close summaries that should become tracked time.

When the input comes from email, read the full message and preserve the sender's explicit wording for the work description whenever possible.

## Workflow

1. Parse the message into separate activity chunks.
2. Detect duration expressions such as:
   - `1 ora`
   - `2 ore`
   - `30 minuti`
   - mixed daily summaries
3. For each chunk, identify:
   - project
   - issue ID if present
   - description of the work
   - whether confirmation is needed
4. Build a preview before any commit.
5. Commit only once project/issue routing is safe.

## Decision rules

- If duration exists but issue/project is missing, ask instead of guessing.
- If project is clear but issue is missing, use the configured service/default issue only if the backend preview marks it as acceptable.
- If one sentence includes both issue-like work and time, let the preview propose both an issue action and a worklog action.
- If multiple clients are mentioned in one summary, keep their time separated.
- If the user provides an explicit comment block for the worklog, preserve it exactly and do not rewrite it.
- Do not prepend labels such as `Commento:` inside the saved worklog text unless the user explicitly wants that label stored.

## Preferred tool sequence

- Use `GET /issues/{issue_id}/work-items` when you need to inspect existing worklogs.
- Use `POST /issues/{issue_id}/work-items/{item_id}/edit` when the user wants to correct an existing work item.
- Use `POST /actions/preview` for free-form day-close notes.
- Use `POST /requests/ingest` first if sender/customer normalization would improve project matching.
- Use `POST /actions/commit` only after reviewing the worklog candidates.

## Output style

Return a short discursive summary and explicitly list any time entries that still need clarification.
