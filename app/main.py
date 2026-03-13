from __future__ import annotations

from fastapi import FastAPI, HTTPException

from app.dependencies import (
    get_commit_service,
    get_preview_service,
    get_request_repository,
    get_request_service,
    get_youtrack_client,
)
from app.models import CommitInput, CommitResult, IngestRequestInput, NormalizedRequest, PreviewInput

app = FastAPI(
    title="YouTrack Open WebUI Orchestrator",
    version="0.1.0",
    description="OpenAPI backend for issue, time tracking, knowledge base and request triage workflows.",
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


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
