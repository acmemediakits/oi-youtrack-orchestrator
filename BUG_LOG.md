# BUG_LOG

## 2026-03-20

### Runtime settings save redirects to error page

- Status: resolved
- Area: panel / runtime settings
- Reporter: user
- Environment: live panel on deployed container

Observed behavior:
- If a runtime property such as `VERBOSE` is changed from the panel and the settings are saved, the UI redirects to `/panel/settings` and returns an internal server error.

Expected behavior:
- After saving runtime settings, the panel should complete successfully and return to `/panel` with the updated values visible.

Notes:
- The bug was observed during manual live testing.
- The fix was to restore the missing `logging` import used during runtime-config updates.
- The user reported that the bug now appears resolved in live usage.

## 2026-03-23

### Issue creation flow: project assignment is valid, assignee write is the risky step

- Status: review pending
- Area: YouTrack commit flow / issue creation
- Reporter: user
- Environment: API commit flow for email/manual issue creation

Observed behavior:
- During commit, the system creates a new issue with `summary`, `description`, and `project.id`, then performs a second call to assign the issue owner through a detected custom field.
- The user suspected that sending the project during save could be the source of API errors.

Expected behavior:
- The create request should include the project, because YouTrack requires it for new issues.
- If an assignee must be set, the system should do so using a field/value combination that is known to be valid for the target project, or degrade gracefully without making the overall flow ambiguous.

Verification against official documentation:
- The suspicion about `project` is not confirmed by the official YouTrack REST documentation.
- JetBrains documents `summary` and `project (id)` as required fields for `POST /api/issues`.
- JetBrains also documents that custom fields, including `Assignee`, can be set either during issue creation with `customFields` or later through the issue custom field endpoint.

Evidence in this codebase:
- `app/services.py` creates the issue with `project: {"id": operation.project_id}` and only afterwards calls `_assign_issue(...)`.
- `_assign_issue(...)` discovers candidate user fields dynamically and retries with multiple payload shapes (`login`, `name`, `fullName`), which is a signal that the assignment step is the unstable part, not the project binding itself.
- Live evidence captured from the email workflow shows the backend still returning: `incompatible-issue-custom-field-name-Assignee` while reporting "Attempted fields: Assignee".

Likely root cause:
- The risky behavior is not “assigning the project during save”; that part is required by the API.
- The fragile part is the post-create assignee update, because field discovery is heuristic and the accepted user identity may vary by project configuration.

Source:
- JetBrains YouTrack Developer Portal, "Issues" (`POST /api/issues`, required fields `summary` and `project.id`): https://www.jetbrains.com/help/youtrack/devportal/resource-api-issues.html
- JetBrains YouTrack Developer Portal, "Create an Issue and Set Custom Fields" (example with `Assignee` in `customFields` during create): https://www.jetbrains.com/help/youtrack/devportal/api-howto-create-issue-with-fields.html
- JetBrains YouTrack Developer Portal, "Operations with Specific IssueCustomField" (update custom field after creation): https://www.jetbrains.com/help/youtrack/devportal/operations-api-issues-issueID-customFields.html

Possible solution:
- Keep `project.id` in the create payload.
- Prefer a two-phase flow that is explicit and deterministic:
- 1. create the issue and persist the returned readable/id reference;
- 2. reconnect using that issue id and write the assignee only after resolving the exact project field metadata and the accepted user identifier for that project.
- Alternative: when field metadata is already known, set `Assignee` directly in the initial `customFields` payload and avoid heuristic retries after creation.

Review notes:
- A later live review of the target project settings showed that the expected assignee custom field had not actually been created on that project.
- This means the reported production failure may have been caused by project configuration drift rather than an unresolved backend defect.
- Keep this item in review-pending state until the same email flow is revalidated end-to-end on projects where the assignee field is correctly configured.

Tracking notes for agents:
- Do not spend time removing `project.id` from create requests unless new evidence appears.
- Focus investigation on field discovery, per-project assignee field naming, accepted user identity (`login` vs displayed name), and error visibility returned by YouTrack.
- Re-test specifically from the email flow, not only from direct/manual commit flows, after confirming the project custom field is present in YouTrack.

### Email thread context is lost across clarification replies

- Status: resolved (short-term mitigation)
- Area: mailbox / AI planner / reply handling
- Reporter: user
- Environment: email-driven workflows with clarification loop

Observed behavior:
- The system sends clarification questions by email.
- The outgoing reply does not include the original message body or any quoted conversation history.
- When the user answers that clarification email, the AI often receives only the latest short reply and loses the operational context of the original request.

Expected behavior:
- A clarification reply should preserve enough thread context for the next inbound message to remain interpretable.
- The planner should be able to reconstruct the original request, previous clarification, and any generated YouTrack outcome linked to that email conversation.

Evidence in this codebase:
- `app/mailbox.py` sends replies with `message.set_content(body)` only; no quoted original body, no appended transcript, no thread reconstruction block.
- `app/mail_agent.py` builds planner context from the current inbound message (`subject` + `message.text`) and explicitly relies on quoted thread text only "if present".
- `MailProcessingRecord` stores per-message processing output, but there is no persistent conversation-thread model that links successive replies into a reusable history.

Impact:
- Follow-up replies become ambiguous.
- Clarification loops degrade quickly.
- The AI can lose track of why a question was asked, which issue was created, and what was already decided.

Possible solution:
- Implemented short term: clarification replies now carry explicit operational context and quoted original-thread content so follow-up replies retain more usable history.
- Medium/long-term thread-state architecture has been extracted into feature planning and is no longer tracked as part of this bug entry.

