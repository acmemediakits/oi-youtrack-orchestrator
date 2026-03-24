from __future__ import annotations

from collections import defaultdict
import calendar
from difflib import SequenceMatcher
import hashlib
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from email.utils import parseaddr

from app.config import settings
from app.models import (
    AssistantProjectContext,
    ActionKind,
    ActionPreview,
    AdminApproval,
    ArticleSearchResult,
    CommitInput,
    CommitResult,
    GlobalTimeTrackingSummary,
    IngestRequestInput,
    IssueFieldMetadata,
    IssueFieldOption,
    IssueSubscription,
    IssueSearchResult,
    IssueOperation,
    ProjectMetadata,
    KnowledgeOperation,
    NormalizedRequest,
    OperationResult,
    PanelStatus,
    ProjectSearchResult,
    PreviewInput,
    ProjectCandidate,
    ProjectMatch,
    ResolveValueResult,
    RequestStatus,
    RuntimeConfig,
    RuntimeMailboxFolders,
    TimeTrackingAuthorSummary,
    TimeTrackingIssueSummary,
    TimeTrackingProjectSummary,
    TimeTrackingSummary,
    UserType,
    WhitelistedUser,
    WorklogOperation,
)
from app.repositories import (
    AdminApprovalRepository,
    CommitRepository,
    CustomerDirectoryRepository,
    IssueSubscriptionRepository,
    PreviewRepository,
    RequestRepository,
    RuntimeConfigRepository,
    UserDirectoryRepository,
)


ISSUE_ID_PATTERN = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")
HOURS_PATTERN = re.compile(r"(\d+(?:[.,]\d+)?)\s*(ora|ore|h|hr|min|mins|minuti)", re.IGNORECASE)
MONTH_NAME_TO_NUMBER = {
    "gennaio": 1,
    "febbraio": 2,
    "marzo": 3,
    "aprile": 4,
    "maggio": 5,
    "giugno": 6,
    "luglio": 7,
    "agosto": 8,
    "settembre": 9,
    "ottobre": 10,
    "novembre": 11,
    "dicembre": 12,
}


def normalize_text(text: str) -> str:
    return " ".join(text.strip().split())


def normalize_markdown_text(text: str) -> str:
    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    normalized_lines: list[str] = []
    previous_blank = False
    for raw_line in lines:
        line = raw_line.rstrip()
        if not line.strip():
            if not previous_blank and normalized_lines:
                normalized_lines.append("")
            previous_blank = True
            continue
        stripped = line.strip()
        if re.match(r"^[-*]\s+", stripped):
            normalized_lines.append(f"- {stripped[2:].strip()}")
        elif re.match(r"^\d+\.\s+", stripped):
            normalized_lines.append(stripped)
        elif stripped.startswith(">"):
            normalized_lines.append(stripped)
        else:
            normalized_lines.append(" ".join(stripped.split()))
        previous_blank = False
    return "\n".join(normalized_lines).strip()


