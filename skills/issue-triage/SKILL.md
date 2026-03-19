---
name: issue-triage
description: Use when a request must be classified into the right YouTrack project and translated into issue create/update actions, especially from informal client text or operator notes.
---

# Issue Triage

Use this skill when the user asks to understand a client request, find the right project, or create/update an issue safely.

When the source is an email, read the full body before deciding whether the request is a new issue or a change to an existing one.

## Workflow

1. Read the request and identify customer clues:
   - customer name
   - aliases
   - email sender/domain
   - existing issue IDs
2. If project certainty is low, inspect available projects or ask one short clarification.
3. Build a preview before any issue write.
4. Summarize:
   - chosen project
   - whether the action is create or update
   - summary/description you intend to send
   - any open questions
5. Commit only when the preview is safe or explicitly approved.

## Preferred tool sequence

- Use `GET /projects` when project selection needs validation.
- Use `GET /issues/{issue_id}` when the user references an existing issue.
- Use `POST /issues/{issue_id}/edit` when the user wants to rename or rewrite an existing issue.
- Use `POST /requests/ingest` for normalization and customer/project matching.
- Use `POST /actions/preview` to produce issue candidates.
- Use `POST /actions/commit` only after confirming the plan when needed.

## Decision rules

- If an explicit issue ID exists, prefer update over create.
- If the text describes a new problem/request and no issue ID is present, prefer create.
- If the project is ambiguous, stop and ask.
- Do not silently merge multiple client contexts into one issue.
- If the body of an email adds detail that is not present in the subject, use the body as the primary source.

## Output style

Explain the plan in plain language first, then execute.
