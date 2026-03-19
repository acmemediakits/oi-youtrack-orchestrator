from __future__ import annotations

import asyncio
import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field

from app.config import settings
from app.models import CommitInput, IngestRequestInput, MailExecutionPlan, MailProcessingRecord, MailboxMessage, PreviewInput, RequestSource

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class MailAutomationService:
    mailbox: any
    openwebui: any
    processed: any
    request_service: any
    preview_service: any
    commit_service: any
    youtrack_client: any

    async def run_once(self) -> list[MailProcessingRecord]:
        results: list[MailProcessingRecord] = []
        logger.info("Starting mail polling cycle.")
        for message in self.mailbox.fetch_unseen():
            existing = self.processed.find_by_message_id(message.message_id)
            if existing:
                logger.info("Skipping already processed email message_id=%s", message.message_id)
                continue
            domain = self.mailbox.sender_domain(message.sender)
            if not self._domain_allowed(domain):
                logger.warning(
                    "Rejected email from sender=%s domain=%s message_id=%s because domain is not allowed.",
                    message.sender,
                    domain,
                    message.message_id,
                )
                record = MailProcessingRecord(
                    message_id=message.message_id,
                    mailbox_uid=message.mailbox_uid,
                    sender=message.sender,
                    subject=message.subject,
                    status="rejected_domain",
                    error="Sender domain is not allowed to use the bot.",
                )
                self.processed.upsert(record.id, record)
                self.mailbox.move_message(message.mailbox_uid, settings.mailbox_rejected_folder)
                results.append(record)
                continue
            try:
                logger.info(
                    "Processing email message_id=%s sender=%s subject=%s",
                    message.message_id,
                    message.sender,
                    message.subject,
                )
                planner_reply = await self._plan_with_ytbot(message)
                plan = await self._build_execution_plan(message, planner_reply)
                if plan.reply_intent == "ignore":
                    logger.info("Planner marked email message_id=%s as ignorable.", message.message_id)
                    self.mailbox.mark_seen(message.mailbox_uid)
                    record = MailProcessingRecord(
                        message_id=message.message_id,
                        mailbox_uid=message.mailbox_uid,
                        sender=message.sender,
                        subject=message.subject,
                        status="processed",
                        response_text=plan.reply_draft or "No operational action required.",
                        finish_reason="ignored",
                        tool_calls_detected=planner_reply.tool_calls_detected if planner_reply else False,
                        raw_openwebui_response=planner_reply.raw_response if planner_reply and settings.verbose else {},
                    )
                    self.processed.upsert(record.id, record)
                    self.mailbox.move_message(message.mailbox_uid, settings.mailbox_processed_folder)
                    results.append(record)
                    continue

                ingest = self.request_service.ingest(
                    IngestRequestInput(
                        source=RequestSource.email,
                        text=plan.request_text,
                        sender=message.sender,
                        subject=message.subject,
                        customer_label=plan.customer_label,
                        project_id=plan.project_id,
                    )
                )
                preview = self.preview_service.build_preview(
                    PreviewInput(
                        request_id=ingest.id,
                        customer_label=plan.customer_label,
                        project_id=plan.project_id,
                    )
                )
                self._apply_plan_to_preview(preview, plan)

                if plan.needs_clarification or preview.requires_confirmation:
                    reply = self._build_clarification_reply(message, preview, plan)
                    finish_reason = "clarification_required"
                    target_folder = settings.mailbox_processing_folder
                else:
                    commit = await self.commit_service.commit(
                        CommitInput(preview_id=preview.preview_id, confirm=True)
                    )
                    reply = self._build_commit_reply(message, preview, commit, plan)
                    finish_reason = commit.status
                    target_folder = settings.mailbox_processed_folder if commit.status != "blocked" else settings.mailbox_failed_folder

                self.mailbox.send_reply(message, reply)
                self.mailbox.mark_seen(message.mailbox_uid)
                record = MailProcessingRecord(
                    message_id=message.message_id,
                    mailbox_uid=message.mailbox_uid,
                    sender=message.sender,
                    subject=message.subject,
                    status="processed",
                    response_text=reply,
                    finish_reason=finish_reason,
                    tool_calls_detected=planner_reply.tool_calls_detected if planner_reply else False,
                    raw_openwebui_response=planner_reply.raw_response if planner_reply and settings.verbose else {},
                )
                self.processed.upsert(record.id, record)
                self.mailbox.move_message(message.mailbox_uid, target_folder)
                logger.info("Email processed successfully for message_id=%s", message.message_id)
                results.append(record)
            except Exception as exc:
                logger.exception("Mail automation failed for message_id=%s: %s", message.message_id, exc)
                technical_reply = self._build_failure_reply(exc)
                try:
                    self.mailbox.send_reply(message, technical_reply)
                except Exception:
                    logger.exception("Failed to send technical failure reply for message_id=%s", message.message_id)
                record = MailProcessingRecord(
                    message_id=message.message_id,
                    mailbox_uid=message.mailbox_uid,
                    sender=message.sender,
                    subject=message.subject,
                    status="error",
                    error=str(exc),
                    raw_openwebui_response={},
                )
                self.processed.upsert(record.id, record)
                try:
                    self.mailbox.move_message(message.mailbox_uid, settings.mailbox_failed_folder)
                except Exception:
                    logger.exception("Failed to move message_id=%s to FAILED folder", message.message_id)
                results.append(record)
        logger.info("Mail polling cycle finished with %s processed record(s).", len(results))
        return results

    def _domain_allowed(self, domain: str | None) -> bool:
        if not settings.mailbox_allowed_sender_domains:
            return False
        if not domain:
            return False
        return domain.lower() in settings.mailbox_allowed_sender_domains

    def _compose_request_text(self, message: MailboxMessage) -> str:
        subject = (message.subject or "").strip()
        body = (message.text or "").strip()
        if subject and body:
            return f"{subject}\n\n{body}"
        return body or subject

    async def _plan_with_ytbot(self, message: MailboxMessage):
        if not self.openwebui:
            return None
        try:
            reply = await self.openwebui.generate_structured_reply(
                system_prompt=self._planner_system_prompt(),
                user_prompt=self._planner_user_prompt(message),
            )
            return reply
        except Exception:
            logger.exception("YTBot planner failed for message_id=%s, falling back to deterministic mode.", message.message_id)
            return None

    async def _build_execution_plan(self, message: MailboxMessage, planner_reply) -> MailExecutionPlan:
        fallback = MailExecutionPlan(request_text=self._compose_request_text(message))
        if not planner_reply:
            return fallback
        if planner_reply.tool_calls_detected:
            logger.warning(
                "YTBot planner returned tool calls for message_id=%s. Falling back to deterministic mode.",
                message.message_id,
            )
            return fallback
        raw_content = (planner_reply.content or "").strip()
        if not raw_content:
            return fallback
        try:
            payload = self._extract_json_payload(raw_content)
            plan = MailExecutionPlan.model_validate(payload)
        except Exception:
            logger.exception("Failed to parse planner JSON for message_id=%s. Falling back to deterministic mode.", message.message_id)
            return fallback

        resolved_project_id = plan.project_id or await self._resolve_project_id(plan.project_hint or plan.customer_label)
        normalized_request = plan.request_text.strip() or fallback.request_text
        return plan.model_copy(update={"request_text": normalized_request, "project_id": resolved_project_id})

    def _extract_json_payload(self, raw_content: str) -> dict:
        stripped = raw_content.strip()
        if stripped.startswith("```"):
            stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
            stripped = re.sub(r"\s*```$", "", stripped)
        return json.loads(stripped)

    async def _resolve_project_id(self, project_hint: str | None) -> str | None:
        if not project_hint:
            return None
        hint = self._normalize_match_value(project_hint)
        try:
            projects = await self.youtrack_client.list_projects()
        except Exception:
            logger.exception("Failed to list projects while resolving project hint '%s'.", project_hint)
            return None

        exact_match = None
        partial_match = None
        for project in projects:
            candidates = [
                project.get("id"),
                project.get("shortName"),
                project.get("name"),
            ]
            normalized = [self._normalize_match_value(value) for value in candidates if value]
            if hint in normalized:
                exact_match = project.get("id")
                break
            if any(hint in value or value in hint for value in normalized):
                partial_match = partial_match or project.get("id")
        return exact_match or partial_match

    def _normalize_match_value(self, value: str | None) -> str:
        normalized = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
        return " ".join(normalized.lower().split())

    def _planner_system_prompt(self) -> str:
        return (
            "You are YTBot acting as a planner for an IMAP automation caller.\n"
            "You understand the whole email thread and must prepare a safe execution plan.\n"
            "Do not call tools. Do not mention tools. Do not ask the caller to execute tool calls.\n"
            "Return only valid JSON with these keys:\n"
            "{"
            '"request_text": string, '
            '"customer_label": string|null, '
            '"project_hint": string|null, '
            '"project_id": string|null, '
            '"issue_summary": string|null, '
            '"issue_description": string|null, '
            '"issue_assignee": string|null, '
            '"needs_clarification": boolean, '
            '"clarification_question": string|null, '
            '"reply_intent": "execute"|"clarify"|"ignore", '
            '"reply_draft": string|null'
            "}\n"
            "request_text must contain the operational request as a standalone text ready for backend processing.\n"
            "If the current email is only a clarification reply, merge it with the visible thread context into request_text.\n"
            "Set project_hint when the user mentions a project by name but you are not certain about the exact YouTrack ID.\n"
            "When the email asks to create a new issue, provide a concise issue_summary in Italian and a clean issue_description.\n"
            "issue_summary must be short, action-oriented, and must not start with generic prefixes like 'Create new issue' or 'Crea una issue'.\n"
            "issue_description should preserve the actual requested work as plain business requirements without mail-forward boilerplate.\n"
            f"Use issue_assignee='{settings.youtrack_default_assignee}' for new issues unless the email clearly asks for someone else.\n"
            "Never invent issue IDs, project IDs, or completed actions.\n"
        )

    def _planner_user_prompt(self, message: MailboxMessage) -> str:
        return (
            f"From: {message.sender}\n"
            f"Subject: {message.subject or '(no subject)'}\n\n"
            "Email body, including any quoted thread text if present:\n"
            f"{message.text.strip()}\n"
        )

    def _build_clarification_reply(self, message: MailboxMessage, preview, plan: MailExecutionPlan) -> str:
        if plan.clarification_question:
            return plan.clarification_question
        lines = [
            "Ho letto la tua richiesta ma prima di procedere mi serve un chiarimento.",
            "",
        ]
        for question in preview.open_questions or ["Mi puoi indicare il progetto o la issue corretta?"]:
            lines.append(f"- {question}")
        if message.subject:
            lines.extend(
                [
                    "",
                    f"Oggetto ricevuto: {message.subject}",
                ]
            )
        lines.extend(
            [
                "",
                "Appena mi rispondi completo l'operazione.",
            ]
        )
        return "\n".join(lines)

    def _apply_plan_to_preview(self, preview, plan: MailExecutionPlan) -> None:
        changed = False
        for operation in preview.issue_operations:
            if operation.action != "create":
                continue
            if plan.issue_summary:
                operation.summary = plan.issue_summary.strip()
                changed = True
            if plan.issue_description:
                operation.description = plan.issue_description.strip()
                changed = True
            if plan.issue_assignee:
                operation.assignee = plan.issue_assignee.strip()
                changed = True
        if changed:
            self.preview_service.previews.upsert(preview.preview_id, preview)

    def _build_commit_reply(self, message: MailboxMessage, preview, commit, plan: MailExecutionPlan) -> str:
        lines = ["Ho elaborato la tua richiesta."]

        if commit.status in {"success", "partial_success"}:
            success_lines = self._successful_operation_lines(commit)
            if success_lines:
                lines.extend(["", *success_lines])
            if commit.errors:
                lines.extend(["", "Ho riscontrato anche questi problemi:"])
                lines.extend(f"- {error}" for error in commit.errors)
        elif commit.status == "duplicate":
            lines.extend(["", "La richiesta risulta gia' elaborata in precedenza."])
        else:
            lines.extend(["", "Non sono riuscito a completare l'operazione in modo sicuro."])
            for question in preview.open_questions:
                lines.append(f"- {question}")
            for error in commit.errors:
                lines.append(f"- {error}")

        lines.extend(["", "Se vuoi, puoi rispondere a questa email con ulteriori dettagli."])
        return "\n".join(lines)

    def _successful_operation_lines(self, commit) -> list[str]:
        lines: list[str] = []
        for result in commit.issue_results:
            if result.status != "success":
                continue
            label = result.payload.get("summary") or result.remote_id or "issue"
            url = result.payload.get("url")
            line = f"- Issue aggiornata: {label}"
            if url:
                line += f" ({url})"
            if result.payload.get("assignee"):
                line += f" [assegnata a {result.payload['assignee']}]"
            lines.append(line)

        for result in commit.worklog_results:
            if result.status != "success":
                continue
            minutes = (((result.payload or {}).get("duration") or {}).get("minutes"))
            issue_id = result.payload.get("issue_id") or "issue di servizio"
            url = result.payload.get("issue_url")
            duration_label = f"{minutes} minuti" if minutes else "tempo registrato"
            line = f"- Worklog registrato su {issue_id}: {duration_label}"
            if url:
                line += f" ({url})"
            lines.append(line)

        for result in commit.knowledge_results:
            if result.status != "success":
                continue
            label = result.payload.get("summary") or result.remote_id or "articolo KB"
            url = result.payload.get("url")
            line = f"- Nota salvata: {label}"
            if url:
                line += f" ({url})"
            lines.append(line)

        return lines

    def _build_failure_reply(self, exc: Exception) -> str:
        return (
            "I could not complete your request because of a technical problem in the automation layer.\n\n"
            f"Error: {exc}\n\n"
            "The message has been placed in the FAILED queue for review."
        )


@dataclass(slots=True)
class MailAutomationRunner:
    service: MailAutomationService
    _task: asyncio.Task | None = field(default=None, init=False)
    _stopping: asyncio.Event | None = field(default=None, init=False)

    def start(self) -> None:
        if not settings.mailbox_poll_enabled or self._task is not None:
            if not settings.mailbox_poll_enabled:
                logger.info("Mail polling runner not started because MAILBOX_POLL_ENABLED is false.")
            return
        self._stopping = asyncio.Event()
        self._task = asyncio.create_task(self._loop())
        logger.info("Mail polling runner started with interval=%ss", settings.mailbox_poll_interval_seconds)

    async def stop(self) -> None:
        if not self._task or not self._stopping:
            return
        self._stopping.set()
        await self._task
        self._task = None
        self._stopping = None
        logger.info("Mail polling runner stopped.")

    async def _loop(self) -> None:
        assert self._stopping is not None
        while not self._stopping.is_set():
            try:
                await self.service.run_once()
            except Exception:
                logger.exception("Unexpected error in mail polling runner loop.")
            try:
                await asyncio.wait_for(
                    self._stopping.wait(),
                    timeout=max(settings.mailbox_poll_interval_seconds, 10),
                )
            except asyncio.TimeoutError:
                continue
