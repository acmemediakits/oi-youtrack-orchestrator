from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from app.config import settings
from app.models import (
    ActionKind,
    ActionPreview,
    CommitInput,
    CommitResult,
    IngestRequestInput,
    IssueOperation,
    KnowledgeOperation,
    NormalizedRequest,
    OperationResult,
    PreviewInput,
    ProjectCandidate,
    ProjectMatch,
    RequestStatus,
    WorklogOperation,
)
from app.repositories import CommitRepository, CustomerDirectoryRepository, PreviewRepository, RequestRepository


ISSUE_ID_PATTERN = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")
HOURS_PATTERN = re.compile(r"(\d+(?:[.,]\d+)?)\s*(ora|ore|h|hr|min|mins|minuti)", re.IGNORECASE)


def normalize_text(text: str) -> str:
    return " ".join(text.strip().split())


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
            issue_id_match = ISSUE_ID_PATTERN.search(chunk)
            duration = extract_duration_minutes(chunk)

            if any(keyword in lowered for keyword in ["knowledge", "kb", "salvare", "salva", "script", "comando"]):
                knowledge_ops.append(
                    KnowledgeOperation(
                        project_id=project_match.selected_project_id or settings.personal_kb_project,
                        folder=settings.personal_kb_folder if "person" in lowered or "miei" in lowered else None,
                        title=self._knowledge_title(chunk),
                        content=chunk,
                        tags=["personale"] if "personal" in lowered or "miei" in lowered else [],
                        is_personal="personal" in lowered or "miei" in lowered,
                        needs_confirmation=project_match.status != "matched" and "personal" not in lowered and "miei" not in lowered,
                    )
                )
                continue

            if duration:
                issue_id = issue_id_match.group(1) if issue_id_match else None
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
                    issue_ops.append(
                        IssueOperation(
                            action=action,
                            project_id=project_id,
                            issue_id=issue_id,
                            summary=self._issue_summary(chunk),
                            description=explicit_worklog_comment or chunk,
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
                action = "update" if issue_id_match else "create"
                issue_ops.append(
                    IssueOperation(
                        action=action,
                        project_id=project_match.selected_project_id,
                        issue_id=issue_id_match.group(1) if issue_id_match else None,
                        summary=self._issue_summary(chunk),
                        description=chunk,
                        assignee=self._default_issue_assignee(action),
                        confidence=0.6 if issue_id_match else 0.75,
                        needs_confirmation=project_match.status != "matched" or not issue_id_match,
                    )
                )

        if not issue_ops and not worklog_ops and not knowledge_ops and text:
            issue_ops.append(
                IssueOperation(
                    action="create",
                    project_id=project_match.selected_project_id,
                    summary=text[:120],
                    description=text,
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
        stripped = ISSUE_ID_PATTERN.sub("", chunk).strip()
        return stripped[:120] if stripped else "Attivita' cliente"

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
                        "content": operation.content,
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

    async def _assign_issue(self, response: dict, assignee: str) -> str | None:
        issue_ref = response.get("idReadable") or response.get("id")
        if not issue_ref:
            return f"Assignee '{assignee}' not applied because the created issue has no readable reference."

        payload_variants = [
            {
                "customFields": [
                    {
                        "name": settings.youtrack_assignee_field_name,
                        "$type": "SingleUserIssueCustomField",
                        "value": {"login": settings.youtrack_default_assignee_login or assignee},
                    }
                ]
            },
            {
                "customFields": [
                    {
                        "name": settings.youtrack_assignee_field_name,
                        "$type": "SingleUserIssueCustomField",
                        "value": {"name": assignee},
                    }
                ]
            },
            {
                "customFields": [
                    {
                        "name": settings.youtrack_assignee_field_name,
                        "$type": "SingleUserIssueCustomField",
                        "value": {"fullName": assignee},
                    }
                ]
            },
        ]

        last_error = None
        for variant in payload_variants:
            try:
                await self.youtrack_client.update_issue(issue_ref, variant)
                return None
            except Exception as exc:
                last_error = str(exc)
        return f"Assignee '{assignee}' could not be applied to {issue_ref}: {last_error}"
