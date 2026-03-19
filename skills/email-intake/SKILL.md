---
name: email-intake
description: Use when processing inbound emails that must be read end-to-end, classified into YouTrack actions, and answered with a concise operational reply.
---

# Email Intake

Use this skill when the assistant is handling an inbound email through the mailbox workflow.

## Primary goal

Read the entire email, understand what the sender is asking, use the available YouTrack tools when appropriate, and generate the reply that should be sent back to the sender.

## Workflow

1. Read the whole email body before acting.
2. Extract:
   - sender identity and likely customer
   - explicit requests
   - hidden or implied operational requests
   - issue IDs, links, and project references
   - urgency signals
3. Decide whether the email should:
   - create a new issue
   - edit an existing issue
   - add or edit a worklog
   - create a knowledge base entry
   - ask for clarification only
4. Use the relevant tools.
5. Produce a short reply suitable for email delivery.

## Tool strategy

- Use `POST /requests/ingest` when normalization or project matching helps.
- Use `GET /projects` if project selection needs validation.
- Use `GET /issues/{issue_id}` and `POST /issues/{issue_id}/edit` for issue changes.
- Use `GET /issues/{issue_id}/work-items` and `POST /issues/{issue_id}/work-items/{item_id}/edit` for worklog corrections.
- Use `POST /actions/preview` and `POST /actions/commit` for free-form requests that should become new operations.

## Rules

- Do not rely only on the subject line.
- Do not ignore quoted or lower sections if they contain the actual task details.
- If multiple requests exist in the same email, keep them separate in your internal reasoning and tool usage.
- If the sender provides explicit wording for a comment or worklog text, preserve that wording.
- If you need clarification, ask one compact question rather than a long questionnaire.

## Reply style

- Write like a competent human assistant.
- Confirm what you did in plain language.
- Include the YouTrack link when available and useful.
- Avoid tool names and internal technical jargon.
