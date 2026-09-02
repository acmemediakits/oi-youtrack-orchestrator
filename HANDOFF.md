# Project Handoff

## Purpose

This repository is the current YouTrack tool-core and email-channel implementation that should be carried into the broader shared-agent project described in `AgentChatNorris.md`.

The immediate product provides:

- a FastAPI/OpenAPI tool surface for YouTrack projects, issues, time tracking, and knowledge-base operations
- semantic project and metadata resolution before writes
- preview/commit safety primitives
- an IMAP/SMTP email channel with polling, folder lifecycle, thread cleanup, replies, and execution audit
- a small operations panel for runtime settings, users, and logs
- JSON or PostgreSQL operational-state persistence

## Canonical Source

- Repository: `https://github.com/acmemediakits/oi-youtrack-orchestrator.git`
- Transfer branch: `codex-split-tool-cores`
- Stable pre-refactor branch: `main`
- Do not continue from a raw copy of this workspace unless GitHub is unavailable.
- Do not merge the transfer branch into `main` until its runtime and unit tests have been revalidated.

The transfer branch contains the first architectural separation between:

- `services/youtrack_core`: YouTrack-facing tool service
- `services/email_channel`: asynchronous mailbox adapter
- `app/main.py`: compatibility monolith and temporary panel host

## Architectural Direction

The target is a monorepo of separately deployable services:

1. Tool cores expose narrow, channel-agnostic capabilities.
2. Channel adapters normalize transport-specific input and output.
3. The shared agent runtime owns model routing, prompts, skills, KB retrieval, policy, and tool orchestration.
4. The operations surface owns configuration, health, logs, audit, and approvals.

Open WebUI is currently the model/orchestration bridge used by this project. The broader target in `AgentChatNorris.md` is a proprietary shared runtime where Open WebUI can remain a provider/UI component without being the sole system brain.

Future services already identified:

- `db-core`: safe SQL and schema tools
- `nextcloud-core`: calendar and document tools
- `docgen-core`: Markdown to DOCX/XLSX/PDF/PPTX transformations

## Current Implementation State

Implemented and important:

- project list/search/detail, description update, and archive/restore
- issue search/read/create/edit, field metadata, transitions, assignee update, and state update
- dynamic YouTrack user-bundle resolution for real assignable users
- work-item creation/list/edit and project time reports
- knowledge search and preview/commit creation flow
- generic `/resolve-value` metadata resolver
- OpenAPI descriptions for preview and commit operations
- Markdown-capable issue and knowledge content; worklog text remains plain
- branded web panel with runtime settings, whitelist management, and application logs
- IMAP startup folder bootstrap and subscription
- duplicate-email finalization and processing folders
- email subject/body cleanup for spam tags, quoted threads, signatures, and unsubscribe noise
- planner JSON recovery when OpenWebUI wraps JSON in prose
- `EMAIL_PERMISSIONS_ENFORCED` feature flag for development/demo versus guarded email execution
- state backend switch through `STATE_BACKEND=json|postgres`

The compatibility deployment still starts `app.main:app`, so its existing OpenAPI endpoints remain available while the service split progresses.

## Persistence

PostgreSQL is the intended operational-state backend.

Last known deployment setup:

- dedicated database: `assistant_ops`
- dedicated role: `assistant_rw`
- PostgreSQL is hosted separately from the OpenWebUI database
- application storage uses the generic `state_store` JSONB table, namespaced by repository type

Never reuse or commit database credentials. Configure `DATABASE_URL` only in the deployment secret source. The dedicated database password should be rotated before the next handoff/deployment because it appeared in earlier local operational context.

The JSON backend remains available for local development and migration compatibility. There is no automatic JSON-to-PostgreSQL importer yet.

## Runtime And Deploy

Last verified Lada state was recorded on 2026-03-31, not on the handoff date. At that time:

- host: `192.168.69.6`, reachable only in the expected VPN/network context
- SSH convention: `ssh -i ~/.ssh/hank -o IdentitiesOnly=yes hank@192.168.69.6`
- container: `acme_youtrack_api`
- public port: `8086:8000`
- PostgreSQL container: `postgre_sql`, host mapping `8080:5432`
- application reached `Application startup complete`
- IMAP folder bootstrap and mail polling started successfully

