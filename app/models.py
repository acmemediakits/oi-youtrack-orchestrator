from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RequestSource(str, Enum):
    email = "email"
    manual = "manual"


class RequestStatus(str, Enum):
    ingested = "ingested"
    previewed = "previewed"
    committed = "committed"


class ActionKind(str, Enum):
    issue = "issue"
    worklog = "worklog"
    knowledge = "knowledge"


class ProjectCandidate(BaseModel):
    project_id: str
    confidence: float = Field(ge=0, le=1)
    reason: str


class ProjectMatch(BaseModel):
    status: Literal["matched", "ambiguous", "unknown"]
    candidates: list[ProjectCandidate] = Field(default_factory=list)
    selected_project_id: str | None = None
    needs_confirmation: bool = False
    question: str | None = None


class NormalizedRequest(BaseModel):
    id: str = Field(default_factory=lambda: f"req_{uuid4().hex}")
    source: RequestSource
    text: str
    sender: str | None = None
    subject: str | None = None
    customer_label: str | None = None
    urgency: Literal["low", "medium", "high"] = "medium"
    context_snippets: list[str] = Field(default_factory=list)
    project_match: ProjectMatch
    open_questions: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    status: RequestStatus = RequestStatus.ingested


class IssueOperation(BaseModel):
    kind: Literal["issue"] = "issue"
    action: Literal["create", "update"]
    project_id: str | None = None
    issue_id: str | None = None
    summary: str
    description: str
    tags: list[str] = Field(default_factory=list)
    assignee: str | None = None
    confidence: float = Field(default=0.75, ge=0, le=1)
    needs_confirmation: bool = False


class WorklogOperation(BaseModel):
    kind: Literal["worklog"] = "worklog"
    issue_id: str | None = None
    project_id: str | None = None
    duration_minutes: int = Field(gt=0)
    description: str
    work_date: date = Field(default_factory=date.today)
    needs_confirmation: bool = False


class KnowledgeOperation(BaseModel):
    kind: Literal["knowledge"] = "knowledge"
    project_id: str | None = None
    folder: str | None = None
    title: str
    content: str
    tags: list[str] = Field(default_factory=list)
    is_personal: bool = False
    needs_confirmation: bool = False


class ActionPreview(BaseModel):
    preview_id: str = Field(default_factory=lambda: f"preview_{uuid4().hex}")
    request_id: str | None = None
    source_text: str
    project_match: ProjectMatch
    summary: str
    issue_operations: list[IssueOperation] = Field(default_factory=list)
    worklog_operations: list[WorklogOperation] = Field(default_factory=list)
    knowledge_operations: list[KnowledgeOperation] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    requires_confirmation: bool = False
    created_at: datetime = Field(default_factory=utc_now)


class OperationResult(BaseModel):
    kind: ActionKind
    status: Literal["success", "skipped", "error"]
    local_ref: str
    remote_id: str | None = None
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)


class CommitResult(BaseModel):
    commit_id: str = Field(default_factory=lambda: f"commit_{uuid4().hex}")
    preview_id: str
    committed_at: datetime = Field(default_factory=utc_now)
    status: Literal["success", "partial_success", "blocked", "duplicate"]
    summary: str
    issue_results: list[OperationResult] = Field(default_factory=list)
    worklog_results: list[OperationResult] = Field(default_factory=list)
    knowledge_results: list[OperationResult] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class IngestRequestInput(BaseModel):
    source: RequestSource
    text: str
    sender: str | None = None
    subject: str | None = None


class PreviewInput(BaseModel):
    text: str | None = None
    request_id: str | None = None


class CommitInput(BaseModel):
    preview_id: str
    confirm: bool = False


class CustomerRule(BaseModel):
    customer_label: str
    aliases: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    project_ids: list[str] = Field(default_factory=list)
    default_project_id: str | None = None
    tags: list[str] = Field(default_factory=list)


class MailboxMessage(BaseModel):
    message_id: str
    sender: str
    subject: str
    text: str
    received_at: datetime
