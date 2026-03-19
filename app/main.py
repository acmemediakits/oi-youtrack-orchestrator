from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException

from app.config import settings
from app.dependencies import (
    get_commit_service,
    get_mail_automation_runner,
    get_mail_automation_service,
    get_openwebui_client,
    get_preview_service,
    get_request_repository,
    get_request_service,
    get_youtrack_client,
)
from app.models import CommitInput, CommitResult, IngestRequestInput, MailProcessingRecord, NormalizedRequest, PreviewInput
from app.models import IssueEditInput, MailboxMessage, WorkItemEditInput

logging.basicConfig(
    level=logging.DEBUG if settings.verbose else logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)


@asynccontextmanager
async def lifespan(_: FastAPI):
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


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


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
async def ingest_request(payload: IngestRequestInput) -> NormalizedRequest:
    service = get_request_service()
    return service.ingest(payload)


@app.get("/requests/{request_id}", response_model=NormalizedRequest)
async def get_request(request_id: str) -> NormalizedRequest:
    repository = get_request_repository()
    item = repository.get(request_id)
    if not item:
        raise HTTPException(status_code=404, detail="Request not found.")
    return item


@app.get("/projects")
async def get_projects() -> list[dict]:
    client = get_youtrack_client()
    try:
        return await client.list_projects()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get(
    "/issues/{issue_id}",
    summary="Get issue details",
    description="Read an existing YouTrack issue by issue ID or readable ID such as ES-40.",
)
async def get_issue(issue_id: str) -> dict:
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
async def edit_issue(issue_id: str, payload: IssueEditInput) -> dict:
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
async def list_issue_work_items(issue_id: str) -> list[dict]:
    client = get_youtrack_client()
    try:
        return await client.list_issue_work_items(issue_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post(
    "/issues/{issue_id}/work-items/{item_id}/edit",
    summary="Edit an existing work item",
    description="Update text, duration, and/or date of an existing YouTrack work item. Use this when the user wants to correct a previously created worklog.",
)
async def edit_issue_work_item(issue_id: str, item_id: str, payload: WorkItemEditInput) -> dict:
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
async def preview_actions(payload: PreviewInput):
    service = get_preview_service()
    try:
        return service.build_preview(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/actions/commit", response_model=CommitResult)
async def commit_actions(payload: CommitInput) -> CommitResult:
    service = get_commit_service()
    try:
        return await service.commit(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