Revalidate before making changes:

```bash
curl -fsS http://192.168.69.6:8086/health
curl -fsS http://192.168.69.6:8086/openapi.json
ssh -i ~/.ssh/hank -o IdentitiesOnly=yes hank@192.168.69.6 \
  'docker ps --filter name=acme_youtrack_api --filter name=postgre_sql'
```

Never copy `.env`, `data/`, database dumps, mailbox contents, or private keys into Git or a handoff archive.

## Verification Status

Verified locally during handoff:

```bash
python3 -m py_compile app/*.py app/presentation/*.py \
  services/youtrack_core/*.py services/email_channel/*.py \
  tests/test_services.py tests/test_api_auth.py
```

This passes.

The full unit suite could not run in the current global Python environment because `pydantic` and `fastapi` are missing. A receiving agent should create a virtual environment and run:

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m unittest tests.test_services tests.test_api_auth
```

Then build and smoke-test the Docker image before merging.

## Known Risks And Open Work

Highest priority:

1. Run the complete test suite with project dependencies installed.
2. Revalidate the live Lada deployment and email end-to-end flow.
3. Rotate the PostgreSQL application password and keep it only in deployment secrets.
4. Decide the exact contract between the future shared agent runtime and `email_channel`.
5. Finish extracting panel/ops from the compatibility monolith.

Architecture gaps:

- email still receives a structured JSON plan instead of participating in the exact same tool-driven runtime path as interactive chat
- persistent email thread memory is planned but not implemented
- PostgreSQL uses a generic state table; migrations and specialized relational repositories are not implemented
- direct Knowledge Base create/read/update coverage is incomplete compared with Project, Issue, and TimeTracking
- service-wide auth, error envelopes, retries, rate limiting, tracing, and audit policy need normalization
- `EMAIL_PERMISSIONS_ENFORCED=false` is useful for demos but is not a production-safe default

Product-quality gaps:

- issue summary/description generation needs continued evaluation on real requests
- assignee behavior should be rechecked when project custom fields change
- metadata resolver aliases and confidence thresholds need broader tenant coverage

Use `BUG_LOG.md` for defect history and `PLANNING_FEATURES.md` for planned capabilities. Some entries are historical; confirm current code and runtime before reopening or closing them.

## Important Files

- `README.md`: setup and operator-facing overview
- `AI_GUIDE.md`: implementation memory and operating rules
- `WORKLOG_AI.md`: chronological work history
- `BUG_LOG.md`: bugs and resolutions
- `PLANNING_FEATURES.md`: feature roadmap
- `AgentChatNorris.md`: broader shared-agent product vision
- `app/main.py`: current compatibility API and panel host
- `app/services.py`: domain behavior and YouTrack action logic
- `app/mail_agent.py`: email workflow
- `app/email_orchestrator.py`: OpenWebUI email planning bridge
- `app/storage.py`: JSON/PostgreSQL state abstraction
- `prompts/` and `skills/`: current prompt/skill assets
- `services/`: initial deployable service boundaries

## Suggested First Prompt For The Receiving Agent

```text
Continue the AgentChatNorris shared-agent initiative from this repository.

Start by reading HANDOFF.md, AgentChatNorris.md, AI_GUIDE.md, README.md,
PLANNING_FEATURES.md, BUG_LOG.md, and the newest WORKLOG_AI.md entries.

Work from branch codex-split-tool-cores. Do not merge to main yet.
First install dependencies and run the complete test suite. Then inspect the
current service boundaries and propose the smallest next slice that moves
email orchestration into the shared runtime while preserving the existing
YouTrack OpenAPI surface and live compatibility deployment.

Do not read, print, copy, or commit secrets. Treat the last recorded Lada state
as historical until health, OpenAPI, containers, and logs are reverified.
```

## Transfer Rule

Use commit and push as the primary transfer. If a standalone artifact is required, generate it from the committed tree:

```bash
git archive --format=zip --output=oi-youtrack-orchestrator-handoff.zip \
  codex-split-tool-cores
```

This archive excludes `.git`, ignored runtime data, ignored `lada/` mirrors, `.env`, and other untracked local artifacts by construction.
