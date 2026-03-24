# Planning Features

## 2026-03-23

### Mail thread state model

- Status: planned
- Source: extracted from bug `Email thread context is lost across clarification replies`
- Priority: medium / long term

Goal:
- Move from transport-level context preservation to a real lightweight conversation-memory model for mailbox workflows.

Why:
- The short-term reply quoting fix helps, but it still depends on client behavior and visible quoted text.
- Clarification, delegation, follow-up, escalation, and issue-update flows need a more durable thread model.

Proposed direction:
- Keep IMAP as source of truth for full message bodies.
- Use local storage as an operational index, not as a full mailbox mirror.
- Model:
- `main_thread`: canonical case/workstream anchored to the root message or first known thread identifier
- `sub_thread`: branch for clarification, delegation, follow-up, escalation, or issue update
- `timeline/meta`: compact append-only state changes and pointers

Suggested indexed fields:
- root / anchor message ids
- normalized subject
- participants
- current summary / resume
- topics
- linked YouTrack issue ids
- open questions
- actions already taken
- current status
- last seen timestamp

Outcome:
- The agent should be able to reconstruct the original request, prior clarifications, and downstream YouTrack actions without relying only on quoted email text.

## 2026-03-23

### Intelligent YouTrack agent layer

- Status: planned
- Source: external product/agent improvement proposal, reviewed against the current repo
- Priority: medium

Assessment:
- The proposal makes sense overall.
- It is not a greenfield feature: several parts already exist in partial form.
- The main missing piece is a generic metadata-resolution layer before writes, not basic project search itself.
- Some of the current bugs are symptoms of this gap:
- assignee application is still fragile because metadata resolution is partly dynamic but not yet standardized
- natural-language project inference exists, but value resolution for statuses, transitions, fields, and similar write-time metadata is not generalized

Current state vs proposal:
- `Context tools`
- already present:
- project list via `/projects`
- project search via `/projects/search`
- assistant context via `/assistant/project-context`
- issue detail via `/issues/{issue_id}`
- issue custom fields exist internally via `YouTrackClient.list_issue_custom_fields(...)`
- missing:
- public endpoint for issue fields / writable metadata
- public endpoint for issue transitions
- richer project metadata endpoint
- `Semantic mapping layer`
- already present:
- alias/domain project matching in `ProjectMatcher`
- confidence-based ranking in `ProjectMatcher` and `QueryService.search_projects`
- fallback to clarification via `needs_confirmation`, `open_questions`, and preview blocking
- missing:
- generic fuzzy resolution for values like status, transition, priority, assignee, and custom-field options
- reusable semantic resolver instead of one-off project matching logic
- `Project memory layer`
- already present:
- customer alias storage and domain mapping in the customer directory repository
- partial assistant-oriented context assembly in `build_project_context(...)`
- missing:
- stronger project memory enrichment for descriptions, conventions, and write-time defaults
- `Action pipeline`
- already present:
- `ingest -> preview -> commit`
- mail planner flow already approximates `intent -> context -> preview -> commit`
- missing:
- explicit standardized internal pipeline of `intent -> context -> options -> mapping -> preview -> commit`
- reusable mapping/options stage for metadata-dependent writes
- `Safety layer`
- already present:
- preview enforcement
- ambiguity detection for project matching
- confidence fields and confirmation gates
- missing:
- standardized confidence thresholds for metadata resolution beyond project selection
- write-time guarantees that invalid statuses/fields/transitions are resolved before commit

Recommendation:
- Add this as an incremental architecture track, not a rewrite.
- Prioritize the metadata-resolution slice first, because it directly reduces invalid write errors and LLM hallucination.

Recommended phases:
- Phase 1: expose metadata read tools
- add endpoints for project metadata, issue fields, and issue transitions
- keep them read-only and explicit so the assistant can inspect legal values before proposing writes
- Phase 2: introduce a generic resolver layer
- implement semantic resolution for `status`, `transition`, `assignee`, and selected custom fields
- reuse confidence scoring, alias dictionaries, and clarification fallback patterns already used for projects
- Phase 3: wire the resolver into writes
- every write path that depends on project-specific values should resolve metadata before commit
- if confidence is low or ambiguous, stop at preview/clarification
- Phase 4: enrich project memory
- store project aliases, domains, conventions, and descriptive hints that improve summary/description generation and default routing
- Phase 5: standardize the pipeline
- formalize `intent -> context -> options -> mapping -> preview -> commit` as shared orchestration, rather than keeping similar logic split across mail, preview, and commit codepaths

Candidate endpoint:
- `POST /resolve-value`

Example request:
```json
{
  "type": "status",
  "input": "risolto",
  "project": "FS"
}
```

Suggested backend behavior:
- fetch valid metadata for the requested scope first
- run fuzzy/alias matching against legal values only
- return ranked candidates plus score and ambiguity hints