def normalize_match_token(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").strip().lower()).strip()


def similarity_score(left: str | None, right: str | None) -> float:
    normalized_left = normalize_match_token(left)
    normalized_right = normalize_match_token(right)
    if not normalized_left or not normalized_right:
        return 0.0
    if normalized_left == normalized_right:
        return 1.0
    if normalized_left in normalized_right or normalized_right in normalized_left:
        return 0.9
    return SequenceMatcher(a=normalized_left, b=normalized_right).ratio()


def split_sentences(text: str) -> list[str]:
    chunks = re.split(r"[\n;,]+", text)
    return [normalize_text(chunk) for chunk in chunks if normalize_text(chunk)]


def extract_explicit_worklog_comment(text: str) -> str | None:
    pattern = re.compile(
        r"(?:commento\s+sulla\s+lavorazione|commento)\s*:\s*(.+)$",
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(text)
    if not match:
        return None
    return normalize_text(match.group(1))


def extract_duration_minutes(text: str) -> int | None:
    match = HOURS_PATTERN.search(text)
    if not match:
        return None
    raw_value = float(match.group(1).replace(",", "."))
    unit = match.group(2).lower()
    if unit.startswith("min"):
        return int(raw_value)
    return int(raw_value * 60)


def extract_issue_reference(text: str) -> str | None:
    for raw_token in re.split(r"\s+", text or ""):
        token = raw_token.strip(".,;:!?()[]{}<>\"'")
        if "-" not in token:
            continue
        prefix, suffix = token.rsplit("-", 1)
        normalized_prefix = prefix.replace("_", "")
        if not normalized_prefix or not suffix.isdigit():
            continue
        if not normalized_prefix[0].isalpha():
            continue
        if not all(char.isalnum() or char == "_" for char in prefix):
            continue
        return token
    match = ISSUE_ID_PATTERN.search(text or "")
    return match.group(1) if match else None


def utc_datetime_from_millis(raw: int | None) -> datetime | None:
    if raw is None:
        return None
    return datetime.fromtimestamp(raw / 1000, tz=timezone.utc)


def issue_custom_field_value(issue: dict, field_name: str) -> dict | str | None:
    for field in issue.get("customFields") or []:
        if field.get("name") == field_name:
            return field.get("value")
    return None


def issue_state_name(issue: dict) -> str | None:
    value = issue_custom_field_value(issue, "State")
    if isinstance(value, dict):
        return value.get("name") or value.get("presentation")
    if isinstance(value, str):
        return value
    return None


def issue_assignee_name(issue: dict) -> str | None:
    value = issue_custom_field_value(issue, settings.youtrack_assignee_field_name)
    if value is None:
        for field in issue.get("customFields") or []:
            field_name = (field.get("name") or "").lower()
            if not any(token in field_name for token in ["assignee", "team", "owner"]):
                continue
            value = field.get("value")
            break
    if isinstance(value, dict):
        return value.get("fullName") or value.get("name") or value.get("login")
    if isinstance(value, str):
        return value
    return None


def parse_mail_identity(sender: str | None) -> tuple[str | None, str | None]:
    display_name, email_address = parseaddr(sender or "")
    if not email_address:
        return (display_name or None, None)
    return (display_name or email_address.split("@", 1)[0], email_address.lower())


def sender_author_hints(sender: str | None) -> list[str]:
    display_name, email_address = parse_mail_identity(sender)
    hints: list[str] = []
    if display_name:
        hints.append(display_name.lower())
    if email_address:
        hints.append(email_address.lower())
        hints.append(email_address.split("@", 1)[0].lower())
    return list(dict.fromkeys(filter(None, hints)))


def matches_author_hint(author: dict | None, author_hint: str | None) -> bool:
    if not author_hint:
        return True
    normalized_hint = author_hint.strip().lower()
    if not normalized_hint:
        return True
    values = {
        ((author or {}).get("fullName") or "").lower(),
        ((author or {}).get("login") or "").lower(),
        ((author or {}).get("email") or "").lower(),
    }
    return normalized_hint in values


def parse_reporting_period(text: str, today: date | None = None) -> tuple[date | None, date | None]:
    lowered = normalize_text(text).lower()
    today = today or date.today()

    month_match = re.search(
        r"\b(gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre)\s+(\d{4})\b",
        lowered,
    )
    if month_match:
        month = MONTH_NAME_TO_NUMBER[month_match.group(1)]
        year = int(month_match.group(2))
        last_day = calendar.monthrange(year, month)[1]
        return date(year, month, 1), date(year, month, last_day)

    iso_range = re.search(r"\bdal\s+(\d{4}-\d{2}-\d{2})\s+al\s+(\d{4}-\d{2}-\d{2})\b", lowered)
    if iso_range:
        return date.fromisoformat(iso_range.group(1)), date.fromisoformat(iso_range.group(2))

    if "mese scorso" in lowered:
        year = today.year
        month = today.month - 1
        if month == 0:
            month = 12
            year -= 1
        last_day = calendar.monthrange(year, month)[1]
        return date(year, month, 1), date(year, month, last_day)

    if "questo mese" in lowered:
        last_day = calendar.monthrange(today.year, today.month)[1]
        return date(today.year, today.month, 1), date(today.year, today.month, last_day)

    return (None, None)


ROLE_CAPABILITIES: dict[UserType, set[str]] = {
    UserType.visitor: {"create_task", "receive_updates"},
    UserType.team: {"create_task", "receive_updates", "view_open_tasks", "view_non_archived_projects", "assist_mail"},
    UserType.power: {
        "create_task",
        "receive_updates",
        "view_open_tasks",
        "view_non_archived_projects",
        "assist_mail",
        "advanced_reads",
        "time_reports",
        "knowledge_write",
        "knowledge_read",
        "admin_scope_email",
        "admin_scope_api",
    },
}


@dataclass(slots=True)
class RuntimeConfigService:
    repository: RuntimeConfigRepository

    def get(self) -> RuntimeConfig:
        existing = self.repository.get_config()
        if existing:
            return existing
        config = RuntimeConfig(
            verbose=settings.verbose,
            mailbox_poll_interval_seconds=settings.mailbox_poll_interval_seconds,
            mailbox_allowed_sender_domains=list(settings.mailbox_allowed_sender_domains),
            mailbox_folders=RuntimeMailboxFolders(
                inbox=settings.mailbox_folder,
                processing=settings.mailbox_processing_folder,
                processed=settings.mailbox_processed_folder,
                failed=settings.mailbox_failed_folder,
                rejected=settings.mailbox_rejected_folder,
            ),
        )
        return self.repository.save_config(config)

    def update(self, **changes) -> RuntimeConfig:
        current = self.get()
        updated = current.model_copy(update={**changes, "updated_at": datetime.now(timezone.utc)})
        saved = self.repository.save_config(updated)
        logging.getLogger().setLevel(logging.DEBUG if saved.verbose else logging.INFO)
        return saved

    def panel_status(self, users: list[WhitelistedUser]) -> PanelStatus:
        return PanelStatus(
            runtime_config=self.get(),
            users_total=len(users),
            users_active=sum(1 for user in users if user.active),
            secrets_status={
                "youtrack_token_configured": bool(settings.youtrack_token),
                "openwebui_api_token_configured": bool(settings.openwebui_api_token),
                "mailbox_imap_configured": bool(settings.mailbox_imap_host and settings.mailbox_username and settings.mailbox_password),
                "mailbox_smtp_configured": bool(settings.mailbox_smtp_host and settings.mailbox_username and settings.mailbox_password),
                "panel_admin_password_configured": bool(settings.panel_admin_password),
                "super_admin_email_configured": bool(settings.super_admin_email),
            },
        )


@dataclass(slots=True)
class UserDirectoryService:
    repository: UserDirectoryRepository

    def list_users(self) -> list[WhitelistedUser]:
        return sorted(self.repository.list_all(), key=lambda item: item.full_name.lower())

    def resolve(self, email: str | None) -> WhitelistedUser | None:
        if not email:
            return None
        return self.repository.find_by_email(email)

    def upsert_user(
        self,
        *,
        full_name: str,
        email: str,
        original_email: str | None = None,
        youtrack_assignee_email: str | None,
        user_type: UserType,
        active: bool,
    ) -> WhitelistedUser:
        normalized_email = email.strip().lower()
        normalized_original_email = (original_email or "").strip().lower() or None
        existing = self.repository.find_by_email(normalized_original_email or normalized_email)
        payload = {
            "full_name": full_name.strip(),
            "email": normalized_email,
            "youtrack_assignee_email": (youtrack_assignee_email or "").strip().lower() or None,
            "user_type": user_type,
            "active": active,
            "updated_at": datetime.now(timezone.utc),
        }
        if existing:
            user = existing.model_copy(update=payload)
            saved = self.repository.upsert(existing.id, user)
            duplicate = self.repository.find_by_email(normalized_email)
            if duplicate and duplicate.id != existing.id:
                self.repository.delete_user(duplicate.id)
            return saved
        user = WhitelistedUser(**payload)
        return self.repository.upsert(user.id, user)


@dataclass(slots=True)
class PermissionService:
    subscriptions: IssueSubscriptionRepository

    def ensure_active_user(self, user: WhitelistedUser | None) -> WhitelistedUser:
        if not user or not user.active:
            raise PermissionError("Utente non autorizzato.")
        return user

    def has_capability(self, user: WhitelistedUser, capability: str) -> bool:
        return capability in ROLE_CAPABILITIES.get(user.user_type, set())

    def assert_capability(self, user: WhitelistedUser, capability: str) -> None:
        self.ensure_active_user(user)
        if not self.has_capability(user, capability):
            raise PermissionError("Operazione non consentita per questo utente.")

    def can_modify_issue(self, user: WhitelistedUser, issue_id: str, now: datetime | None = None) -> bool:
        if user.user_type in {UserType.team, UserType.power}:
            return True
        if user.user_type != UserType.visitor:
            return False
        now = now or datetime.now(timezone.utc)
        owned = self.subscriptions.find_by_issue_and_email(issue_id, user.email)
        if not owned:
            return False
        return (now - owned.created_at) <= timedelta(minutes=30)


@dataclass(slots=True)
class AdminApprovalService:
    approvals: AdminApprovalRepository
    mailbox: any

    def create(self, message, plan, requester_name: str | None, requester_email: str) -> tuple[AdminApproval, str]:
        token = secrets.token_urlsafe(16)
        approval = AdminApproval(
            requester_email=requester_email,
            requester_name=requester_name,
            original_message_id=message.message_id,
            original_subject=message.subject,
            token_hash=self._hash_token(token),
            plan_payload=plan.model_dump(mode="json"),
            message_payload=message.model_dump(mode="json"),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        )
        self.approvals.upsert(approval.id, approval)
        self._send_approval_email(approval, token)
        return approval, token

    def approve_from_message(self, sender_email: str | None, text: str) -> AdminApproval | None:
        if not sender_email or sender_email.lower() != settings.super_admin_email.lower():
            return None
        token = self._extract_token(text)
        if not token:
            return None
        hashed = self._hash_token(token)
        for approval in self.approvals.list_all():
            if approval.token_hash != hashed:
                continue
            if approval.used_at is not None or approval.expires_at < datetime.now(timezone.utc):
                return None
            refreshed = approval.model_copy(update={"used_at": datetime.now(timezone.utc)})
            self.approvals.upsert(refreshed.id, refreshed)
            return refreshed
        return None

    def _send_approval_email(self, approval: AdminApproval, token: str) -> None:
        if not settings.super_admin_email:
            return
        lines = [
            "Richiesta admin-scope in attesa di approvazione.",
            "",
            f"Richiedente: {approval.requester_name or approval.requester_email}",
            f"Email: {approval.requester_email}",
            f"Oggetto: {approval.original_subject or '(senza oggetto)'}",
            "",
            "Reply a questa email includendo il token seguente:",
            token,
            "",
            "Il token scade tra 30 minuti.",
        ]
        self.mailbox.send_message(
            settings.super_admin_email,
            f"Approval richiesta: {approval.original_subject or approval.original_message_id}",
            "\n".join(lines),
        )

    def _extract_token(self, text: str) -> str | None:
        match = re.search(r"\b([A-Za-z0-9_\-]{20,})\b", text or "")
        return match.group(1) if match else None

    def _hash_token(self, token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class ProjectMatcher:
    directory: CustomerDirectoryRepository

    def match(
        self,
        text: str,
        sender: str | None = None,
        customer_label: str | None = None,
        project_id: str | None = None,
    ) -> ProjectMatch:
        if project_id:
            candidate = ProjectCandidate(
                project_id=project_id,
                confidence=1.0,
                reason="explicit project override",
            )
            return ProjectMatch(
                status="matched",
                candidates=[candidate],
                selected_project_id=project_id,
                needs_confirmation=False,
                question=None,
            )

        match_text = " ".join(part for part in [text, customer_label] if part)
        lowered = match_text.lower()
        sender = (sender or "").lower()
        candidates: list[ProjectCandidate] = []

        for rule in self.directory.list_all():
            score = 0.0
            reasons: list[str] = []
            if any(alias.lower() in lowered for alias in [rule.customer_label, *rule.aliases]):
                score += 0.55
                reasons.append("customer alias found")
            if sender and any(domain.lower() in sender for domain in rule.domains):
                score += 0.45
                reasons.append("sender domain matched")
            if score > 0 and rule.default_project_id:
                candidates.append(
                    ProjectCandidate(
                        project_id=rule.default_project_id,
                        confidence=min(score, 1.0),
                        reason=", ".join(reasons),
                    )
                )

        if not candidates:
            return ProjectMatch(
                status="unknown",
                candidates=[],
                needs_confirmation=True,
                question="Non riesco a capire il progetto cliente. Puoi indicarmi il progetto YouTrack?",
            )

        candidates.sort(key=lambda item: item.confidence, reverse=True)
        if len(candidates) > 1 and abs(candidates[0].confidence - candidates[1].confidence) < 0.2:
            return ProjectMatch(
                status="ambiguous",
                candidates=candidates,
                needs_confirmation=True,
                question="Ho trovato piu' progetti possibili. Quale devo usare?",
            )

        winner = candidates[0]
        return ProjectMatch(
            status="matched",
            candidates=candidates,
            selected_project_id=winner.project_id,
            needs_confirmation=winner.confidence < 0.65,
            question="Confermi il progetto scelto?" if winner.confidence < 0.65 else None,
        )


@dataclass(slots=True)
class RequestService:
    requests: RequestRepository
    matcher: ProjectMatcher

    def ingest(self, payload: IngestRequestInput) -> NormalizedRequest:
        requester_name, requester_email = parse_mail_identity(payload.sender)
        project_match = self.matcher.match(
            payload.text,
            payload.sender,
            customer_label=payload.customer_label,
            project_id=payload.project_id,
        )
        customer_label = payload.customer_label or project_match.selected_project_id or (
            project_match.candidates[0].project_id if project_match.candidates else None
        )
        urgency = "high" if "urgente" in payload.text.lower() else "medium"
        request = NormalizedRequest(
            source=payload.source,
            text=normalize_text(payload.text),
            sender=payload.sender,
            requester_email=requester_email,
            requester_name=requester_name,
            subject=payload.subject,
            customer_label=customer_label,
            urgency=urgency,
            context_snippets=split_sentences(payload.text)[:5],
            project_match=project_match,
            open_questions=[project_match.question] if project_match.question else [],
        )
        self.requests.upsert(request.id, request)
        return request


@dataclass(slots=True)
class PreviewService:
    requests: RequestRepository
    previews: PreviewRepository
    matcher: ProjectMatcher

    def build_preview(self, payload: PreviewInput) -> ActionPreview:
        if payload.request_id:
            request = self.requests.get(payload.request_id)
            if not request:
                raise ValueError(f"Unknown request_id {payload.request_id}")
            text = request.text
            project_match = self.matcher.match(
                text,
                request.sender,
                customer_label=payload.customer_label or request.customer_label,
                project_id=payload.project_id or request.project_match.selected_project_id,
            )
        elif payload.text:
            text = normalize_text(payload.text)
            project_match = self.matcher.match(
                text,
                customer_label=payload.customer_label,
                project_id=payload.project_id,
            )
            request = None
        else:
            raise ValueError("Either text or request_id must be provided.")

        issue_ops: list[IssueOperation] = []
        worklog_ops: list[WorklogOperation] = []
        knowledge_ops: list[KnowledgeOperation] = []
        open_questions = list(filter(None, [project_match.question]))
        explicit_worklog_comment = extract_explicit_worklog_comment(text)

        for chunk in split_sentences(text):
            lowered = chunk.lower()
            issue_id = extract_issue_reference(chunk)
            duration = extract_duration_minutes(chunk)

            if any(keyword in lowered for keyword in ["knowledge", "kb", "salvare", "salva", "script", "comando"]):
                knowledge_ops.append(
                    KnowledgeOperation(
                        project_id=project_match.selected_project_id or settings.personal_kb_project,
                        folder=settings.personal_kb_folder if "person" in lowered or "miei" in lowered else None,
                        title=self._knowledge_title(chunk),
                        content=normalize_markdown_text(chunk),
                        tags=["personale"] if "personal" in lowered or "miei" in lowered else [],
                        is_personal="personal" in lowered or "miei" in lowered,
                        needs_confirmation=project_match.status != "matched" and "personal" not in lowered and "miei" not in lowered,
                    )
                )
                continue

            if duration:
                needs_confirmation = False
                project_id = project_match.selected_project_id
                worklog_description = explicit_worklog_comment or chunk

                if not issue_id and not project_id:
                    needs_confirmation = True
                    open_questions.append(
                        f"Manca issue o progetto per registrare il tempo: '{chunk}'."
                    )
                if not issue_id and project_id and not settings.default_service_issue:
                    needs_confirmation = True
                    open_questions.append(
                        f"Manca un issue di servizio di default per il progetto {project_id}: '{chunk}'."
                    )

                worklog_ops.append(
                    WorklogOperation(
                        issue_id=issue_id or settings.default_service_issue or None,
                        project_id=project_id,
                        duration_minutes=duration,
                        description=worklog_description,
                        work_date=date.today(),
                        needs_confirmation=needs_confirmation,
                    )
                )

                if any(keyword in lowered for keyword in ["bug", "fix", "risolto", "feature", "ticket"]):
                    action = "update" if issue_id else "create"
                    summary, description = self._issue_content(explicit_worklog_comment or chunk)
                    issue_ops.append(
                        IssueOperation(
                            action=action,
                            project_id=project_id,
                            issue_id=issue_id,
                            summary=summary,
                            description=description,
                            assignee=self._default_issue_assignee(action),
                            confidence=0.65 if issue_id else 0.8,
                            needs_confirmation=project_match.status != "matched" or not issue_id,
                        )
                    )
                continue

            if any(
                keyword in lowered
                for keyword in ["bug", "fix", "risolto", "errore", "feature", "richiesta", "debug", "supporto"]
            ):
                action = "update" if issue_id else "create"
                summary, description = self._issue_content(chunk)
                issue_ops.append(
                    IssueOperation(
                        action=action,
                        project_id=project_match.selected_project_id,
                        issue_id=issue_id,
                        summary=summary,
                        description=description,
                        assignee=self._default_issue_assignee(action),
                        confidence=0.6 if issue_id else 0.75,
                        needs_confirmation=project_match.status != "matched" or not issue_id,
                    )
                )

        if not issue_ops and not worklog_ops and not knowledge_ops and text:
            summary, description = self._issue_content(text)
            issue_ops.append(
                IssueOperation(
                    action="create",
                    project_id=project_match.selected_project_id,
                    summary=summary,
                    description=description,
                    assignee=self._default_issue_assignee("create"),
                    confidence=0.7 if project_match.selected_project_id else 0.4,
                    needs_confirmation=project_match.status != "matched",
                )
            )

        requires_confirmation = (
            project_match.needs_confirmation
            or any(item.needs_confirmation for item in issue_ops)
            or any(item.needs_confirmation for item in worklog_ops)
            or any(item.needs_confirmation for item in knowledge_ops)
            or bool(open_questions)
        )

        preview = ActionPreview(
            request_id=request.id if payload.request_id and request else None,
            source_text=text,
            project_match=project_match,
            summary=self._preview_summary(project_match, issue_ops, worklog_ops, knowledge_ops),
            issue_operations=issue_ops,
            worklog_operations=worklog_ops,
            knowledge_operations=knowledge_ops,
            open_questions=open_questions,
            requires_confirmation=requires_confirmation,
        )
        self.previews.upsert(preview.preview_id, preview)

        if request:
            updated_request = request.model_copy(update={"status": RequestStatus.previewed})
            self.requests.upsert(updated_request.id, updated_request)
        return preview

    def _issue_summary(self, chunk: str) -> str:
        summary, _ = self._issue_content(chunk)
        return summary

    def _issue_content(self, chunk: str) -> tuple[str, str]:
        explicit_summary, explicit_description = self._extract_explicit_issue_content(chunk)
        summary = self._clean_issue_summary(explicit_summary or chunk)
        description = self._clean_issue_description(explicit_description or chunk, summary)
        return summary, description

    def _extract_explicit_issue_content(self, text: str) -> tuple[str | None, str | None]:
        stripped = normalize_text(text)
        summary_match = re.search(
            r'(?:issue|ticket)[^"\n:]*:\s*"([^"]+)"|(?:issue|ticket)[^"\n]*"([^"]+)"',
            stripped,
            re.IGNORECASE,
        )
        description_match = re.search(r'descrizione\s*:\s*"([^"]+)"', stripped, re.IGNORECASE)
        summary = None
        if summary_match:
            summary = summary_match.group(1) or summary_match.group(2)
        description = description_match.group(1) if description_match else None
        return summary, description

    def _clean_issue_summary(self, text: str) -> str:
        issue_ref = extract_issue_reference(text)
        stripped = text.replace(issue_ref, "", 1).strip() if issue_ref else ISSUE_ID_PATTERN.sub("", text).strip()
        patterns = [
            r"^(crea|apri|genera)\s+(un\s+)?(nuov[ao]\s+)?(issue|ticket)\s*:?\s*",
            r"^(crea|apri|genera)\s*:?\s*",
        ]
        for pattern in patterns:
            stripped = re.sub(pattern, "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r'\s+nel progetto\s+.+$', "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r'\s+con descrizione\s*:.*$', "", stripped, flags=re.IGNORECASE)
        stripped = stripped.strip().strip('"\' ')
        stripped = normalize_text(stripped)
        return stripped[:120] if stripped else "Attivita' cliente"

    def _clean_issue_description(self, text: str, summary: str) -> str:
        cleaned = normalize_markdown_text(text).strip().strip('"\' ')
        cleaned = re.sub(r"^(crea|apri|genera)\s+(un\s+)?(nuov[ao]\s+)?(issue|ticket)\s*:?\s*", "", cleaned, flags=re.IGNORECASE)
        if summary:
            summary_patterns = [
                rf'^"{re.escape(summary)}"\s*',
                rf"^{re.escape(summary)}\s*",
            ]
            for pattern in summary_patterns:
                cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^\s*(nel progetto\s+[^\"]+?)\s*(con descrizione\s*:)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^descrizione\s*:\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.strip().strip('"\' ')
        cleaned = normalize_markdown_text(cleaned)
        if not cleaned or normalize_match_token(cleaned) == normalize_match_token(summary):
            cleaned = normalize_markdown_text(text).strip()
        return cleaned

    def _knowledge_title(self, chunk: str) -> str:
        cleaned = chunk.replace('"', "").replace("'", "").strip()
        return cleaned[:80] if cleaned else "Nota operativa"

    def _preview_summary(
        self,
        project_match: ProjectMatch,
        issue_ops: list[IssueOperation],
        worklog_ops: list[WorklogOperation],
        knowledge_ops: list[KnowledgeOperation],
    ) -> str:
        project = project_match.selected_project_id or "progetto da confermare"
        return (
            f"Preview per {project}: {len(issue_ops)} issue, "
            f"{len(worklog_ops)} worklog, {len(knowledge_ops)} articoli KB."
        )

    def _default_issue_assignee(self, action: str) -> str | None:
        if action != "create":
            return None
        return settings.youtrack_default_assignee or None


@dataclass(slots=True)
class QueryService:
    directory: CustomerDirectoryRepository
    youtrack_client: any

    async def search_projects(self, query: str, include_archived: bool = False, limit: int = 10) -> list[ProjectSearchResult]:
        normalized_query = normalize_text(query).lower()
        projects = await self.youtrack_client.list_projects()
        results: list[ProjectSearchResult] = []

        for project in projects:
            archived = bool(project.get("archived"))
            if archived and not include_archived:
                pass
            score = 0.0
            reasons: list[str] = []
            matched_rule = self._matched_project_rule(project)
            project_values = [
                (project.get("shortName") or "").lower(),
                (project.get("name") or "").lower(),
                (project.get("id") or "").lower(),
            ]
            context = self._project_context(project, matched_rule)
            if normalized_query in project_values:
                score += 0.8
                reasons.append("exact project match")
            elif any(normalized_query and normalized_query in value for value in project_values):
                score += 0.55
                reasons.append("partial project match")

            if matched_rule:
                aliases = [matched_rule.customer_label, *matched_rule.aliases]
                if any(normalized_query == alias.lower() for alias in aliases):
                    score += 0.95
                    reasons.append(f"customer alias '{matched_rule.customer_label}' matched")
                elif any(normalized_query in alias.lower() for alias in aliases):
                    score += 0.65
                    reasons.append(f"customer alias '{matched_rule.customer_label}' partially matched")

            normalized_context = normalize_match_token(context)
            if normalized_query and normalized_context:
                if normalized_query == normalized_context:
                    score += 0.75
                    reasons.append("project context exact match")
                elif normalized_query in normalized_context:
                    score += 0.45
                    reasons.append("project context matched")

            if not archived:
                score += 0.05
                reasons.append("non archived priority")

            if score <= 0:
                continue
            if archived and not include_archived:
                continue
            results.append(
                ProjectSearchResult(
                    project_id=project.get("id"),
                    short_name=project.get("shortName") or project.get("id"),
                    name=project.get("name") or project.get("shortName") or project.get("id"),
                    context=context,
                    archived=archived,
                    confidence=min(score, 1.0),
                    reason=", ".join(dict.fromkeys(reasons)),
                )
            )

        results.sort(key=lambda item: (item.archived, -item.confidence, item.name.lower()))
        return results[:limit]

    async def get_project_metadata(self, project_id: str) -> ProjectMetadata | None:
        project = await self._project_details(project_id)
        if not project:
            return None
        matched_rule = self._matched_project_rule(project)
        return ProjectMetadata(
            project_id=project.get("id"),
            short_name=project.get("shortName") or project.get("id"),
            name=project.get("name") or project.get("shortName") or project.get("id"),
            description=project.get("description"),
            context=self._project_context(project, matched_rule),
            archived=bool(project.get("archived")),
            aliases=list(matched_rule.aliases) if matched_rule else [],
            domains=list(matched_rule.domains) if matched_rule else [],
            default_for_customer=matched_rule.customer_label if matched_rule else None,
            reason="customer directory rule matched" if matched_rule else None,
        )

    async def update_project_description(self, project_id: str, description: str) -> ProjectMetadata | None:
        await self.youtrack_client.update_project(project_id, {"description": description.strip()})
        return await self.get_project_metadata(project_id)

    async def update_project_archived_state(self, project_id: str, archived: bool) -> ProjectMetadata | None:
        await self.youtrack_client.update_project(project_id, {"archived": archived})
        return await self.get_project_metadata(project_id)

    async def list_project_issues(
        self,
        project_id: str,
        *,
        query: str | None = None,
        only_open: bool = False,
        assignee: str | None = None,
        updated_since: date | None = None,
        limit: int = 20,
    ) -> list[IssueSearchResult]:
        project_ref = await self._project_query_reference(project_id)
        query_parts = [f"project: {project_ref}"]
        if query:
            query_parts.append(query)
        issues = await self.youtrack_client.search_issues(" ".join(query_parts).strip(), limit=max(limit, 50))
        return self._normalize_issues(
            issues,
            query=query,
            only_open=only_open,
            assignee=assignee,
            updated_since=updated_since,
            limit=limit,
        )

    async def search_issues(
        self,
        query: str,
        *,
        project_id: str | None = None,
        only_open: bool = False,
        assignee: str | None = None,
        updated_since: date | None = None,
        limit: int = 20,
    ) -> list[IssueSearchResult]:
        query_parts: list[str] = []
        if project_id:
            project_ref = await self._project_query_reference(project_id)
            query_parts.append(f"project: {project_ref}")
        if query:
            query_parts.append(query)
        issues = await self.youtrack_client.search_issues(" ".join(query_parts).strip(), limit=max(limit, 50))
        return self._normalize_issues(
            issues,
            query=query,
            only_open=only_open,
            assignee=assignee,
            updated_since=updated_since,
            limit=limit,
        )

    async def summarize_project_time(self, project_id: str, date_from: date, date_to: date) -> TimeTrackingSummary:
        issues = await self.list_project_issues(project_id, limit=100, only_open=False)
        total_minutes = 0
        per_issue: dict[str, TimeTrackingIssueSummary] = {}
        per_author: dict[str, int] = defaultdict(int)

        for issue in issues:
            work_items = await self.youtrack_client.list_issue_work_items(issue.issue_id_readable)
            for item in work_items:
                work_date = utc_datetime_from_millis(item.get("date"))
                if not work_date:
                    continue
                day = work_date.date()
                if day < date_from or day > date_to:
                    continue
                minutes = ((item.get("duration") or {}).get("minutes")) or 0
                total_minutes += minutes
                if issue.issue_id not in per_issue:
                    per_issue[issue.issue_id] = TimeTrackingIssueSummary(
                        issue_id=issue.issue_id,
                        issue_id_readable=issue.issue_id_readable,
                        summary=issue.summary,
                        issue_url=issue.url,
                    )
                per_issue[issue.issue_id].minutes += minutes
                author = ((item.get("author") or {}).get("fullName")) or ((item.get("author") or {}).get("login")) or "Unknown"
                per_author[author] += minutes

        issue_breakdown = list(per_issue.values())
        for item in issue_breakdown:
            item.hours = round(item.minutes / 60, 2)
        issue_breakdown.sort(key=lambda item: item.minutes, reverse=True)

        author_breakdown = [
            TimeTrackingAuthorSummary(author=author, minutes=minutes, hours=round(minutes / 60, 2))
            for author, minutes in sorted(per_author.items(), key=lambda pair: pair[1], reverse=True)
        ]

        project = await self._project_details(project_id)
        return TimeTrackingSummary(
            project_id=project_id,
            project_name=project.get("name") if project else None,
            date_from=date_from,
            date_to=date_to,
            total_minutes=total_minutes,
            total_hours=round(total_minutes / 60, 2),
            issue_breakdown=issue_breakdown,
            author_breakdown=author_breakdown,
        )

    async def summarize_time_report(
        self,
        date_from: date,
        date_to: date,
        *,
        author_hint: str | None = None,
        include_archived: bool = False,
    ) -> GlobalTimeTrackingSummary:
        projects = await self.youtrack_client.list_projects()
        project_minutes: dict[str, TimeTrackingProjectSummary] = {}
        issue_sets: dict[str, set[str]] = defaultdict(set)
        total_minutes = 0

        for project in projects:
            if project.get("archived") and not include_archived:
                continue
            issues = await self.list_project_issues(project.get("id"), limit=100, only_open=False)
            for issue in issues:
                work_items = await self.youtrack_client.list_issue_work_items(issue.issue_id_readable)
                for item in work_items:
                    work_date = utc_datetime_from_millis(item.get("date"))
                    if not work_date:
                        continue
                    day = work_date.date()
                    if day < date_from or day > date_to:
                        continue
                    if not matches_author_hint(item.get("author"), author_hint):
                        continue

                    minutes = ((item.get("duration") or {}).get("minutes")) or 0
                    if minutes <= 0:
                        continue
                    project_id = project.get("id")
                    if project_id not in project_minutes:
                        project_minutes[project_id] = TimeTrackingProjectSummary(
                            project_id=project_id,
                            project_name=project.get("name") or project.get("shortName") or project_id,
                        )
                    project_minutes[project_id].minutes += minutes
                    issue_sets[project_id].add(issue.issue_id)
                    total_minutes += minutes

        breakdown = list(project_minutes.values())
        for item in breakdown:
            item.hours = round(item.minutes / 60, 2)
            item.issue_count = len(issue_sets[item.project_id])
        breakdown.sort(key=lambda item: item.minutes, reverse=True)

        return GlobalTimeTrackingSummary(
            date_from=date_from,
            date_to=date_to,
            author_hint=author_hint,
            total_minutes=total_minutes,
            total_hours=round(total_minutes / 60, 2),
            project_breakdown=breakdown,
        )

    async def list_project_articles(self, project_id: str, query: str | None = None, limit: int = 20) -> list[ArticleSearchResult]:
        project = await self._project_details(project_id)
        project_name = project.get("name") if project else project_id
        raw_articles = await self.youtrack_client.search_articles(query or "", limit=max(limit, 50))
        filtered = [
            article
            for article in raw_articles
            if ((article.get("project") or {}).get("id") == project_id)
            or ((article.get("project") or {}).get("name") == project_name)
        ]
        return self._normalize_articles(filtered, limit=limit)

    async def search_articles(self, query: str, project_id: str | None = None, limit: int = 20) -> list[ArticleSearchResult]:
        raw_articles = await self.youtrack_client.search_articles(query, limit=max(limit, 50))
        if project_id:
            raw_articles = [
                article
                for article in raw_articles
                if ((article.get("project") or {}).get("id") == project_id)
                or ((article.get("project") or {}).get("shortName") == project_id)
            ]
        return self._normalize_articles(raw_articles, limit=limit)

    async def build_project_context(self, hint: str, limit: int = 10) -> AssistantProjectContext | None:
        projects = await self.search_projects(hint, include_archived=False, limit=1)
        if not projects:
            return None
        project = projects[0]
        open_issues = await self.list_project_issues(project.project_id, only_open=True, limit=limit)
        articles = await self.list_project_articles(project.project_id, limit=min(limit, 5))
        return AssistantProjectContext(project=project, open_issues=open_issues, recent_articles=articles)

    def _normalize_issues(
        self,
        issues: list[dict],
        *,
        query: str | None,
        only_open: bool,
        assignee: str | None,
        updated_since: date | None,
        limit: int,
    ) -> list[IssueSearchResult]:
        query_lower = (query or "").lower()
        assignee_lower = (assignee or "").lower()
        results: list[IssueSearchResult] = []
        for issue in issues:
            resolved = bool(issue.get("resolved"))
            if only_open and resolved:
                continue
            state = issue_state_name(issue)
            parsed_assignee = issue_assignee_name(issue)
            updated_at = utc_datetime_from_millis(issue.get("updated"))
            if assignee_lower and (parsed_assignee or "").lower() != assignee_lower:
                continue
            if updated_since and updated_at and updated_at.date() < updated_since:
                continue

            score = 0.2 if not resolved else 0.0
            reasons: list[str] = []
            summary_lower = (issue.get("summary") or "").lower()
            if query_lower:
                if query_lower in summary_lower:
                    score += 0.55
                    reasons.append("summary matched query")
                if state and query_lower in state.lower():
                    score += 0.15
                    reasons.append("state matched query")
                if any(keyword in summary_lower for keyword in ["supporto", "call", "meet", "meeting"]):
                    score += 0.1
                    reasons.append("operational issue keyword")
            if updated_at:
                age_days = max((datetime.now(timezone.utc) - updated_at).days, 0)
                if age_days <= 14:
                    score += 0.1
                    reasons.append("recently updated")

            project = issue.get("project") or {}
            issue_id_readable = issue.get("idReadable") or issue.get("id")
            results.append(
                IssueSearchResult(
                    issue_id=issue.get("id"),
                    issue_id_readable=issue_id_readable,
                    summary=issue.get("summary") or issue_id_readable,
                    project_id=project.get("id"),
                    project_short_name=project.get("shortName"),
                    project_name=project.get("name"),
                    state=state,
                    assignee=parsed_assignee,
                    resolved=resolved,
                    updated_at=updated_at,
                    url=self.youtrack_client.issue_url(issue_id_readable),
                    score=min(score, 1.0),
                    reason=", ".join(reasons) if reasons else None,
                )
            )

        results.sort(key=lambda item: (item.resolved, -(item.score or 0), -(item.updated_at.timestamp() if item.updated_at else 0)))
        return results[:limit]

    def _normalize_articles(self, articles: list[dict], *, limit: int) -> list[ArticleSearchResult]:
        results = [
            ArticleSearchResult(
                article_id=article.get("id"),
                article_id_readable=article.get("idReadable"),
                summary=article.get("summary") or article.get("idReadable") or article.get("id"),
                project_id=(article.get("project") or {}).get("id"),
                project_name=(article.get("project") or {}).get("name"),
                updated_at=utc_datetime_from_millis(article.get("updated")),
                url=self.youtrack_client.issue_url(article.get("idReadable") or article.get("id")),
            )
            for article in articles
        ]
        results.sort(key=lambda item: -(item.updated_at.timestamp() if item.updated_at else 0))
        return results[:limit]

    async def _project_query_reference(self, project_id: str) -> str:
        project = await self._project_details(project_id)
        if not project:
            return project_id
        return project.get("shortName") or project.get("id") or project_id

    async def _project_details(self, project_id: str) -> dict | None:
        try:
            return await self.youtrack_client.get_project(project_id)
        except Exception:
            projects = await self.youtrack_client.list_projects()
            for project in projects:
                if project.get("id") == project_id or project.get("shortName") == project_id or project.get("name") == project_id:
                    return project
            return None

    def _matched_project_rule(self, project: dict):
        for rule in self.directory.list_all():
            if (
                project.get("id") == rule.default_project_id
                or project.get("id") in rule.project_ids
                or project.get("shortName") in rule.project_ids
            ):
                return rule
        return None

    def _project_context(self, project: dict, matched_rule) -> str | None:
        parts: list[str] = []
        description = (project.get("description") or "").strip()
        if description:
            parts.append(description)
        if matched_rule:
            alias_text = ", ".join([matched_rule.customer_label, *matched_rule.aliases]).strip(", ")
            if alias_text:
                parts.append(f"Aliases: {alias_text}")
            if matched_rule.domains:
                parts.append(f"Domains: {', '.join(matched_rule.domains)}")
        context = " | ".join(part for part in parts if part)
        return context or None


@dataclass(slots=True)
class CommitService:
    previews: PreviewRepository
    commits: CommitRepository
    requests: RequestRepository
    youtrack_client: any

    async def commit(self, payload: CommitInput) -> CommitResult:
        existing = self.commits.find_by_preview_id(payload.preview_id)
        if existing:
            return existing.model_copy(update={"status": "duplicate"})

        preview = self.previews.get(payload.preview_id)
        if not preview:
            raise ValueError(f"Unknown preview_id {payload.preview_id}")
        if preview.requires_confirmation and not payload.confirm:
            blocked = CommitResult(
                preview_id=preview.preview_id,
                status="blocked",
                summary="Commit bloccato: sono presenti domande aperte o conferme richieste.",
                errors=preview.open_questions or ["Preview requires confirmation."],
            )
            self.commits.upsert(blocked.commit_id, blocked)
            return blocked

        issue_results: list[OperationResult] = []
        worklog_results: list[OperationResult] = []
        knowledge_results: list[OperationResult] = []
        errors: list[str] = []

        for index, operation in enumerate(preview.issue_operations, start=1):
            try:
                if operation.action == "create":
                    request_payload = {
                        "summary": operation.summary,
                        "description": operation.description,
                        "project": {"id": operation.project_id},
                    }
                    response = await self.youtrack_client.create_issue(request_payload)
                    assignment_error = None
                    if operation.assignee:
                        assignment_error = await self._assign_issue(response, operation.assignee)
                        if assignment_error:
                            errors.append(assignment_error)
                else:
                    response = await self.youtrack_client.update_issue(
                        operation.issue_id,
                        {"summary": operation.summary, "description": operation.description},
                    )
                    assignment_error = None
                    if operation.assignee:
                        assignment_error = await self._assign_issue(response, operation.assignee)
                        if assignment_error:
                            errors.append(assignment_error)
                issue_results.append(
                    OperationResult(
                        kind=ActionKind.issue,
                        status="success",
                        local_ref=f"issue_{index}",
                        remote_id=response.get("idReadable") or response.get("id"),
                        message="Issue sincronizzata." if not assignment_error else "Issue sincronizzata con warning.",
                        payload={
                            **response,
                            "url": self.youtrack_client.issue_url(response.get("idReadable") or response.get("id")),
                            "assignee": operation.assignee,
                            "assignment_error": assignment_error,
                        },
                    )
                )
            except Exception as exc:
                errors.append(str(exc))
                issue_results.append(
                    OperationResult(
                        kind=ActionKind.issue,
                        status="error",
                        local_ref=f"issue_{index}",
                        message=str(exc),
                    )
                )

        for index, operation in enumerate(preview.worklog_operations, start=1):
            try:
                if not operation.issue_id:
                    raise ValueError("Missing issue_id for worklog operation.")
                response = await self.youtrack_client.add_work_item(
                    operation.issue_id,
                    {
                        "text": operation.description,
                        "date": int(operation.work_date.strftime("%s")) * 1000,
                        "duration": {"minutes": operation.duration_minutes},
                    },
                )
                worklog_results.append(
                    OperationResult(
                        kind=ActionKind.worklog,
                        status="success",
                        local_ref=f"worklog_{index}",
                        remote_id=response.get("id"),
                        message="Work item creato.",
                        payload={
                            **response,
                            "issue_id": operation.issue_id,
                            "issue_url": self.youtrack_client.issue_url(operation.issue_id),
                        },
                    )
                )
            except Exception as exc:
                errors.append(str(exc))
                worklog_results.append(
                    OperationResult(
                        kind=ActionKind.worklog,
                        status="error",
                        local_ref=f"worklog_{index}",
                        message=str(exc),
                    )
                )

        for index, operation in enumerate(preview.knowledge_operations, start=1):
            try:
                response = await self.youtrack_client.create_article(
                    {
                        "summary": operation.title,
                        "content": normalize_markdown_text(operation.content),
                        "project": {"id": operation.project_id or settings.personal_kb_project},
                    }
                )
                knowledge_results.append(
                    OperationResult(
                        kind=ActionKind.knowledge,
                        status="success",
                        local_ref=f"knowledge_{index}",
                        remote_id=response.get("idReadable") or response.get("id"),
                        message="Articolo KB creato.",
                        payload={
                            **response,
                            "url": self.youtrack_client.issue_url(response.get("idReadable") or response.get("id")),
                        },
                    )
                )
            except Exception as exc:
                errors.append(str(exc))
                knowledge_results.append(
                    OperationResult(
                        kind=ActionKind.knowledge,
                        status="error",
                        local_ref=f"knowledge_{index}",
                        message=str(exc),
                    )
                )

        success_count = sum(
            1
            for result in [*issue_results, *worklog_results, *knowledge_results]
            if result.status == "success"
        )
        status = "success"
        if errors and success_count > 0:
            status = "partial_success"
        elif errors:
            status = "blocked"

        result = CommitResult(
            preview_id=preview.preview_id,
            status=status,
            summary="Commit completato." if not errors else "Commit completato con errori parziali.",
            issue_results=issue_results,
            worklog_results=worklog_results,
            knowledge_results=knowledge_results,
            errors=errors,
        )
        self.commits.upsert(result.commit_id, result)

        if preview.request_id:
            request = self.requests.get(preview.request_id)
            if request:
                updated_request = request.model_copy(update={"status": RequestStatus.committed})
                self.requests.upsert(updated_request.id, updated_request)
        return result

    async def list_issue_fields(self, issue_id: str) -> list[IssueFieldMetadata]:
        fields = await self.youtrack_client.list_issue_custom_fields(issue_id)
        return [await self._normalize_issue_field(issue_id, field) for field in fields]

    async def list_issue_transitions(self, issue_id: str) -> list[IssueFieldOption]:
        fields = await self.list_issue_fields(issue_id)
        transitions: list[IssueFieldOption] = []
        for field in fields:
            if field.possible_events:
                transitions.extend(field.possible_events)
        seen: set[tuple[str | None, str]] = set()
        deduped: list[IssueFieldOption] = []
        for item in transitions:
            key = (item.id, item.name)
            if key in seen:
                continue
            deduped.append(item)
            seen.add(key)
        return deduped

    async def assign_issue_by_id(self, issue_id: str, assignee: str) -> dict:
        issue = await self.youtrack_client.get_issue(issue_id)
        issue_ref = issue.get("idReadable") or issue.get("id") or issue_id
        assignment_error = await self._assign_issue({"idReadable": issue_ref, "id": issue.get("id")}, assignee)
        refreshed = await self.youtrack_client.get_issue(issue_ref)
        return {
            **refreshed,
            "url": self.youtrack_client.issue_url(refreshed.get("idReadable") or refreshed.get("id")),
            "assignment_error": assignment_error,
        }

    async def update_issue_state_by_id(self, issue_id: str, state_input: str) -> dict:
        fields = await self.youtrack_client.list_issue_custom_fields(issue_id)
        state_candidates = [
            field for field in fields
            if (field.get("$type") or "").lower() in {"stateissuecustomfield", "statemachineissuecustomfield"}
            or (field.get("name") or "").lower() == "state"
        ]
        if not state_candidates:
            raise ValueError(f"No state field found for issue {issue_id}.")
        candidate = state_candidates[0]
        field_id = candidate.get("id")
        if not field_id:
            raise ValueError(f"State field for issue {issue_id} has no field id.")
        detailed_field = await self.youtrack_client.get_issue_custom_field(issue_id, field_id)
        field_type = detailed_field.get("$type") or "StateIssueCustomField"
        resolution = self._resolve_issue_field_value(
            field=detailed_field,
            raw_input=state_input,
            value_type="transition" if "statemachine" in field_type.lower() else "status",
        )
        if not resolution.selected:
            raise ValueError(f"Could not resolve state '{state_input}' for issue {issue_id}.")
        if "statemachine" in field_type.lower():
            payload = {
                "id": detailed_field.get("id"),
                "name": detailed_field.get("name"),
                "$type": field_type,
                "event": {"id": resolution.selected.id} if resolution.selected.id else {"name": resolution.selected.name},
            }
        else:
            payload = {
                "id": detailed_field.get("id"),
                "name": detailed_field.get("name"),
                "$type": field_type,
                "value": {"name": resolution.selected.name},
            }
        await self.youtrack_client.update_issue_custom_field(issue_id, field_id, payload)
        refreshed = await self.youtrack_client.get_issue(issue_id)
        return {
            **refreshed,
            "url": self.youtrack_client.issue_url(refreshed.get("idReadable") or refreshed.get("id")),
            "resolved_state": resolution.selected.model_dump(),
        }

    async def resolve_value(
        self,
        *,
        value_type: str,
        raw_input: str,
        project_id: str | None = None,
        issue_id: str | None = None,
        field_name: str | None = None,
    ) -> ResolveValueResult:
        selected: IssueFieldOption | None = None
        candidates: list[IssueFieldOption] = []
        if value_type == "assignee":
            if not issue_id:
                raise ValueError("issue_id is required to resolve 'assignee'.")
            assignee_resolution = await self._resolve_assignee_candidates(issue_id, raw_input)
            candidates = assignee_resolution.candidates
            selected = assignee_resolution.selected
            field_name = field_name or assignee_resolution.field_name
        elif value_type in {"status", "transition", "issue_field", "priority"}:
            if not issue_id:
                raise ValueError(f"issue_id is required to resolve '{value_type}'.")
            fields = await self.youtrack_client.list_issue_custom_fields(issue_id)
            matching_fields = fields
            if field_name:
                matching_fields = [field for field in fields if normalize_match_token(field.get("name")) == normalize_match_token(field_name)]
            resolved_field = None
            field_resolution = None
            for field in matching_fields:
                field_id = field.get("id")
                if not field_id:
                    continue
                detailed_field = await self.youtrack_client.get_issue_custom_field(issue_id, field_id)
                field_resolution = self._resolve_issue_field_value(detailed_field, raw_input, value_type)
                if field_resolution.candidates:
                    resolved_field = detailed_field
                    break
            if field_resolution:
                candidates = field_resolution.candidates
                selected = field_resolution.selected
                field_name = field_name or (resolved_field or {}).get("name")
        else:
            raise ValueError(f"Unsupported resolve-value type '{value_type}'.")
        ambiguous = len(candidates) > 1 and selected is not None and (candidates[1].score or 0) >= (selected.score or 0) - 0.08
        return ResolveValueResult(
            type=value_type,
            input=raw_input,
            issue_id=issue_id,
            project_id=project_id,
            field_name=field_name,
            selected=selected,
            candidates=candidates,
            ambiguous=ambiguous,
            needs_clarification=selected is None or ambiguous or (selected.score or 0) < 0.6,
        )

    async def _assign_issue(self, response: dict, assignee: str) -> str | None:
        issue_ref = response.get("idReadable") or response.get("id")
        if not issue_ref:
            return f"Assignee '{assignee}' not applied because the created issue has no readable reference."

        field_candidates = await self._assignee_field_candidates(issue_ref)
        if not field_candidates:
            return f"Assignee '{assignee}' could not be applied to {issue_ref}: no compatible issue custom field was found."
        field_candidates = self._preferred_assignee_candidates(field_candidates)

        resolved_assignee = await self._resolve_assignee_option(issue_ref, assignee)
        value_variants = self._assignee_value_variants(assignee, resolved_assignee)

        last_error = None
        attempted_fields: list[str] = []
        for candidate in field_candidates:
            field_id = candidate.get("id")
            field_name = candidate.get("name")
            field_type = candidate.get("$type") or "SingleUserIssueCustomField"
            attempted_fields.append(field_name or field_id or "unknown-field")
            for value in value_variants:
                try:
                    logger = logging.getLogger(__name__)
                    logger.info(
                        "Trying assignee update issue=%s field_id=%s field_name=%s field_type=%s value_keys=%s",
                        issue_ref,
                        field_id,
                        field_name,
                        field_type,
                        ",".join(sorted(value.keys())),
                    )
                    if field_id:
                        payload = {
                            "id": field_id,
                            "name": field_name,
                            "$type": field_type,
                            "value": value,
                        }
                        await self.youtrack_client.update_issue_custom_field(issue_ref, field_id, payload)
                    else:
                        await self.youtrack_client.update_issue(
                            issue_ref,
                            {
                                "customFields": [
                                    {
                                        "name": field_name,
                                        "$type": field_type,
                                        "value": value,
                                    }
                                ]
                            },
                        )
                    return None
                except Exception as exc:
                    last_error = str(exc)
                    logging.getLogger(__name__).warning(
                        "Assignee update attempt failed issue=%s field_id=%s field_name=%s value=%s error=%s",
                        issue_ref,
                        field_id,
                        field_name,
                        value,
                        exc,
                    )
        attempted_fields_label = ", ".join(dict.fromkeys(filter(None, attempted_fields)))
        return (
            f"Assignee '{assignee}' could not be applied to {issue_ref}: {last_error}. "
            f"Attempted fields: {attempted_fields_label or 'none'}"
        )

    async def _normalize_issue_field(self, issue_id: str, field: dict) -> IssueFieldMetadata:
        enriched_field = await self._enrich_issue_field_bundle(issue_id, field)
        return IssueFieldMetadata(
            id=enriched_field.get("id") or "",
            name=enriched_field.get("name") or "",
            field_type=enriched_field.get("$type") or "",
            current_value=enriched_field.get("value"),
            can_be_empty=((enriched_field.get("projectCustomField") or {}).get("canBeEmpty")),
            possible_values=self._field_options_from_bundle(enriched_field),
            possible_events=self._field_options_from_events(enriched_field),
        )

    def _field_options_from_bundle(self, field: dict) -> list[IssueFieldOption]:
        bundle = ((field.get("projectCustomField") or {}).get("bundle")) or {}
        field_type = (field.get("$type") or "").lower()
        values = []
        if "userissuecustomfield" in field_type:
            values = bundle.get("aggregatedUsers") or bundle.get("individuals") or bundle.get("values") or []
        else:
            values = bundle.get("values") or []
        options: list[IssueFieldOption] = []
        for value in values:
            name = value.get("name") or value.get("presentation") or value.get("fullName") or value.get("login")
            if not name:
                continue
            options.append(
                IssueFieldOption(
                    id=value.get("id"),
                    name=name,
                    presentation=value.get("presentation"),
                    login=value.get("login"),
                    full_name=value.get("fullName"),
                    email=value.get("email"),
                )
            )
        return options

    def _field_options_from_events(self, field: dict) -> list[IssueFieldOption]:
        events = field.get("possibleEvents") or []
        return [
            IssueFieldOption(id=item.get("id"), name=item.get("name") or item.get("presentation") or "", presentation=item.get("presentation"))
            for item in events
            if item.get("name") or item.get("presentation")
        ]

    def _resolve_issue_field_value(self, field: dict, raw_input: str, value_type: str) -> ResolveValueResult:
        candidates: list[IssueFieldOption] = []
        if value_type == "transition":
            base_options = self._field_options_from_events(field)
        else:
            base_options = self._field_options_from_bundle(field)
        for option in base_options:
            score = max(
                similarity_score(raw_input, option.name),
                similarity_score(raw_input, option.presentation),
                similarity_score(raw_input, option.login),
                similarity_score(raw_input, option.full_name),
                similarity_score(raw_input, option.email),
            )
            if score <= 0:
                continue
            candidates.append(option.model_copy(update={"score": round(score, 3), "reason": "fuzzy/name match"}))
        candidates.sort(key=lambda item: (-(item.score or 0), item.name.lower()))
        selected = candidates[0] if candidates else None
        return ResolveValueResult(
            type=value_type,
            input=raw_input,
            issue_id=None,
            project_id=None,
            field_name=field.get("name"),
            selected=selected,
            candidates=candidates[:10],
            ambiguous=len(candidates) > 1 and (candidates[1].score or 0) >= ((selected.score or 0) - 0.08) if selected else False,
            needs_clarification=selected is None,
        )

    async def _resolve_assignee_candidates(self, issue_id: str, raw_input: str) -> ResolveValueResult:
        candidates: list[IssueFieldOption] = []
        selected: IssueFieldOption | None = None
        resolved_field_name: str | None = None
        fields = await self.list_issue_fields(issue_id)
        assignee_fields = [
            field
            for field in fields
            if "userissuecustomfield" in field.field_type.lower()
            and any(token in field.name.lower() for token in ["assignee", "team", "owner"])
        ]
        for field in assignee_fields:
            field_candidates = self._resolve_issue_field_value(
                {
                    "name": field.name,
                    "$type": field.field_type,
                    "projectCustomField": {
                        "bundle": {
                            "aggregatedUsers": [item.model_dump(exclude_none=True) for item in field.possible_values],
                        }
                    },
                },
                raw_input,
                "assignee",
            )
            if field_candidates.candidates:
                candidates = field_candidates.candidates
                selected = field_candidates.selected
                resolved_field_name = field.name
                break

        configured = (settings.youtrack_default_assignee or "").strip()
        configured_login = (settings.youtrack_default_assignee_login or "").strip()
        if not candidates and configured:
            score = max(similarity_score(raw_input, configured), similarity_score(raw_input, configured_login))
            if score > 0:
                candidates.append(
                    IssueFieldOption(
                        id=configured_login or None,
                        name=configured,
                        presentation=configured_login or None,
                        login=configured_login or None,
                        score=round(score, 3),
                        reason="configured default assignee",
                    )
                )
        deduped: list[IssueFieldOption] = []
        seen = set()
        for item in sorted(candidates, key=lambda candidate: -(candidate.score or 0)):
            key = (item.id, item.name, item.login)
            if key in seen:
                continue
            deduped.append(item)
            seen.add(key)
        selected = deduped[0] if deduped else None
        ambiguous = len(deduped) > 1 and selected is not None and (deduped[1].score or 0) >= ((selected.score or 0) - 0.08)
        return ResolveValueResult(
            type="assignee",
            input=raw_input,
            issue_id=issue_id,
            field_name=resolved_field_name,
            selected=selected,
            candidates=deduped[:10],
            ambiguous=ambiguous,
            needs_clarification=selected is None or ambiguous or (selected.score or 0) < 0.6,
        )

    async def _assignee_field_candidates(self, issue_ref: str) -> list[dict]:
        try:
            issue_fields = await self.youtrack_client.list_issue_custom_fields(issue_ref)
        except Exception:
            configured_name = settings.youtrack_assignee_field_name
            if not configured_name:
                return []
            return [{"id": None, "name": configured_name, "$type": "SingleUserIssueCustomField"}]

        candidates: list[dict] = []
        fallback_candidates: list[dict] = []
        for field in issue_fields or []:
            name = field.get("name")
            field_type = field.get("$type") or ""
            lowered_name = (name or "").lower()
            if "userissuecustomfield" in field_type.lower():
                candidates.append(field)
                continue
            if any(token in lowered_name for token in ["assignee", "team", "owner"]):
                fallback_candidates.append(
                    {
                        "id": field.get("id"),
                        "name": name,
                        "$type": field_type or "SingleUserIssueCustomField",
                    }
                )

        configured_name = settings.youtrack_assignee_field_name
        if configured_name:
            fallback_candidates.append({"id": None, "name": configured_name, "$type": "SingleUserIssueCustomField"})

        deduped: list[dict] = []
        seen = set()
        for candidate in [*candidates, *fallback_candidates]:
            key = (candidate.get("id"), candidate.get("name"), candidate.get("$type"))
            if key in seen:
                continue
            deduped.append(candidate)
            seen.add(key)
        return sorted(deduped, key=self._assignee_candidate_priority, reverse=True)

    def _assignee_value_variants(self, assignee: str, resolved_option: IssueFieldOption | None = None) -> list[dict]:
        normalized_assignee = (assignee or "").strip()
        default_assignee = (settings.youtrack_default_assignee or "").strip().lower()
        configured_login = (settings.youtrack_default_assignee_login or "").strip()
        variants: list[dict] = []
        if resolved_option:
            if resolved_option.id:
                variants.append({"id": resolved_option.id})
            if resolved_option.login:
                variants.append({"login": resolved_option.login})
            if resolved_option.full_name:
                variants.append({"fullName": resolved_option.full_name})
            variants.append({"name": resolved_option.name})
        if configured_login and normalized_assignee.lower() == default_assignee:
            variants.append({"login": configured_login})
        variants.extend(
            [
                {"login": normalized_assignee},
                {"fullName": normalized_assignee},
                {"name": normalized_assignee},
            ]
        )
        deduped: list[dict] = []
        seen = set()
        for item in variants:
            key = tuple(item.items())
            if key in seen:
                continue
            deduped.append(item)
            seen.add(key)
        return deduped

    async def _resolve_assignee_option(self, issue_ref: str, raw_input: str) -> IssueFieldOption | None:
        resolution = await self._resolve_assignee_candidates(issue_ref, raw_input)
        return resolution.selected

    async def _enrich_issue_field_bundle(self, issue_id: str, field: dict) -> dict:
        if "userissuecustomfield" not in (field.get("$type") or "").lower():
            return field
        bundle = ((field.get("projectCustomField") or {}).get("bundle")) or {}
        if bundle.get("aggregatedUsers"):
            return field
        bundle_id = bundle.get("id")
        if not bundle_id or not hasattr(self.youtrack_client, "get_user_bundle"):
            return field
        try:
            user_bundle = await self.youtrack_client.get_user_bundle(bundle_id)
        except Exception:
            return field
        enriched = dict(field)
        project_custom_field = dict((field.get("projectCustomField") or {}))
        merged_bundle = dict(bundle)
        merged_bundle.update(user_bundle or {})
        project_custom_field["bundle"] = merged_bundle
        enriched["projectCustomField"] = project_custom_field
        return enriched

    def _preferred_assignee_candidates(self, candidates: list[dict]) -> list[dict]:
        if not candidates:
            return []
        scored = [(candidate, self._assignee_candidate_priority(candidate)) for candidate in candidates]
        max_score = max(score for _, score in scored)
        if max_score <= 0:
            return candidates
        preferred = [candidate for candidate, score in scored if score == max_score]
        return preferred or candidates

    def _assignee_candidate_priority(self, candidate: dict) -> int:
        configured_name = (settings.youtrack_assignee_field_name or "").strip().lower()
        field_name = (candidate.get("name") or "").strip().lower()
        project_field_name = (
            (((candidate.get("projectCustomField") or {}).get("field") or {}).get("name") or "").strip().lower()
        )
        field_type = (candidate.get("$type") or "").lower()

        score = 0
        if configured_name and field_name == configured_name:
            score += 200
        if configured_name and project_field_name == configured_name:
            score += 180
        if configured_name and configured_name and configured_name in field_name:
            score += 80
        if "assignee" in field_name or "owner" in field_name:
            score += 60
        if "team" in field_name:
            score += 50
        if "userissuecustomfield" in field_type:
            score += 40
        if candidate.get("id"):
            score += 10
        return score


@dataclass(slots=True)
class IssueSubscriptionService:
    subscriptions: IssueSubscriptionRepository
    youtrack_client: any
    mailbox: any

    async def subscribe(self, issue_id_readable: str, requester_email: str, *, requester_name: str | None = None, source_subject: str | None = None) -> IssueSubscription:
        existing = self.subscriptions.find_by_issue_and_email(issue_id_readable, requester_email)
        if existing:
            return existing

        issue = await self.youtrack_client.get_issue(issue_id_readable)
        snapshot = await self._snapshot(issue_id_readable, issue=issue)
        subscription = IssueSubscription(
            issue_id=issue.get("id") or issue_id_readable,
            issue_id_readable=issue.get("idReadable") or issue_id_readable,
            summary=issue.get("summary") or issue_id_readable,
            requester_email=requester_email.lower(),
            requester_name=requester_name,
            source_subject=source_subject,
            state=snapshot["state"],
            assignee=snapshot["assignee"],
            resolved=snapshot["resolved"],
            updated_at=snapshot["updated_at"],
            worklog_count=snapshot["worklog_count"],
            total_minutes=snapshot["total_minutes"],
            last_worklog_at=snapshot["last_worklog_at"],
        )
        self.subscriptions.upsert(subscription.id, subscription)
        return subscription

    async def notify_updates(self) -> list[IssueSubscription]:
        updated_subscriptions: list[IssueSubscription] = []
        for subscription in self.subscriptions.list_all():
            issue = await self.youtrack_client.get_issue(subscription.issue_id_readable)
            snapshot = await self._snapshot(subscription.issue_id_readable, issue=issue)
            changes = self._detect_changes(subscription, snapshot)
            if not changes:
                continue

            subject = f"Aggiornamento ticket {subscription.issue_id_readable}: {issue.get('summary') or subscription.summary}"
            body = self._build_update_email(subscription, issue, changes, snapshot)
            self.mailbox.send_message(subscription.requester_email, subject, body)
            refreshed = subscription.model_copy(
                update={
                    "summary": issue.get("summary") or subscription.summary,
                    "state": snapshot["state"],
                    "assignee": snapshot["assignee"],
                    "resolved": snapshot["resolved"],
                    "updated_at": snapshot["updated_at"],
                    "worklog_count": snapshot["worklog_count"],
                    "total_minutes": snapshot["total_minutes"],
                    "last_worklog_at": snapshot["last_worklog_at"],
                    "last_notified_at": datetime.now(timezone.utc),
                }
            )
            self.subscriptions.upsert(refreshed.id, refreshed)
            updated_subscriptions.append(refreshed)
        return updated_subscriptions

    async def _snapshot(self, issue_id_readable: str, *, issue: dict | None = None) -> dict:
        issue = issue or await self.youtrack_client.get_issue(issue_id_readable)
        work_items = await self.youtrack_client.list_issue_work_items(issue_id_readable)
        total_minutes = 0
        last_worklog_at = None
        for item in work_items:
            minutes = ((item.get("duration") or {}).get("minutes")) or 0
            total_minutes += minutes
            work_date = utc_datetime_from_millis(item.get("date"))
            if work_date and (last_worklog_at is None or work_date > last_worklog_at):
                last_worklog_at = work_date
        return {
            "state": issue_state_name(issue),
            "assignee": issue_assignee_name(issue),
            "resolved": bool(issue.get("resolved")),
            "updated_at": utc_datetime_from_millis(issue.get("updated")),
            "worklog_count": len(work_items),
            "total_minutes": total_minutes,
            "last_worklog_at": last_worklog_at,
        }

    def _detect_changes(self, subscription: IssueSubscription, snapshot: dict) -> list[str]:
        changes: list[str] = []
        if snapshot["state"] != subscription.state:
            changes.append(f"stato: {subscription.state or 'n/d'} -> {snapshot['state'] or 'n/d'}")
        if snapshot["assignee"] != subscription.assignee:
            changes.append(f"assegnazione: {subscription.assignee or 'n/d'} -> {snapshot['assignee'] or 'n/d'}")
        if snapshot["resolved"] != subscription.resolved:
            changes.append("ticket chiuso" if snapshot["resolved"] else "ticket riaperto")
        if snapshot["worklog_count"] > subscription.worklog_count:
            delta_minutes = max(snapshot["total_minutes"] - subscription.total_minutes, 0)
            if delta_minutes > 0:
                changes.append(f"tempo registrato: +{round(delta_minutes / 60, 2)} ore")
            else:
                changes.append("nuova lavorazione registrata")
        elif snapshot["updated_at"] and subscription.updated_at and snapshot["updated_at"] > subscription.updated_at:
            changes.append("attivita aggiornata")
        return changes

    def _build_update_email(self, subscription: IssueSubscription, issue: dict, changes: list[str], snapshot: dict) -> str:
        issue_ref = issue.get("idReadable") or subscription.issue_id_readable
        lines = [
            "Ti aggiorno sul ticket che avevi aperto tramite il bot.",
            "",
            f"Ticket: {issue_ref} - {issue.get('summary') or subscription.summary}",
            f"Link: {self.youtrack_client.issue_url(issue_ref) or 'n/d'}",
            "",
            "Aggiornamenti rilevati:",
        ]
        lines.extend(f"- {change}" for change in changes)
        lines.extend(
            [
                "",
                f"Stato attuale: {snapshot['state'] or 'n/d'}",
                f"Assegnato a: {snapshot['assignee'] or 'n/d'}",
                f"Ore registrate totali: {round(snapshot['total_minutes'] / 60, 2)}",
            ]
        )
        return "\n".join(lines)
