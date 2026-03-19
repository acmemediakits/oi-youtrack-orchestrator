# AI Worklog

## How To Use

This file is the running log for AI-assisted work on the project.

Use it to record:

- what changed
- why it changed
- what was verified
- what is still blocked or uncertain

Append new entries at the top.

## Template

```md
## YYYY-MM-DD HH:MM

Context:
- short description of the task

Changes:
- concrete implementation changes

Verification:
- commands run, manual checks, or screenshots observed

Open points:
- blockers, risks, or next steps
```

## 2026-03-17 17:45

Context:
- IMAP-created issues still had noisy title/description text and were not being assigned to `developers`.

Changes:
- Extended the YTBot execution plan schema with explicit `issue_summary`, `issue_description`, and `issue_assignee`.
- Updated the planner prompt so it produces concise Italian issue titles, clean business descriptions, and defaults assignment to `developers`.
- Applied planner-provided issue metadata back onto the generated preview before commit, so the final YouTrack write uses the refined title and description.
- Added assignee configuration and passed the assignee to YouTrack through the assignee custom field payload on issue creation.
- Extended tests to assert planner-driven summary, description, and assignee propagation.
- Updated `.env.example` and `AI_GUIDE.md` so this behavior is documented for future context recovery.

Verification:
- Ran `python3 -m py_compile app/mail_agent.py app/dependencies.py app/main.py app/models.py app/clients.py app/services.py app/config.py tests/test_services.py`.

Open points:
- The exact assignee field payload may still need one validation on the real YouTrack tenant if it expects a different field type or identifier for `developers`.

## 2026-03-17 18:00

Context:
- The IMAP bot was still sending an anxious pre-commit confirmation email and the assignee payload could block issue creation with a 400.

Changes:
- Stopped using optimistic planner `reply_draft` text for successful execute flows; email replies now derive from the real commit result and include the actual created issue reference.
- Changed issue assignment to a second best-effort step after issue creation, so a bad assignee payload no longer prevents the issue from being created.
- Added fallback assignee update variants (`login`, `name`, `fullName`) to improve compatibility with tenant-specific YouTrack user payload expectations.
- Tightened commit status evaluation so all-error runs end as `blocked` instead of appearing as partial success.
- Updated tests to verify post-commit reply behavior and separate assignee update attempts.

Verification:
- Ran `python3 -m py_compile app/mail_agent.py app/services.py tests/test_services.py`.

Open points:
- The exact assignee update variant that works on the real tenant still needs a live validation, even though issue creation is now protected from assignee-related failure.

## 2026-03-17 18:10

Context:
- A YouTrack user card confirmed that the visible assignee label is `developers` while the underlying username/login appears to be `acmemediakits`.

Changes:
- Added `YOUTRACK_DEFAULT_ASSIGNEE_LOGIN` so assignee updates can use an explicit login instead of guessing from the display label.
- Switched the first assignee update attempt to prefer the configured login value before trying label-based fallbacks.
- Updated `.env.example`, tests, and `AI_GUIDE.md` to preserve this tenant-specific mapping in project memory.

Verification:
- Covered the configured login path in the mail automation test fixture.

Open points:
- A live tenant check is still useful to confirm that `acmemediakits` is accepted exactly as the assignee login by the production YouTrack API.

## 2026-03-17 17:20

Context:
- The IMAP reader could not rely on Open WebUI tool-calling for email-driven YouTrack actions.
- We needed a more reliable hybrid design and better project memory in the repo documentation.

Changes:
- Refactored the mail automation flow so the IMAP caller can ask YTBot for a structured JSON execution plan.
- Kept YouTrack execution local in the backend through the existing ingest, preview, commit, and direct issue/worklog endpoints.
- Added planner fallback logic so a bad Open WebUI reply or tool-call response falls back to deterministic local handling.
- Added project-hint resolution against real YouTrack project listings to help emails that name the project in natural language.
- Updated tests for planner-driven execution, clarification behavior, duplicate skipping, and tool-call fallback.
- Updated `AI_GUIDE.md` to record the planner/executor architecture and the rule to refresh project memory files after changes.

Verification:
- Ran `python3 -m py_compile app/mail_agent.py app/dependencies.py app/main.py app/models.py app/clients.py tests/test_services.py`.
- In this environment, full Python tests could not run because project dependencies such as `pydantic` and `pytest` are not installed.

Open points:
- Clarification loops still rely mainly on the visible email body and quoted thread; persistent thread-state storage is still needed.
- The YTBot planner prompt should be refined with more real examples from production mail threads.

## 2026-03-13 12:35

Context:
- Bootstrapped the v1 backend for Open WebUI and YouTrack orchestration.
- Aligned deployment assumptions with the Lada Docker host.

Changes:
- Added FastAPI application with endpoints for ingest, preview, commit, health, and projects.
- Added local JSON persistence for requests, previews, and commit audit logs.
- Added YouTrack client support for project listing, issue create/update, work items, and articles.
- Added deterministic parsing/matching for initial customer/project resolution.
- Added Docker packaging for deployment on the Lada host.
- Prepared project files inside the mounted deployment directory used by Docker build context.
- Added project guidance and roadmap in `AI_GUIDE.md`.
- Added first local prompt/skill asset structure in `prompts/` and `skills/`.
- Added email-intake prompting direction for mailbox-driven YTBot behavior.

Verification:
- Confirmed `/openapi.json` is reachable at `http://192.168.69.6:8086/openapi.json`.
- Confirmed `/projects` returns real YouTrack projects from the production-like environment.
- Confirmed the Open WebUI connection can reach the tool server.

Open points:
- Open WebUI tool discoverability should be improved with stronger OpenAPI descriptions and examples.
- Preview and commit flows should be validated with real end-to-end examples.
- Mailbox ingestion and SMTP-driven clarification flows are not production-ready yet.
- System prompt design and reusable skill design are now explicit project work items.
