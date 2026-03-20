from __future__ import annotations

import hashlib
import hmac
import logging
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone

from fastapi import FastAPI, Form, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import settings
from app.dependencies import (
    get_admin_approval_service,
    get_commit_service,
    get_issue_subscription_service,
    get_mail_automation_runner,
    get_mail_automation_service,
    get_mailbox_service,
    get_openwebui_client,
    get_permission_service,
    get_preview_service,
    get_query_service,
    get_request_repository,
    get_request_service,
    get_runtime_config_service,
    get_user_directory_service,
    get_youtrack_client,
)
from app.logging_utils import get_log_file_path, get_recent_logs, setup_logging
from app.models import (
    AssistantProjectContext,
    ArticleSearchResult,
    CommitInput,
    CommitResult,
    GlobalTimeTrackingSummary,
    IngestRequestInput,
    IssueEditInput,
    IssueSearchResult,
    MailProcessingRecord,
    MailboxMessage,
    NormalizedRequest,
    RuntimeMailboxFolders,
    PreviewInput,
    ProjectSearchResult,
    TimeTrackingSummary,
    WhitelistedUser,
    UserType,
    WorkItemCreateInput,
    WorkItemEditInput,
)
from app.presentation.panel_views import render_login_page, render_panel

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        get_mailbox_service().ensure_runtime_folders()
    except Exception:
        logger.exception("IMAP folder bootstrap failed during startup.")
    runner = get_mail_automation_runner()
    runner.start()
    try:
        yield
    finally:
        await runner.stop()


app = FastAPI(
    title="YouTrack Open WebUI Orchestrator",
    version="0.1.0",
    description="OpenAPI backend for issue, time tracking, knowledge base and request triage workflows.",
    lifespan=lifespan,
)


TRUSTED_ASSISTANT_ACTOR_ID = "user_openwebui_trusted_assistant"


def _panel_cookie_value() -> str:
    return hashlib.sha256(settings.panel_admin_password.encode("utf-8")).hexdigest() if settings.panel_admin_password else ""


def _panel_authenticated(request: Request) -> bool:
    cookie = request.cookies.get("panel_auth")
    expected = _panel_cookie_value()
    return bool(expected and cookie and hmac.compare_digest(cookie, expected))


def _require_panel_auth(request: Request) -> None:
    if not _panel_authenticated(request):
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, detail="Panel auth required.")


def _resolve_actor(actor_email: str | None):
    if not actor_email and settings.openwebui_trusted_channel_enabled:
        return WhitelistedUser(
            id=TRUSTED_ASSISTANT_ACTOR_ID,
            full_name=settings.openwebui_trusted_actor_name,
            email=settings.openwebui_trusted_actor_email,
            user_type=settings.openwebui_trusted_actor_role,
            active=True,
        )
    if not actor_email:
        raise HTTPException(status_code=401, detail="Missing X-Actor-Email header.")
    user = get_user_directory_service().resolve(actor_email)
    try:
        return get_permission_service().ensure_active_user(user)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _assert_capability(actor, capability: str) -> None:
    try:
        get_permission_service().assert_capability(actor, capability)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _assert_issue_edit_allowed(actor, issue_id: str) -> None:
    if actor.user_type == UserType.visitor and not get_permission_service().can_modify_issue(actor, issue_id):
        raise HTTPException(status_code=403, detail="Il visitor puo' modificare solo i ticket creati da lui negli ultimi 30 minuti.")


def _is_trusted_assistant_actor(actor: WhitelistedUser) -> bool:
    return actor.id == TRUSTED_ASSISTANT_ACTOR_ID


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/panel/login", response_class=HTMLResponse)
async def panel_login_page(error: str | None = None) -> HTMLResponse:
    error_message = "Invalid panel password. Please try again." if error == "invalid" else None
    return HTMLResponse(render_login_page(error_message))


