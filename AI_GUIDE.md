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

Not yet complete:

- richer OpenAPI descriptions/examples for better tool discovery in Open WebUI
- real mailbox sync workflows beyond basic IMAP service support
- SMTP actions and outbound clarification messages
- stronger parsing for daily summaries and mixed worklog narratives
- dedicated system prompts for role, behavior, and confirmation strategy
- reusable skills and prompt assets for YouTrack, mailbox triage, and daily closing flows
- production auth/rate limiting on the local API
- robust error taxonomy and retry logic

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

### Phase 2: Prompt and skill foundation

- define the primary system prompt for the assistant role
- define confirmation policy for ambiguous project/time/KB operations
- create initial skills/instruction packs for:
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
- support clarification loops tied to the selected communication channel
- prepare SMTP sending for follow-up questions and summaries

### Phase 5: Production hardening

- add API authentication for local tool access
- define structured logging and error codes
- harden Docker deployment and persistence
- add smoke tests for deployment and health checks

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

## Next Recommended Tasks

- improve OpenAPI descriptions so Open WebUI recognizes tools more naturally
- draft the first system prompt for the assistant's operational behavior
- define the first skill set for issue creation, worklog logging, and KB capture
- test `POST /requests/ingest` and `POST /actions/preview` with real client-like inputs
- define the first real customer directory entries
- decide whether mailbox ingestion should be pull-based or triggered manually from Open WebUI
- connect the prompt and skill assets to the actual Open WebUI assistant configuration

## Repo Plan

- use this repository as the working source of truth for now
- once the backend and prompts stabilize, create a private GitHub repository
- migrate backlog, code, and deployment notes there without changing the current local structure first
