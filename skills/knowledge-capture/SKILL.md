---
name: knowledge-capture
description: Use when the user wants to save commands, procedures, notes, or reusable snippets into the YouTrack knowledge base, including personal operational notes.
---

# Knowledge Capture

Use this skill when the user says to save, remember, document, or archive a command, note, procedure, or reusable snippet.

When the content comes from email, use the full body to determine whether the note is operational knowledge, client-specific knowledge, or just incidental context.

## Workflow

1. Identify the content to preserve.
2. Decide whether the destination is:
   - personal knowledge
   - client-specific knowledge
   - unclear and needs confirmation
3. Build a preview that includes:
   - title
   - content
   - project/folder destination
   - any tags if obvious
4. Explain what will be saved and where.
5. Commit only after the destination is safe.

## Decision rules

- If the user says `miei`, `personali`, or equivalent, prefer personal knowledge destination.
- If the content clearly belongs to one client/project, keep it there.
- If the destination is unclear, ask before writing.
- Preserve commands and code snippets exactly when possible.

## Preferred tool sequence

- Use `POST /actions/preview` for free-form text that may include KB candidates.
- Use `POST /requests/ingest` first when customer/project identification matters.
- Use `POST /actions/commit` only after verifying the KB target is correct.

## Output style

State the intended KB title and destination clearly before execution.