Tracking notes for agents:
- The phrase in the planner prompt "including any quoted thread text if present" is currently aspirational, not guaranteed by the transport layer.
- Avoid a local copy of every email unless a future compliance/debug requirement explicitly demands it.
- The local code fix appended quoted original context to reply emails and embedded a compact operational-context block in clarification replies.
- The user reported that the short-term fix now appears resolved in live usage.

### Task generation quality is still too weak for production use

- Status: in progress as planned feature
- Area: AI planning / issue drafting
- Reporter: user
- Environment: email/manual request to YouTrack issue generation

Observed behavior:
- The assistant still produces summaries and descriptions that do not reliably make sense.
- It does not consistently distinguish between a short actionable title and a fuller descriptive body.
- It under-interprets the meaning of the source thread and tends to mirror input text instead of synthesizing a useful ticket.
- Even when the issue is materially correct, the generated description is often dumped as a dense plain-text block instead of a readable Markdown structure that takes advantage of YouTrack formatting support.

Expected behavior:
- `summary` should be short, action-oriented, and suitable as a real YouTrack issue title.
- `description` should preserve the business/operational request with enough detail to execute the work.
- The model should infer intent from the whole thread, not just paraphrase the latest message.
- `description` should be formatted as clean Markdown for YouTrack, using structure when helpful: short intro, bullet list of requests, links on separate meaningful anchors, and explicit notes/open questions when present.

Evidence in this codebase:
- The planner prompt contains rules for concise `issue_summary` and "clean issue_description", but there is no stronger structural validation that rejects poor title/body separation before commit.
- The preview/commit flow accepts AI-provided summary/description with limited semantic quality control once the plan is normalized.
- Live issue output confirms that the text currently lands as a minimally formatted paragraph even when the content would benefit from Markdown sections/lists.

Source:
- JetBrains YouTrack Markdown Syntax for issues and issue descriptions: https://www.jetbrains.com/help/youtrack/server/youtrack-markdown-syntax-issues.html

Impact:
- Low-quality task creation reduces trust in the automation.
- Operators must manually rewrite tickets.
- Weak summaries/descriptions also make search, routing, and later thread recovery worse.

Possible solution:
- Improve prompting and examples so the model sees stronger distinctions between title and description.
- Add explicit formatting guidance for YouTrack Markdown in the planner and/or post-processing layer.
- Prefer structured descriptions by default, for example:
- short problem statement
- numbered or bulleted requested interventions
- relevant links under a dedicated section
- constraints / expected outcome
- Add lightweight validation heuristics before commit, for example rejecting titles that are too long, too generic, or too similar to the full description.
- Consider loosening over-constrained instructions if they are pushing the model toward sterile paraphrase rather than useful interpretation.
- If future thread persistence is added, use the whole conversation and downstream outcomes as context for better ticket drafting.

Tracking notes for agents:
- This is no longer tracked as a pure bug fix.
- It is now part of planned product work on prompt/agent quality and metadata-aware planning.
- Any future implementation should be evaluated on real thread-to-ticket examples, not only synthetic unit cases.
- Issue and knowledge descriptions should be treated as Markdown-capable fields; worklog comments should remain plain text by default.

### Tooling gap: missing endpoint to archive and restore projects

- Status: resolved
- Area: API / tool surface / project administration
- Reporter: user
- Environment: assistant/tool usage for project lifecycle management

Observed behavior:
- The current tool surface does not expose an endpoint/action to archive or restore a YouTrack project.
- As a consequence, the assistant reports that project archiving/reactivation is not available programmatically even though YouTrack supports project updates through its REST API.

Expected behavior:
- The tool should expose a safe administrative endpoint to archive a project.
- The tool should expose the corresponding endpoint to restore a previously archived project.
- The assistant should be able to use these actions instead of falling back to manual UI instructions when the caller has sufficient permissions.

Verification against official documentation:
- JetBrains documents `POST /api/admin/projects/{projectID}` as the update operation for a specific project.
- The `Project` entity includes an `archived` boolean attribute, and project attributes are updated by providing them in the POST body.
- From this, it is reasonable to infer that archive/restore can be implemented by updating `archived` to `true` or `false` on the specific project resource.

Source:
- JetBrains YouTrack Developer Portal, "Projects": https://www.jetbrains.com/help/youtrack/devportal/resource-api-admin-projects.html
- JetBrains YouTrack Developer Portal, "Operations with Specific Project": https://www.jetbrains.com/help/youtrack/devportal/operations-api-admin-projects.html
- JetBrains YouTrack Cloud Documentation, "Archive a Project / Restore a Project": https://www.jetbrains.com/help/youtrack/cloud/archiving-a-project.html

Possible solution:
- Add an API endpoint that wraps `POST /api/admin/projects/{projectID}` with `{"archived": true}`.
- Add the symmetric restore endpoint with `{"archived": false}`.
- Guard both endpoints behind the appropriate admin permission/capability checks.
- Return updated project metadata so callers can confirm the state transition immediately.

Resolution notes:
- The tool surface now exposes project metadata editing and project archive-state updates through dedicated project endpoints.
- Archive and restore are handled by updating the project `archived` attribute and returning refreshed project metadata.

Tracking notes for agents:
- This is a missing capability in the tool surface, not evidence that YouTrack lacks the underlying API.
- When implementing, verify that permission checks and user-facing wording distinguish clearly between archive, restore, and delete.
