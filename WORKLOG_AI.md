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

## 2026-03-23 11:10

Context:
- The active bug queue included a panel save crash when editing runtime settings and a mailbox clarification problem where reply emails lost too much context for subsequent user responses.

Changes:
- Fixed the runtime settings save path by restoring the missing `logging` import used by `RuntimeConfigService.update()`, which was a likely cause of the `/panel/settings` internal server error when toggling flags like `VERBOSE`.
- Improved clarification replies so they now include an explicit "Contesto operativo" block built from the current interpreted request, making the outgoing email itself more self-contained.
- Updated the SMTP reply flow to preserve thread context by appending a quoted original-message block and setting `In-Reply-To` / `References` headers when replying.
- Added focused regression tests for runtime config updates, clarification reply content, and reply-body thread preservation.
- Mirrored the same fixes and tests into `lada/`.

Verification:
- Ran `python3 -m py_compile app/services.py app/mailbox.py app/mail_agent.py tests/test_services.py`.
- Attempted targeted `unittest` cases for the touched paths, but this environment still lacks `pydantic`, so import-based tests could not execute here.

Open points:
- Bug 1 and bug 3 still need live validation after deploy to confirm the panel save no longer errors and that clarification follow-ups actually preserve enough thread context in real clients.
- This does not yet implement a persistent mailbox conversation model; it improves transport-level context retention only.

## 2026-03-23 11:45

Context:
- After live confirmation that bug 1 and bug 3 appear resolved, the remaining long-term thread-memory idea needed to be separated from bug tracking and work began on bug 2 around fragile assignee application.

Changes:
- Marked bug 1 as resolved and bug 3 as resolved with short-term mitigation in `BUG_LOG.md`.
- Extracted the medium/long-term mailbox thread-state architecture into `PLANNING_FEATURES.md`.
- Started hardening assignee application by prioritizing the configured/exact assignee field over generic user-like fields and by making assignee value attempts more explicit and better logged.
- Mirrored the same assignee-priority changes into `lada/`.

Verification:
- Planned verification path is syntax validation plus live retest against the tenant/project combinations that previously produced assignee uncertainty.

Open points:
- Bug 2 is still in progress and needs validation against the real YouTrack tenant.
- The new planning file is intentionally product-facing and should stay separate from bug status noise.

## 2026-03-23 12:20

Context:
- A new proposed "Intelligent YouTrack agent layer" needed to be compared against the real codebase so we could tell what is truly missing versus what already exists in partial form.

Changes:
- Reviewed the proposal against the current implementation in project matching, assistant context endpoints, preview/commit safety, and assignee metadata handling.
- Expanded `PLANNING_FEATURES.md` with an explicit analysis of what is already implemented, what is partial, and what is still missing.
- Added a planned feature track for a generic metadata resolver layer plus a candidate `POST /resolve-value` endpoint.
- Documented that the main architectural gap is not project inference itself, but generic metadata/options resolution before writes.

Verification:
- Cross-checked the proposal against `ProjectMatcher`, `QueryService`, current assistant endpoints, issue custom-field handling, preview enforcement, and ambiguity/confirmation logic.

Open points:
- The proposed resolver endpoint still needs concrete API models and scope boundaries.
- Bug 2 remains related, because assignee resolution is one of the first write-time metadata cases that should migrate onto the future generic resolver.

## 2026-03-23 12:45

Context:
- Follow-up planning clarified that prompt-quality work should not remain tracked as a standalone bug and that the OpenAPI tool surface needs an explicit completeness review across Project, Issue, TimeTracking, and KnowledgeBase.

Changes:
- Reclassified the former "task generation quality" bug into planned feature work inside `PLANNING_FEATURES.md`.
- Added a dedicated planning section for completing the YouTrack OpenAPI surface, explicitly excluding destructive `DELETE` flows.
- Recorded the current gap analysis: good baseline coverage already exists, but metadata/transitions/KB direct operations are still incomplete.

Verification:
- Reviewed current FastAPI routes and service/client capabilities to compare exposed tools versus the target operational domains.

Open points:
- We still need to decide whether to implement the missing endpoints directly now or first finish the generic metadata resolver that many of those endpoints would depend on.

## 2026-03-23 14:35

Context:
- Live BrowserOS inspection confirmed that the model still could not assign an issue because the OpenAPI surface only exposed `edit_issue` for summary/description plus the indirect preview/commit path.