@app.post("/panel/login")
async def panel_login(password: str = Form(...)) -> Response:
    if not settings.panel_admin_password or not hmac.compare_digest(password, settings.panel_admin_password):
        return RedirectResponse("/panel/login?error=invalid", status_code=status.HTTP_303_SEE_OTHER)
    response = RedirectResponse("/panel", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie("panel_auth", _panel_cookie_value(), httponly=True, samesite="lax")
    return response


@app.post("/panel/logout")
async def panel_logout() -> Response:
    response = RedirectResponse("/panel/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("panel_auth")
    return response


@app.get("/panel", response_class=HTMLResponse)
async def panel_home(
    request: Request,
    edit_email: str | None = None,
    user_modal: str | None = None,
    log_lines: int = 120,
) -> HTMLResponse:
    if not _panel_authenticated(request):
        return HTMLResponse("", status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/panel/login"})
    user_service = get_user_directory_service()
    users = user_service.list_users()
    editing_user = user_service.resolve(edit_email) if edit_email else None
    show_user_modal = user_modal == "add" or (user_modal == "edit" and editing_user is not None)
    status_model = get_runtime_config_service().panel_status(users)
    log_lines = max(20, min(log_lines, 400))
    return HTMLResponse(
        render_panel(
            status_model,
            users,
            editing_user,
            show_user_modal,
            recent_logs=get_recent_logs(log_lines),
            log_path=str(get_log_file_path()),
        )
    )


@app.post("/panel/settings")
async def panel_save_settings(
    request: Request,
    mailbox_poll_interval_seconds: int = Form(...),
    mailbox_allowed_sender_domains: str = Form(""),
    inbox: str = Form(...),
    processing: str = Form(...),
    processed: str = Form(...),
    failed: str = Form(...),
    rejected: str = Form(...),
    verbose: str | None = Form(None),
) -> Response:
    if not _panel_authenticated(request):
        raise HTTPException(status_code=403, detail="Panel auth required.")
    get_runtime_config_service().update(
        verbose=verbose is not None,
        mailbox_poll_interval_seconds=mailbox_poll_interval_seconds,
        mailbox_allowed_sender_domains=[item.strip().lower() for item in mailbox_allowed_sender_domains.split(",") if item.strip()],
        mailbox_folders=RuntimeMailboxFolders(
            inbox=inbox.strip(),
            processing=processing.strip(),
            processed=processed.strip(),
            failed=failed.strip(),
            rejected=rejected.strip(),
        ),
    )
    return RedirectResponse("/panel", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/panel/users")
async def panel_save_user(
    request: Request,
    full_name: str = Form(...),
    email: str = Form(...),
    original_email: str = Form(""),
    youtrack_assignee_email: str = Form(""),
    user_type: UserType = Form(...),
    active: str | None = Form(None),
) -> Response:
    if not _panel_authenticated(request):
        raise HTTPException(status_code=403, detail="Panel auth required.")
    get_user_directory_service().upsert_user(
        full_name=full_name,
        email=email,
        original_email=original_email,
        youtrack_assignee_email=youtrack_assignee_email,
        user_type=user_type,
        active=active is not None,
    )
    return RedirectResponse("/panel", status_code=status.HTTP_303_SEE_OTHER)


@app.get(
    "/test",
    summary="Run external integration tests",
    description="Test Open WebUI connectivity, SMTP delivery, or both through simple query parameters.",
)
async def run_test(
    heartbeat: str | None = None,
    mailto: str | None = None,
    mailjoke: str | None = None,
) -> dict:
    if sum(value is not None for value in [heartbeat, mailto, mailjoke]) != 1:
        raise HTTPException(
            status_code=400,
            detail="Provide exactly one of heartbeat, mailto, or mailjoke.",
        )

    mailbox = get_mail_automation_service().mailbox
    openwebui = get_openwebui_client()

    if heartbeat is not None:
        prompt = (
            "Reply with exactly one short joke in plain text. "
            f"Context token: {heartbeat}"
        )
        try:
            reply = await openwebui.generate_reply(prompt)
            return {
                "mode": "heartbeat",
                "openwebui_ok": True,
                "reply": reply,
            }
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Open WebUI heartbeat failed: {exc}") from exc

    if mailto is not None:
        try:
            message = MailboxMessage(
                message_id="test-mailto",
                mailbox_uid="0",
                sender=mailto,
                subject="YouTrack orchestrator SMTP test",
                text="SMTP test",
                received_at=datetime.now(timezone.utc),
            )
            mailbox.send_reply(
                message,
                "This is a direct SMTP test from the YouTrack Open WebUI orchestrator.",
            )
            return {
                "mode": "mailto",
                "smtp_ok": True,
                "recipient": mailto,
            }
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"SMTP test failed: {exc}") from exc

    try:
        prompt = "Reply with exactly one short joke in plain text."
        reply = await openwebui.generate_reply(prompt)
        message = MailboxMessage(
            message_id="test-mailjoke",
            mailbox_uid="0",
            sender=mailjoke or "",
            subject="YouTrack orchestrator mailjoke test",
            text="mailjoke test",
            received_at=datetime.now(timezone.utc),
        )
        mailbox.send_reply(message, reply)
        return {
            "mode": "mailjoke",
            "openwebui_ok": True,
            "smtp_ok": True,
            "recipient": mailjoke,
            "reply": reply,
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"mailjoke test failed: {exc}") from exc


@app.post("/requests/ingest", response_model=NormalizedRequest)
async def ingest_request(payload: IngestRequestInput, x_actor_email: str | None = Header(default=None)) -> NormalizedRequest:
    actor = _resolve_actor(x_actor_email)
    _assert_capability(actor, "create_task")
    payload = payload.model_copy(update={"sender": payload.sender or actor.email})
    service = get_request_service()
    return service.ingest(payload)


@app.get("/requests/{request_id}", response_model=NormalizedRequest)
async def get_request(request_id: str, x_actor_email: str | None = Header(default=None)) -> NormalizedRequest:
    actor = _resolve_actor(x_actor_email)
    _assert_capability(actor, "create_task")
    repository = get_request_repository()
    item = repository.get(request_id)
    if not item:
        raise HTTPException(status_code=404, detail="Request not found.")
    return item


@app.get("/projects")
async def get_projects(x_actor_email: str | None = Header(default=None)) -> list[dict]:
    actor = _resolve_actor(x_actor_email)
    _assert_capability(actor, "view_non_archived_projects")
    client = get_youtrack_client()
    try:
        projects = await client.list_projects()
        if actor.user_type == UserType.team:
            projects = [item for item in projects if not item.get("archived")]
        return projects
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get(
    "/projects/search",
    summary="Search projects by hint",
    description="Search YouTrack projects by customer hint, project name, or short name. Non-archived projects are ranked first.",
    response_model=list[ProjectSearchResult],
)
async def search_projects(
    q: str,
    include_archived: bool = False,
    limit: int = 10,
    x_actor_email: str | None = Header(default=None),
) -> list[ProjectSearchResult]:
    actor = _resolve_actor(x_actor_email)
    _assert_capability(actor, "view_non_archived_projects")
    service = get_query_service()
    try:
        if actor.user_type == UserType.team:
            include_archived = False
        return await service.search_projects(q, include_archived=include_archived, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get(
    "/issues/{issue_id}",
    summary="Get issue details",
    description="Read an existing YouTrack issue by issue ID or readable ID such as ES-40.",
)
async def get_issue(issue_id: str, x_actor_email: str | None = Header(default=None)) -> dict:
    actor = _resolve_actor(x_actor_email)
    _assert_capability(actor, "advanced_reads")
    client = get_youtrack_client()
    try:
        return await client.get_issue(issue_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post(
    "/issues/{issue_id}/edit",
    summary="Edit an existing issue",
    description="Update summary and/or description of an existing YouTrack issue. Use this when the user wants to rename or rewrite an issue that already exists.",
)
async def edit_issue(issue_id: str, payload: IssueEditInput, x_actor_email: str | None = Header(default=None)) -> dict:
    actor = _resolve_actor(x_actor_email)
    if actor.user_type == UserType.visitor:
        _assert_issue_edit_allowed(actor, issue_id)
    else:
        _assert_capability(actor, "assist_mail")
    if payload.summary is None and payload.description is None:
        raise HTTPException(status_code=400, detail="At least one of summary or description must be provided.")
    client = get_youtrack_client()
    try:
        response = await client.update_issue(
            issue_id,
            {key: value for key, value in payload.model_dump().items() if value is not None},
        )
        return {
            **response,
            "url": client.issue_url(response.get("idReadable") or response.get("id") or issue_id),
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get(
    "/issues/{issue_id}/work-items",
    summary="List work items of an issue",
    description="Read existing work items attached to a YouTrack issue. Use this before editing a worklog when the work item ID is unknown.",
)
async def list_issue_work_items(issue_id: str, x_actor_email: str | None = Header(default=None)) -> list[dict]:
    actor = _resolve_actor(x_actor_email)
    _assert_capability(actor, "advanced_reads")
    client = get_youtrack_client()
    try:
        return await client.list_issue_work_items(issue_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post(
    "/issues/{issue_id}/work-items",
    summary="Create a new work item",
    description="Create a new worklog entry directly on an existing issue.",
)
async def create_issue_work_item(issue_id: str, payload: WorkItemCreateInput, x_actor_email: str | None = Header(default=None)) -> dict:
    actor = _resolve_actor(x_actor_email)
    if actor.user_type == UserType.visitor:
        _assert_issue_edit_allowed(actor, issue_id)
    else:
        _assert_capability(actor, "assist_mail")
    client = get_youtrack_client()
    try:
        response = await client.add_work_item(
            issue_id,
            {
                "text": payload.text,
                "date": int(payload.work_date.strftime("%s")) * 1000,
                "duration": {"minutes": payload.duration_minutes},
            },
        )
        return {
            **response,
            "issue_id": issue_id,
            "issue_url": client.issue_url(issue_id),
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post(
    "/issues/{issue_id}/work-items/{item_id}/edit",
    summary="Edit an existing work item",
    description="Update text, duration, and/or date of an existing YouTrack work item. Use this when the user wants to correct a previously created worklog.",
)
async def edit_issue_work_item(issue_id: str, item_id: str, payload: WorkItemEditInput, x_actor_email: str | None = Header(default=None)) -> dict:
    actor = _resolve_actor(x_actor_email)
    if actor.user_type == UserType.visitor:
        _assert_issue_edit_allowed(actor, issue_id)
    else:
        _assert_capability(actor, "assist_mail")
    if payload.text is None and payload.duration_minutes is None and payload.work_date is None:
        raise HTTPException(
            status_code=400,
            detail="At least one of text, duration_minutes, or work_date must be provided.",
        )
    client = get_youtrack_client()
    raw_payload = payload.model_dump()
    request_payload = {}
    if raw_payload["text"] is not None:
        request_payload["text"] = raw_payload["text"]
    if raw_payload["duration_minutes"] is not None:
        request_payload["duration"] = {"minutes": raw_payload["duration_minutes"]}
    if raw_payload["work_date"] is not None:
        request_payload["date"] = int(raw_payload["work_date"].strftime("%s")) * 1000
    try:
        response = await client.update_work_item(issue_id, item_id, request_payload)
        return {
            **response,
            "issue_id": issue_id,
            "issue_url": client.issue_url(issue_id),
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get(
    "/projects/{project_id}/issues",
    summary="List project issues",
    description="List issues in a project with optional query, open-only filter, assignee filter, and updated-since filter.",
    response_model=list[IssueSearchResult],
)
async def list_project_issues(
    project_id: str,
    query: str | None = None,
    only_open: bool = False,
    assignee: str | None = None,
    updated_since: date | None = None,
    limit: int = 20,
    x_actor_email: str | None = Header(default=None),
) -> list[IssueSearchResult]:
    actor = _resolve_actor(x_actor_email)
    _assert_capability(actor, "view_open_tasks")
    service = get_query_service()
    try:
        if actor.user_type == UserType.team:
            only_open = True
        return await service.list_project_issues(
            project_id,
            query=query,
            only_open=only_open,
            assignee=assignee,
            updated_since=updated_since,
            limit=limit,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get(
    "/issues/search",
    summary="Search issues",
    description="Search issues across YouTrack or within a specific project. Use this to find the best issue candidate before writing or reporting.",
    response_model=list[IssueSearchResult],
)
async def search_issues(
    q: str,
    project_id: str | None = None,
    only_open: bool = False,
    assignee: str | None = None,
    updated_since: date | None = None,
    limit: int = 20,
    x_actor_email: str | None = Header(default=None),
) -> list[IssueSearchResult]:
    actor = _resolve_actor(x_actor_email)
    _assert_capability(actor, "view_open_tasks")
    service = get_query_service()
    try:
        if actor.user_type == UserType.team:
            only_open = True
        return await service.search_issues(
            q,
            project_id=project_id,
            only_open=only_open,
            assignee=assignee,
            updated_since=updated_since,
            limit=limit,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get(
    "/projects/{project_id}/time-tracking/summary",
    summary="Summarize time tracking for a project",
    description="Return total tracked time for a project in a date range, with issue and author breakdowns.",
    response_model=TimeTrackingSummary,
)
async def summarize_project_time(
    project_id: str,
    from_date: date = Query(alias="from"),
    to_date: date = Query(alias="to"),
    x_actor_email: str | None = Header(default=None),
) -> TimeTrackingSummary:
    actor = _resolve_actor(x_actor_email)
    _assert_capability(actor, "time_reports")
    service = get_query_service()
    try:
        return await service.summarize_project_time(project_id, from_date, to_date)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get(
    "/projects/{project_id}/time-tracking/by-issue",
    summary="Project time tracking by issue",
    description="Return the same project time summary focused on issue breakdown ordering.",
    response_model=TimeTrackingSummary,
)
async def summarize_project_time_by_issue(
    project_id: str,
    from_date: date = Query(alias="from"),
    to_date: date = Query(alias="to"),
    x_actor_email: str | None = Header(default=None),
) -> TimeTrackingSummary:
    actor = _resolve_actor(x_actor_email)
    _assert_capability(actor, "time_reports")
    service = get_query_service()
    try:
        return await service.summarize_project_time(project_id, from_date, to_date)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get(
    "/projects/{project_id}/articles",
    summary="List project knowledge articles",
    description="List knowledge base articles for a project, optionally filtered by query.",
    response_model=list[ArticleSearchResult],
)
async def list_project_articles(project_id: str, query: str | None = None, limit: int = 20, x_actor_email: str | None = Header(default=None)) -> list[ArticleSearchResult]:
    actor = _resolve_actor(x_actor_email)
    _assert_capability(actor, "knowledge_read")
    service = get_query_service()
    try:
        return await service.list_project_articles(project_id, query=query, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get(
    "/articles/search",
    summary="Search knowledge articles",
    description="Search YouTrack knowledge base articles globally or inside a single project.",
    response_model=list[ArticleSearchResult],
)
async def search_articles(q: str, project_id: str | None = None, limit: int = 20, x_actor_email: str | None = Header(default=None)) -> list[ArticleSearchResult]:
    actor = _resolve_actor(x_actor_email)
    _assert_capability(actor, "knowledge_read")
    service = get_query_service()
    try:
        return await service.search_articles(q, project_id=project_id, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get(
    "/assistant/project-context",
    summary="Build project context from a hint",
    description="Find the best project match from a natural hint, then return open issues and recent articles for context.",
    response_model=AssistantProjectContext | None,
)
async def assistant_project_context(hint: str, limit: int = 10, x_actor_email: str | None = Header(default=None)) -> AssistantProjectContext | None:
    actor = _resolve_actor(x_actor_email)
    _assert_capability(actor, "view_open_tasks")
    service = get_query_service()
    try:
        return await service.build_project_context(hint, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get(
    "/assistant/open-work",
    summary="Summarize open work from a project hint",
    description="Resolve a project from a natural hint and return open issues for that project.",
    response_model=list[IssueSearchResult],
)
async def assistant_open_work(project_hint: str, limit: int = 10, x_actor_email: str | None = Header(default=None)) -> list[IssueSearchResult]:
    actor = _resolve_actor(x_actor_email)
    _assert_capability(actor, "view_open_tasks")
    service = get_query_service()
    try:
        context = await service.build_project_context(project_hint, limit=limit)
        return context.open_issues if context else []
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get(
    "/assistant/time-report",
    summary="Build a time report from a project hint",
    description="Resolve a project from a natural hint and return tracked time totals in the requested date range.",
    response_model=TimeTrackingSummary,
)
async def assistant_time_report(
    project_hint: str,
    from_date: date = Query(alias="from"),
    to_date: date = Query(alias="to"),
    x_actor_email: str | None = Header(default=None),
) -> TimeTrackingSummary:
    actor = _resolve_actor(x_actor_email)
    _assert_capability(actor, "time_reports")
    service = get_query_service()
    try:
        projects = await service.search_projects(project_hint, include_archived=False, limit=1)
        if not projects:
            raise HTTPException(status_code=404, detail=f"No project found for hint '{project_hint}'.")
        return await service.summarize_project_time(projects[0].project_id, from_date, to_date)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get(
    "/assistant/time-report/global",
    summary="Build a cross-project time report",
    description="Return total tracked time in the requested date range, grouped by project and optionally filtered by author/login hint.",
    response_model=GlobalTimeTrackingSummary,
)
async def assistant_global_time_report(
    from_date: date = Query(alias="from"),
    to_date: date = Query(alias="to"),
    author_hint: str | None = None,
    x_actor_email: str | None = Header(default=None),
) -> GlobalTimeTrackingSummary:
    actor = _resolve_actor(x_actor_email)
    _assert_capability(actor, "time_reports")
    service = get_query_service()
    try:
        return await service.summarize_time_report(from_date, to_date, author_hint=author_hint)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post(
    "/mail/poll/run",
    summary="Run one mail polling cycle",
    description="Fetch unseen emails, filter allowed sender domains, call the configured Open WebUI model, and send email replies for processed messages.",
    response_model=list[MailProcessingRecord],
)
async def run_mail_polling_cycle() -> list[MailProcessingRecord]:
    service = get_mail_automation_service()
    try:
        return await service.run_once()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/actions/preview")
async def preview_actions(payload: PreviewInput, x_actor_email: str | None = Header(default=None)):
    actor = _resolve_actor(x_actor_email)
    _assert_capability(actor, "create_task")
    service = get_preview_service()
    try:
        return service.build_preview(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/actions/commit", response_model=CommitResult)
async def commit_actions(payload: CommitInput, x_actor_email: str | None = Header(default=None)) -> CommitResult:
    actor = _resolve_actor(x_actor_email)
    _assert_capability(actor, "create_task")
    service = get_commit_service()
    try:
        result = await service.commit(payload)
        if _is_trusted_assistant_actor(actor):
            return result
        subscription_service = get_issue_subscription_service()
        for issue in result.issue_results:
            if issue.status != "success":
                continue
            issue_ref = issue.remote_id or issue.payload.get("idReadable") or issue.payload.get("id")
            if issue_ref:
                await subscription_service.subscribe(issue_ref, actor.email, requester_name=actor.full_name)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
