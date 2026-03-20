# AI Guide

## Purpose

This project is an OpenAPI backend for Open WebUI that acts as an AI-operated back office for YouTrack.

The goal is to let a model:

- read and normalize incoming client requests
- identify the correct YouTrack project
- prepare issue, worklog, and knowledge base actions
- ask for clarification when confidence is low
- commit approved actions to YouTrack safely

This local file is also the canonical backlog for the project until a private GitHub repository is created.

## Current State

Implemented today:

- FastAPI backend with OpenAPI schema
- `GET /projects` working against the real YouTrack instance
- request ingest endpoint
- action preview endpoint
- action commit endpoint
- local JSON persistence for requests, previews, and commits
- deterministic customer/project matching
- Docker build context prepared for the Lada host
- local prompt/skill workspace started in the repository root
- hybrid mail workflow: YTBot can suggest a structured execution plan, while the backend executes YouTrack endpoints locally
- planner-controlled issue metadata for IMAP mode: YTBot can suggest explicit issue title, issue description, and default assignee
- post-commit email replies now come from actual execution results instead of optimistic pre-action drafts
- the default assignee label `developers` maps to the explicit YouTrack login `acmemediakits` in current tenant assumptions
- query layer primitives now include project search, issue search/listing, project time reports, article search, and assistant-oriented context helpers
- email planner now supports `assist` mode for summarize/translate/explain/extract-actions flows without creating YouTrack tickets by default
- assignee updates now inspect issue custom fields dynamically instead of assuming that the field name is always `Assignee`
- planner mail flow is now LLM-first: the model must classify `assist_intent`, while backend guardrails block drafts-for-third-parties that are not explicitly classified as `delegate`
- Open WebUI response parsing now fails explicitly on malformed `200` payloads instead of crashing on `NoneType.get`
- runtime configuration is split from secrets/bootstrap settings
- a minimal web control panel exists at `/panel/login` and `/panel`
- runtime settings are editable from JSON-backed storage in `data/`
- whitelist users now include canonical email, full name, assignee fallback email, role, and active state
- RBAC is active for `visitor`, `team`, and `power` users
- email `admin_scope` requests now require temporary-token approval from `SUPER_ADMIN_EMAIL`
- panel UX now includes a client-facing branded dashboard, one-column content flow, modal add/edit user management, and collapsible runtime/secrets sections
- the panel now exposes recent application logs for operational debugging
- IMAP startup now ensures runtime folders on boot and finalizes duplicate messages instead of re-reading the same unseen email forever
- Aurora confirms the runtime IMAP folders are real and subscribed; Roundcube appears to have a client-specific visibility limitation for those folders
- root changes are mirrored in `lada/` so deployment and local source stay aligned

Not yet complete:

- richer OpenAPI descriptions/examples for better tool discovery in Open WebUI
- better email-mode prompting for mailbox-driven workflows
- persistent email thread context across clarification loops instead of relying only on the visible quoted thread
- better normalization of planner-generated issue metadata in edge cases
- validate and harden assignee application against tenant-specific YouTrack field behavior
- stronger parsing for daily summaries and mixed worklog narratives
- dedicated system prompts for role, behavior, and confirmation strategy
- reusable skills and prompt assets for YouTrack, mailbox triage, and daily closing flows
- persistent mailbox thread-state storage beyond visible quoted text
- production auth/rate limiting on the local API
- robust error taxonomy and retry logic
- panel actions beyond edit/upsert, such as quick enable/disable or delete with confirmation
- live runtime validation of the refreshed panel after container rebuild on the deployed host
- a documented operator workaround or UI note for Roundcube folder visibility differences versus Aurora

## Target Outcomes

### Outcome 1: Reliable request triage

The system should accept pasted text or email-derived text and produce:

- normalized request content
- likely customer/project mapping
- confidence score and open questions

Success criteria:

- known customers map to the expected YouTrack project
- ambiguous requests stop before write operations
- the model can explain what it is about to do in plain language

### Outcome 2: Safe operational preview

The system should translate free-form notes into structured actions without writing immediately.

Actions to support:

- create or update issues
- add work items / tracked time
- create knowledge base entries

Success criteria:

- a preview exists for every commit
- preview IDs are stable enough for explicit approval
- operations requiring confirmation are clearly marked

### Outcome 3: Real commit to YouTrack

Approved previews should create/update real YouTrack objects with audit logs.

Success criteria:

- no duplicate commit on retry of the same preview
- partial failures are visible and do not hide successful operations
- the resulting IDs from YouTrack are stored locally

### Outcome 4: Open WebUI usability

The tool must be understandable and callable by the model from Open WebUI.

Success criteria:

- the model discovers and uses functions without endpoint-specific prompting
- OpenAPI operation names and descriptions are self-explanatory
- the workflow works from a normal user chat, not only direct API calls
- the model can discover read/query tools in a fresh thread without requiring a warm-up conversation

### Outcome 4b: Reliable IMAP execution

The email reader should benefit from YTBot understanding without depending on Open WebUI tool execution reliability.

Success criteria:

- YTBot can read an email thread and return a structured operational plan
- the IMAP caller executes YouTrack endpoints locally instead of waiting for model-side tool completion
- tool-call failures from Open WebUI do not block mailbox automation
- clarification replies can enrich the next execution attempt with better project or issue hints
- IMAP-created issues should have clean title/description metadata and receive the expected default assignee

### Outcome 4c: Operational query assistant

