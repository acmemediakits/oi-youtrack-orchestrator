---
name: email-intake
description: Use when processing inbound emails that must be read end-to-end, classified into YouTrack actions, and answered with a concise operational reply.
---

# Email Intake

Use this skill when the assistant is handling an inbound email through the mailbox workflow.

## Primary goal

Read the entire email, understand what the sender is asking, decide whether it is assist/helpdesk mode or YouTrack mode, use the available YouTrack tools only when appropriate, and generate the reply that should be sent back to the sender.

## Workflow

1. Read the whole email body before acting.
2. Extract:
   - sender identity and likely customer
   - explicit requests
   - hidden or implied operational requests
   - issue IDs, links, and project references
   - urgency signals
3. Decide whether the email should:
   - be handled as helpdesk assistance only
   - be delegated to an internal colleague or third person via summary email only
   - create a new issue
   - edit an existing issue
   - add or edit a worklog
   - generate a YouTrack time report for a specific period
   - create a knowledge base entry
   - ask for clarification only
4. Use the relevant tools.
5. Produce a short reply suitable for email delivery.

## Tool strategy

- Use `POST /requests/ingest` when normalization or project matching helps.
- Use `GET /projects/search` or `GET /projects` if project selection needs validation.
- Use `GET /issues/search` or `GET /projects/{project_id}/issues` to recover issue context before asking for IDs.
- Use `GET /issues/{issue_id}` and `POST /issues/{issue_id}/edit` for issue changes.
- Use `POST /issues/{issue_id}/work-items` for direct new worklogs when the issue is already known.
- Use `GET /issues/{issue_id}/work-items` and `POST /issues/{issue_id}/work-items/{item_id}/edit` for worklog corrections.
- Use `GET /assistant/project-context` or the reporting/search tools when project or issue discovery is the real problem.
- Use `GET /assistant/time-report/global` for cross-project monthly/hour summaries grouped by project.
- Use `POST /actions/preview` and `POST /actions/commit` for free-form requests that should become new operations.

## Rules

- Do not rely only on the subject line.
- Do not ignore quoted or lower sections if they contain the actual task details.
- If multiple requests exist in the same email, keep them separate in your internal reasoning and tool usage.
- If the email contains a ticket request written as an instruction, strip the wrapper command from the final issue title and description.
- If the sender already provides a good explicit title plus separate descriptive detail, preserve that structure instead of echoing the whole sentence into the title.
- If the sender provides explicit wording for a comment or worklog text, preserve that wording.
- If you need clarification, ask one compact question rather than a long questionnaire.
- If the email asks for a summary, explanation, translation, or action extraction, default to helpdesk assistance and do not create a ticket unless explicitly asked.
- If the email clearly asks you to remind, notify, contact, update, or write to another person, classify it as delegation and send the outgoing email to that person instead of replying with the same draft to the original sender.
- If the email asks for hours spent in a month or period, treat it as a reporting task and derive the exact date range before answering.

## Reply style

- Write like a competent human assistant.
- Confirm what you did in plain language.
- Include the YouTrack link when available and useful.
- Avoid tool names and internal technical jargon.