Changes:
- Expanded the OpenAPI/backend surface with explicit metadata-aware issue tools:
- `GET /projects/{project_id}`
- `GET /issues/{issue_id}/fields`
- `GET /issues/{issue_id}/transitions`
- `POST /issues/{issue_id}/assignee`
- `POST /issues/{issue_id}/state`
- `POST /resolve-value`
- Added typed request/response models so the generated OpenAPI describes these operations clearly to the model.
- Extended the YouTrack client to fetch detailed issue custom fields and support command application plumbing.
- Added service-layer resolution helpers for issue field metadata, transitions, assignee assignment, state updates, and generic value resolution.
- Synced the updated API surface into `lada/`.

Verification:
- Ran `python3 -m py_compile app/models.py app/clients.py app/services.py app/main.py tests/test_services.py lada/app/models.py lada/app/clients.py lada/app/services.py lada/app/main.py lada/tests/test_services.py`.
- Inspected the live `openapi.json` from BrowserOS before implementation to confirm the previous tool surface really lacked explicit assignee/custom-field/state endpoints.

Open points:
- The live server still needs redeploy before BrowserOS/Open WebUI can see the new OpenAPI surface.
- Knowledge Base direct create/read/update endpoints are still not fully exposed as first-class tools.

## 2026-03-20 18:20

Context:
- The latest trusted-channel and presentation-layer refactors needed to be mirrored into the mounted `lada/` deployment workspace and the local repository needed a cleanup pass before commit.

Changes:
- Synced the updated environment example, documentation, trusted Open WebUI channel changes, presentation-layer files, and focused auth test into `lada/`.
- Recorded the rule that `lada/` must stay aligned with root presentation/orchestration changes in project memory.
- Identified macOS metadata artifacts (`.DS_Store` and `._*`) in the local workspace so they can be removed before committing.

Verification:
- Confirmed the mirrored `lada/app/main.py` imports `app.presentation.panel_views`.
- Confirmed the mirrored `lada/` tree contains the new `app/presentation/` package and `tests/test_api_auth.py`.

Open points:
- Remove the local macOS metadata files before creating the commit.
- Commit and push the current project state after cleanup.

## 2026-03-20 17:58

Context:
- Open WebUI chat calls were failing with `401 Missing X-Actor-Email header`, which mixed user-facing OI chat with the stricter mailbox trust model.
- The architecture needed an explicit split between trusted chatbot execution and guarded email execution.

Changes:
- Added a configurable trusted Open WebUI actor path so chat/tool calls can run without `X-Actor-Email` when `OPENWEBUI_TRUSTED_CHANNEL_ENABLED=true`.
- Kept whitelist/RBAC behavior intact whenever `X-Actor-Email` is explicitly provided, so user-scoped API calls still use the real directory.
- Prevented the trusted chat actor from being persisted as an issue subscription requester during commit flows.
- Documented the channel split in `.env.example`, `README.md`, and `AI_GUIDE.md`.
- Added targeted tests for trusted actor fallback, disabled-mode `401`, and explicit-header whitelist resolution.

Verification:
- Ran `PYTHONPYCACHEPREFIX=/tmp/pycache python3 -m py_compile app/config.py app/main.py app/models.py tests/test_api_auth.py`.
- Attempted `python3 -m unittest tests.test_api_auth`, but this environment does not currently have `fastapi` installed, so import-based API tests could not run here.

Open points:
- A live Open WebUI retest is still needed to confirm the assistant no longer asks the user for YouTrack email/header context during normal chat usage.
- If the API is exposed beyond the trusted OI environment, the trusted channel toggle must stay deliberate and deployment-specific.

## 2026-03-20 18:12

Context:
- `app/main.py` had accumulated inline panel HTML/CSS rendering, which mixed presentation concerns with FastAPI orchestration and made the module harder to evolve.

Changes:
- Introduced an enterprise-style presentation layer under `app/presentation/`.
- Moved panel rendering helpers and inline styling into `app/presentation/panel_views.py`.
- Kept `app/main.py` focused on routing, auth, orchestration, and response wiring by importing `render_login_page` and `render_panel`.

Verification:
- Planned verification is syntax/import validation after the refactor plus a quick runtime panel smoke test.

Open points:
- The panel still uses string-based HTML rendering; if the UI grows further, a next step could be moving from presentation helpers to actual template files under the same presentation layer.

## 2026-03-20 15:05

Context:
- The mailbox workflow needed a real production-like debug pass because IMAP folders appeared missing in webmail and already-processed messages kept resurfacing in `INBOX`.

Changes:
- Added panel-visible application logs backed by `data/app.log` plus an in-memory recent log buffer, so runtime issues can be inspected directly from `/panel`.
- Added IMAP startup bootstrap so runtime folders are ensured on application start, not only during fetch/move flows.
- Fixed duplicate-mail handling so messages already present in local processing records are marked `Seen` and moved to the appropriate operational folder instead of being re-read every poll cycle.
- Iterated on IMAP folder handling after live validation: first exposed that the provider rejects our `LIST` patterns, then removed `LIST` as a hard dependency and relied on `CREATE`/`ALREADYEXISTS` plus `SUBSCRIBE`.
- Verified with BrowserOS that Aurora shows `FAILED`, `PROCESSED`, `PROCESSING`, and `REJECTED`, which confirms the backend-side mailbox workflow is working and that Roundcube is the client-specific weak point.
- Mirrored all relevant mailbox/panel-debug changes into `lada/`.

