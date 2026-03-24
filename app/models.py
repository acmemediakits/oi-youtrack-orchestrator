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


class UserType(str, Enum):
    visitor = "visitor"
    team = "team"
    power = "power"


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


class ProjectSearchResult(BaseModel):
    project_id: str
    short_name: str
    name: str
    context: str | None = None
    archived: bool = False
    confidence: float = Field(ge=0, le=1)
    reason: str


class ProjectMetadata(BaseModel):
    project_id: str
    short_name: str
    name: str
    description: str | None = None
    context: str | None = None
    archived: bool = False
    aliases: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    default_for_customer: str | None = None
    reason: str | None = None


class ProjectEditInput(BaseModel):
    description: str


class ProjectArchiveStateInput(BaseModel):
    archived: bool


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
    requester_email: str | None = None
    requester_name: str | None = None
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


class WorkItemCreateInput(BaseModel):
    text: str
    duration_minutes: int = Field(gt=0)
    work_date: date = Field(default_factory=date.today)


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
    customer_label: str | None = None
    project_id: str | None = None


class PreviewInput(BaseModel):
    text: str | None = None
    request_id: str | None = None
    customer_label: str | None = None
    project_id: str | None = None


class CommitInput(BaseModel):
    preview_id: str
    confirm: bool = False


class IssueEditInput(BaseModel):
    summary: str | None = None
    description: str | None = None


class IssueAssigneeInput(BaseModel):
    assignee: str


class IssueStateInput(BaseModel):
    state: str


class WorkItemEditInput(BaseModel):
    text: str | None = None
    duration_minutes: int | None = Field(default=None, gt=0)
    work_date: date | None = None


class IssueSearchResult(BaseModel):
    issue_id: str
    issue_id_readable: str
    summary: str
    project_id: str | None = None
    project_short_name: str | None = None
    project_name: str | None = None
    state: str | None = None
    assignee: str | None = None
    resolved: bool = False
    updated_at: datetime | None = None
    url: str | None = None
    score: float = Field(default=0.0, ge=0, le=1)
    reason: str | None = None


class ArticleSearchResult(BaseModel):
    article_id: str
    article_id_readable: str | None = None
    summary: str
    project_id: str | None = None
    project_name: str | None = None
    updated_at: datetime | None = None
    url: str | None = None


class TimeTrackingIssueSummary(BaseModel):
    issue_id: str
    issue_id_readable: str
    summary: str
    minutes: int = 0
    hours: float = 0.0
    issue_url: str | None = None


class TimeTrackingAuthorSummary(BaseModel):
    author: str
    minutes: int = 0
    hours: float = 0.0


class TimeTrackingProjectSummary(BaseModel):
    project_id: str
    project_name: str | None = None
    minutes: int = 0
    hours: float = 0.0
    issue_count: int = 0


class TimeTrackingSummary(BaseModel):
    project_id: str
    project_name: str | None = None
    date_from: date
    date_to: date
    total_minutes: int = 0
    total_hours: float = 0.0
    issue_breakdown: list[TimeTrackingIssueSummary] = Field(default_factory=list)
    author_breakdown: list[TimeTrackingAuthorSummary] = Field(default_factory=list)


class GlobalTimeTrackingSummary(BaseModel):
    date_from: date
    date_to: date
    author_hint: str | None = None
    total_minutes: int = 0
    total_hours: float = 0.0
    project_breakdown: list[TimeTrackingProjectSummary] = Field(default_factory=list)


class AssistantProjectContext(BaseModel):
    project: ProjectSearchResult
    open_issues: list[IssueSearchResult] = Field(default_factory=list)
    recent_articles: list[ArticleSearchResult] = Field(default_factory=list)


class IssueFieldOption(BaseModel):
    id: str | None = None
    name: str
    presentation: str | None = None
    login: str | None = None
    full_name: str | None = None
    email: str | None = None
    score: float | None = Field(default=None, ge=0, le=1)
    reason: str | None = None


class IssueFieldMetadata(BaseModel):
    id: str
    name: str
    field_type: str
    current_value: Any = None
    can_be_empty: bool | None = None
    possible_values: list[IssueFieldOption] = Field(default_factory=list)
    possible_events: list[IssueFieldOption] = Field(default_factory=list)


class ResolveValueInput(BaseModel):
    type: Literal["status", "transition", "assignee", "issue_field", "priority"]
    input: str
    project_id: str | None = None
    issue_id: str | None = None
    field_name: str | None = None