Suggested response shape:
```json
{
  "type": "status",
  "input": "risolto",
  "project_id": "FS",
  "candidates": [
    {
      "id": "state-resolved",
      "name": "Resolved",
      "score": 0.93,
      "reason": "language alias + fuzzy match"
    }
  ],
  "selected": {
    "id": "state-resolved",
    "name": "Resolved",
    "score": 0.93
  },
  "ambiguous": false,
  "needs_clarification": false
}
```

Why this endpoint is worth adding:
- It reduces LLM-side hallucination because the model no longer invents project-specific values.
- It reduces write variability because mapping happens against real metadata.
- It fits the current architecture well because preview/commit safety is already present; what is missing is a reusable resolver stage before commit.

Implementation note:
- This should not be limited to status forever.
- A better long-term shape is a generic resolver service with a narrow initial type set:
- `status`
- `transition`
- `assignee`
- `issue_field`
- `priority`

Conclusion:
- Yes, the proposal has strong product and reliability value.
- No, it is not entirely missing today: project search, aliasing, preview enforcement, and ambiguity handling already exist.
- The actual gap is a generalized metadata/options resolver, and that should now be considered a planned feature rather than an ad hoc bug fix.

## 2026-03-23

### Prompt and planning quality upgrade

- Status: in progress
- Source: extracted from former bug `Task generation quality is still too weak for production use`
- Priority: medium

Goal:
- Improve the quality of AI-generated summaries, descriptions, and operational plans without treating the problem as an isolated bugfix.

Current implementation slice:
- stronger planner prompt rules for issue title/body separation
- backend normalization of planner-provided `issue_summary` and `issue_description`
- preview-layer extraction of explicit title/description from operator commands like `crea issue ... con descrizione ...`

Why:
- We already established during debugging that prompt changes are part of the correct solution path.
- The issue is product behavior and planning quality, not only a malformed output edge case.
- This work should stay aligned with the future metadata resolver, because better prompts without valid option resolution still leave write-time fragility.

Scope:
- strengthen summary vs description separation
- improve request-to-ticket interpretation from whole thread context
- reduce sterile paraphrase
- align prompts with real backend constraints and resolver tools
- validate on real examples, not only synthetic cases

Implementation note:
- This must not ship as a standalone disconnected prompt tweak.
- It should be planned together with the intelligent agent layer and metadata-resolution work so the model can reason over real options instead of inventing them.

## 2026-03-23

### YouTrack OpenAPI surface completion

- Status: planned
- Source: current architecture review
- Priority: high

Goal:
- Ensure the tool surface is effectively complete for the four operational domains:
- `Project`
- `Issue`
- `TimeTracking`
- `KnowledgeBase`
- with the deliberate exception of destructive `DELETE` flows.

Current implementation slice:
- project metadata editing endpoint so the assistant can write project descriptions as context hints
- project archive/restore endpoint through project state update
- project search responses now include a `context` attribute and use it in confidence scoring

Assessment of current coverage:
- `Project`
- already exposed:
- list projects: `/projects`
- search projects: `/projects/search`
- assistant project context: `/assistant/project-context`
- missing or incomplete:
- project metadata/details endpoint
- project field metadata endpoint
- project transition/workflow metadata where relevant
- direct project-scoped write/update operations are effectively absent
- `Issue`
- already exposed:
- get issue: `/issues/{issue_id}`
- edit issue summary/description: `/issues/{issue_id}/edit`
- search issues: `/issues/search`
- list project issues: `/projects/{project_id}/issues`
- preview/commit flow for create/update
- internal custom field discovery exists in code
- missing or incomplete:
- explicit endpoint for issue custom fields metadata
- explicit endpoint for available issue transitions
- explicit endpoint to perform a transition/state change
- generic metadata/value resolver before writes
- direct assignee/state/priority update endpoints remain implicit or heuristic
- `TimeTracking`
- already exposed:
- list issue work items
- create work item
- edit work item
- project time summary
- project time by issue
- assistant time report
- global assistant time report
- missing or incomplete:
- direct read endpoint for a single work item by id
- clearer project-scoped author/date filtered worklog queries as first-class tools
- `KnowledgeBase`
- already exposed:
- project KB list
- article search
- KB create via preview/commit flow
- missing or incomplete:
- direct create article endpoint
- direct read article detail endpoint
- direct update article endpoint
- richer KB metadata/context endpoints

Recommendation:
- Do not aim for "every raw YouTrack endpoint".
- Aim for "every operation the agent actually needs to complete Project / Issue / TimeTracking / KnowledgeBase workflows safely".
- That means adding missing metadata endpoints and direct non-destructive write helpers where they materially reduce LLM guesswork.

Priority gaps to close first:
- issue fields metadata endpoint
- issue transitions endpoint
- transition/state-change endpoint
- project metadata/details endpoint
- generic `POST /resolve-value`
- direct KB create/read/update endpoints

Definition of done for this feature:
- For each of the four domains, the assistant can inspect legal options before writing.
- The assistant does not need to guess statuses, assignees, transitions, or KB targets from prompt text alone.
- Preview/commit remains the default safety path for ambiguous or compound operations.