Verification:
- Ran `python3 -m py_compile app/mail_agent.py lada/app/mail_agent.py app/mailbox.py lada/app/mailbox.py app/main.py lada/app/main.py app/logging_utils.py lada/app/logging_utils.py`.
- Inspected `/panel` logs live during multiple redeploys and confirmed successful folder bootstrap, subscription, zero unseen messages after duplicate finalization, and stable mail polling cycles.
- Inspected the same mailbox in Roundcube and Aurora through BrowserOS; Aurora displayed the runtime folders while Roundcube did not.

Open points:
- If Roundcube must remain the reference client, we may need a provider/client-specific note or workaround for folder visibility.
- We still need to commit and push this mailbox-debug package once documentation is aligned.

## 2026-03-20 10:20

Context:
- The project had just gained runtime config separation, whitelist/RBAC, admin approval, and a minimal panel, but the documentation did not yet reflect the real operating model.
- The panel also needed a client-presentable layout and actual user editing flow instead of a bare static form.

Changes:
- Refined the web panel UI into a branded, client-facing dashboard aligned with the Acme palette and links to `acmemk.com` and `chatnorris.it`.
- Added real whitelist editing support: user rows now expose `Edit`, the form supports canonical email changes through `original_email`, and storage/repository helpers now support safe record replacement.
- Reworked the panel layout to a one-column flow with metric cards under the header, `Whitelisted users` first, add/edit user in a modal, and collapsible runtime/secret sections.
- Preserved the same backend safety model while improving the panel UX, and mirrored all relevant changes into `lada/`.
- Updated `AI_GUIDE.md` and `README.md` so runtime/secrets split, RBAC, admin approval, panel routes, deploy notes, and current constraints are captured in repo memory.

Verification:
- Ran `python3 -m py_compile app/main.py app/services.py app/repositories.py app/storage.py lada/app/main.py lada/app/services.py lada/app/repositories.py lada/app/storage.py`.
- Checked the live BrowserOS tab and confirmed the deployed container still shows the previous UI until rebuild/redeploy.
- Reviewed `acmemk.com` in BrowserOS to align the panel palette with the current brand direction.

Open points:
- The deployed container still needs rebuild/restart before the new panel UI is visible on `192.168.69.6:8086`.
- Quick user actions such as enable/disable or delete are still optional follow-up work.

## 2026-03-19 11:40

Context:
- The backend needed the first full query layer so YTBot could search context autonomously instead of relying on highly structured user prompts.
- We also needed to separate everyday email helpdesk assistance from explicit YouTrack execution.

Changes:
- Added query/search/reporting primitives for projects, issues, time tracking, articles, and assistant-oriented project context.
- Added direct work item creation so Open WebUI no longer perceives a missing write tool when the issue is already known.
- Added ranking and normalization logic for project search and issue search so fresh chats can discover relevant context with fewer user clarifications.
- Updated prompts and skills to push the model toward `search first, ask later` behavior and to use assist-mode for noisy forwarded emails.
- Extended the email planner schema with `workflow_mode` and `assist_intent`, so mailbox automation can summarize/translate/explain emails without creating YouTrack tickets by default.
- Updated tests to cover project ranking, open issue listing, project time summaries, project context building, direct work item creation, and mail assist mode.

Verification:
- Planned verification path includes `python3 -m py_compile` on root and `lada`, plus runtime tests where dependencies are available.

Open points:
- Real-tenant validation is still needed for issue/article search query behavior and for the exact Open WebUI fresh-thread discoverability improvements.

## 2026-03-19 12:05

Context:
- A live tenant error showed that assignee updates were still assuming the wrong custom field name (`Assignee`) even though the actual compatible field looked project-specific.

Changes:
- Updated assignee assignment to fetch issue custom fields dynamically and prefer compatible user/team fields exposed by the issue itself.
- Kept configured field-name fallback, but now try real issue field candidates first so project-specific names like `ZD_SEA Team` can be used automatically.
- Updated tests to reflect a tenant where the valid field is not named `Assignee`.

Verification:
- Planned verification path includes `py_compile` on root and `lada`, plus a live tenant retry on assignee application.

Open points:
- We still need one real execution to confirm the tenant accepts the detected field candidate with the configured login `acmemediakits`.

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