The assistant should answer management and search questions directly from YouTrack context.

Success criteria:

- project hints like `funky` or `SEA` can resolve to the right project without manual IDs
- open issues can be listed with meaningful filters and ranking
- monthly/project time totals can be reported with issue detail
- existing project knowledge can be searched before the model asks unnecessary clarification questions

### Outcome 5: Prompt and skill layer

The model should have a stable operating behavior, not just a reachable API.

This includes:

- system prompts for request triage, safe previewing, and day-closing behavior
- reusable skills/instructions for issue management, worklog recording, knowledge capture, and clarification handling
- explicit decision rules for when to ask questions versus when to proceed

Success criteria:

- the model follows the same workflow consistently across sessions
- prompts reduce wrong writes and improve tool selection
- skills are modular enough to evolve without rewriting the whole setup

### Outcome 5b: Controlled operations dashboard

The local operator should be able to review and adjust runtime configuration without editing files directly on the server.

Success criteria:

- non-secret runtime values are editable through the web panel
- user whitelist and RBAC assignments are manageable through the same interface
- the panel is readable enough to demo to clients or internal stakeholders
- UI changes do not change backend safety rules or bypass API-side enforcement

### Outcome 6: Daily closing assistant

The user should be able to write a single informal end-of-day message and get a clean operational plan.

Example:

```text
oggi ho fatto un'ora di call con SEA, ho risolto il bug di funky per la ricerca, segna 2 ore,
mi serve salvare questo comando "cp -a" tra la knowledge base dei miei script personali
```

Success criteria:

- call time is converted into worklogs
- bugfix work becomes issue or issue update actions
- personal snippets become KB entries in the right location
- any uncertainty becomes an explicit question

## Roadmap

### Phase 1: Stabilize the API contract

- add strong endpoint descriptions for Open WebUI tool discovery
- add request/response examples in OpenAPI
- improve operation naming for model comprehension
- verify `ingest -> preview -> commit` with real YouTrack data
- expose read/query primitives for projects, issues, worklogs, time reports, and knowledge listing

### Phase 2: Prompt and skill foundation

- define the primary system prompt for the assistant role
- define confirmation policy for ambiguous project/time/KB operations
- create initial skills/instruction packs for:
  - mailbox email intake and reply behavior
  - YouTrack project and issue operations
  - worklog extraction from natural language
  - knowledge capture from snippets and notes
  - mailbox triage and clarification loops
- document how prompts and skills interact with backend rules
- keep prompts and skills versioned alongside code in the future private repository

### Phase 3: Improve classification and preview quality

- enrich customer directory with aliases, domains, and default rules
- improve text parsing for issue/worklog/KB extraction
- support references to existing issue IDs more reliably
- add better confirmation questions for low-confidence operations

### Phase 4: Mailbox workflows

- implement mailbox polling or manual fetch endpoint
- normalize incoming mail thread data
- use YTBot as a planner that returns structured execution hints instead of delegating final tool execution to Open WebUI
- let the planner provide explicit issue title/description/assignee metadata for issue creation quality
- support helpdesk-style assist mode for email summary/translation/explanation without forcing ticket creation
- support clarification loops tied to the selected communication channel
- prepare SMTP sending for follow-up questions and summaries

### Phase 5: Production hardening

- add API authentication for local tool access
- define structured logging and error codes
- harden Docker deployment and persistence
- add smoke tests for deployment and health checks
- keep panel dependencies aligned with FastAPI form handling requirements such as `python-multipart`

### Phase 6: Personal operating system

- daily close endpoint optimized for spoken/written notes
- reusable knowledge capture flows
- client-specific conventions and templates
- optional weekly review/report generation

## Working Rules

- never write to YouTrack directly from free text without a preview step
- prefer asking one clear question over making a wrong project assignment
- keep business rules in the backend, not only in model prompts
- preserve a local audit trail for every write attempt
- optimize for solo-work practicality over enterprise complexity
- for mailbox automation, prefer a planner/executor split: model decides, backend executes
- keep `.env` limited to secrets/bootstrap values, and keep mutable runtime settings in JSON-backed storage
- when debugging mailbox behavior, trust server/runtime logs and cross-check with more than one mail client before blaming backend state
- after every relevant code change, update `AI_GUIDE.md` and `WORKLOG_AI.md`

## Next Recommended Tasks

- improve OpenAPI descriptions so Open WebUI recognizes tools more naturally
- refine the YTBot planner prompt so IMAP replies produce better project and issue hints
- validate the exact YouTrack assignee-field behavior on the real tenant if `developers` needs a different identifier than the current login-style payload
- validate fresh-thread tool recognition in Open WebUI using the new query/listing endpoints
- define the first skill set for issue creation, worklog logging, and KB capture
- test query/reporting endpoints with real client-like prompts from new chats
- define the first real customer directory entries
- add persistent thread-state storage for email clarification loops
- connect the prompt and skill assets to the actual Open WebUI assistant configuration
- rebuild and smoke-test the deployed container so the new panel UX is visible on `http://192.168.69.6:8086/panel`
- add quick user actions in the panel if operations need faster enable/disable flows
- decide whether to document Roundcube as unsupported for folder visibility or to add provider-specific mailbox notes

## Repo Plan

- use this repository as the working source of truth for now
- once the backend and prompts stabilize, create a private GitHub repository
- migrate backlog, code, and deployment notes there without changing the current local structure first