class ResolveValueResult(BaseModel):
    type: str
    input: str
    issue_id: str | None = None
    project_id: str | None = None
    field_name: str | None = None
    selected: IssueFieldOption | None = None
    candidates: list[IssueFieldOption] = Field(default_factory=list)
    ambiguous: bool = False
    needs_clarification: bool = False


class CustomerRule(BaseModel):
    customer_label: str
    aliases: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    project_ids: list[str] = Field(default_factory=list)
    default_project_id: str | None = None
    tags: list[str] = Field(default_factory=list)


class MailboxMessage(BaseModel):
    message_id: str
    mailbox_uid: str
    sender: str
    subject: str
    text: str
    received_at: datetime


class MailProcessingRecord(BaseModel):
    id: str = Field(default_factory=lambda: f"mail_{uuid4().hex}")
    message_id: str
    mailbox_uid: str
    sender: str
    subject: str
    status: Literal["processed", "rejected_domain", "error"]
    response_text: str | None = None
    error: str | None = None
    finish_reason: str | None = None
    tool_calls_detected: bool = False
    raw_openwebui_response: dict[str, Any] = Field(default_factory=dict)
    processed_at: datetime = Field(default_factory=utc_now)


class OpenWebUIReply(BaseModel):
    content: str
    finish_reason: str | None = None
    tool_calls_detected: bool = False
    raw_response: dict[str, Any] = Field(default_factory=dict)


class MailExecutionPlan(BaseModel):
    request_text: str
    workflow_mode: Literal["youtrack", "assist"] = "youtrack"
    assist_intent: Literal["summarize", "translate", "explain", "extract_actions", "draft_reply", "classify_for_youtrack", "delegate", "time_report"] | None = None
    admin_scope: bool = False
    customer_label: str | None = None
    project_hint: str | None = None
    project_id: str | None = None
    issue_summary: str | None = None
    issue_description: str | None = None
    issue_assignee: str | None = None
    delegate_to_name: str | None = None
    delegate_to_email: str | None = None
    delegate_subject: str | None = None
    delegate_body: str | None = None
    report_date_from: date | None = None
    report_date_to: date | None = None
    report_group_by: Literal["project", "issue", "author"] | None = None
    report_author_hint: str | None = None
    needs_clarification: bool = False
    clarification_question: str | None = None
    reply_intent: Literal["execute", "clarify", "ignore"] = "execute"
    reply_draft: str | None = None


class IssueSubscription(BaseModel):
    id: str = Field(default_factory=lambda: f"sub_{uuid4().hex}")
    issue_id: str
    issue_id_readable: str
    summary: str
    requester_email: str
    requester_name: str | None = None
    source_subject: str | None = None
    state: str | None = None
    assignee: str | None = None
    resolved: bool = False
    updated_at: datetime | None = None
    worklog_count: int = 0
    total_minutes: int = 0
    last_worklog_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
    last_notified_at: datetime | None = None


class RuntimeMailboxFolders(BaseModel):
    inbox: str = "INBOX"
    processing: str = "PROCESSING"
    processed: str = "PROCESSED"
    failed: str = "FAILED"
    rejected: str = "REJECTED"


class RuntimeConfig(BaseModel):
    id: str = "runtime"
    verbose: bool = False
    mailbox_poll_interval_seconds: int = Field(default=60, ge=10, le=86400)
    mailbox_allowed_sender_domains: list[str] = Field(default_factory=list)
    mailbox_folders: RuntimeMailboxFolders = Field(default_factory=RuntimeMailboxFolders)
    updated_at: datetime = Field(default_factory=utc_now)


class WhitelistedUser(BaseModel):
    id: str = Field(default_factory=lambda: f"user_{uuid4().hex}")
    full_name: str
    email: str
    youtrack_assignee_email: str | None = None
    user_type: UserType = UserType.visitor
    active: bool = True
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AdminApproval(BaseModel):
    id: str = Field(default_factory=lambda: f"approval_{uuid4().hex}")
    requester_email: str
    requester_name: str | None = None
    original_message_id: str
    original_subject: str | None = None
    token_hash: str
    plan_payload: dict[str, Any]
    message_payload: dict[str, Any]
    expires_at: datetime
    used_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)


class PanelStatus(BaseModel):
    runtime_config: RuntimeConfig
    users_total: int = 0
    users_active: int = 0
    secrets_status: dict[str, bool] = Field(default_factory=dict)
