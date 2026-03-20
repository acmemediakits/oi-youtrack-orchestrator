from __future__ import annotations

import asyncio
import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date

from app.config import settings
from app.models import CommitInput, IngestRequestInput, MailExecutionPlan, MailProcessingRecord, MailboxMessage, PreviewInput, RequestSource
from app.services import parse_mail_identity, parse_reporting_period, sender_author_hints

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
    query_service: any
    issue_subscription_service: any
    runtime_config: any = None
    user_directory: any = None
    permissions: any = None
    admin_approvals: any = None

    def _runtime(self):
        if self.runtime_config:
            return self.runtime_config.get()
        from app.models import RuntimeConfig, RuntimeMailboxFolders

        return RuntimeConfig(
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

    async def run_once(self) -> list[MailProcessingRecord]:
        results: list[MailProcessingRecord] = []
        logger.info("Starting mail polling cycle.")
        for message in self.mailbox.fetch_unseen():
            existing = self.processed.find_by_message_id(message.message_id)
            if existing:
                logger.info("Skipping already processed email message_id=%s", message.message_id)
                try:
                    self.mailbox.mark_seen(message.mailbox_uid)
                    target_folder = self._runtime().mailbox_folders.processed
                    if existing.status == "rejected_domain":
                        target_folder = self._runtime().mailbox_folders.rejected
                    elif existing.status == "error":
                        target_folder = self._runtime().mailbox_folders.failed
                    self.mailbox.move_message(message.mailbox_uid, target_folder)
                    logger.info(
                        "Finalized duplicate email message_id=%s by moving it to folder=%s",
                        message.message_id,
                        target_folder,
                    )
                except Exception:
                    logger.exception("Failed to finalize duplicate email message_id=%s", message.message_id)
                continue
            requester_name, requester_email = parse_mail_identity(message.sender)
            approval = self.admin_approvals.approve_from_message(requester_email, message.text) if self.admin_approvals else None
            if approval:
                results.append(await self._resume_approved_request(message, approval))
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
                self.mailbox.move_message(message.mailbox_uid, self._runtime().mailbox_folders.rejected)
                results.append(record)
                continue
            try:
                user = self.user_directory.resolve(requester_email) if (requester_email and self.user_directory) else None
                if self.permissions and self.user_directory:
                    self.permissions.ensure_active_user(user)
                logger.info(
                    "Processing email message_id=%s sender=%s subject=%s",
                    message.message_id,
                    message.sender,
                    message.subject,
                )
                planner_reply = await self._plan_with_ytbot(message)
                plan = await self._build_execution_plan(message, planner_reply)
                self._enforce_mail_permissions(message, user, plan)
                if plan.admin_scope:
                    approval_reply = self._create_admin_approval(message, plan, requester_name, requester_email or "")
                    self.mailbox.send_reply(message, approval_reply)
                    self.mailbox.mark_seen(message.mailbox_uid)
                    record = MailProcessingRecord(
                        message_id=message.message_id,
                        mailbox_uid=message.mailbox_uid,
                        sender=message.sender,
                        subject=message.subject,
                        status="processed",
                        response_text=approval_reply,
                        finish_reason="awaiting_admin_approval",
                        tool_calls_detected=planner_reply.tool_calls_detected if planner_reply else False,
                        raw_openwebui_response=planner_reply.raw_response if planner_reply and self._runtime().verbose else {},
                    )
                    self.processed.upsert(record.id, record)
                    self.mailbox.move_message(message.mailbox_uid, self._runtime().mailbox_folders.processing)
                    results.append(record)
                    continue
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
                        raw_openwebui_response=planner_reply.raw_response if planner_reply and self._runtime().verbose else {},
                    )
                    self.processed.upsert(record.id, record)
                    self.mailbox.move_message(message.mailbox_uid, self._runtime().mailbox_folders.processed)
                    results.append(record)
                    continue
                if plan.workflow_mode == "assist":
                    reply = await self._execute_assist_plan(message, plan)
                    self.mailbox.send_reply(message, reply)
                    self.mailbox.mark_seen(message.mailbox_uid)
                    record = MailProcessingRecord(
                        message_id=message.message_id,
                        mailbox_uid=message.mailbox_uid,
                        sender=message.sender,
                        subject=message.subject,
                        status="processed",
                        response_text=reply,
                        finish_reason=plan.assist_intent or "assist",
                        tool_calls_detected=planner_reply.tool_calls_detected if planner_reply else False,
                        raw_openwebui_response=planner_reply.raw_response if planner_reply and self._runtime().verbose else {},
                    )
                    self.processed.upsert(record.id, record)
                    self.mailbox.move_message(message.mailbox_uid, self._runtime().mailbox_folders.processed)
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

                commit = None
                if plan.needs_clarification or preview.requires_confirmation:
                    reply = self._build_clarification_reply(message, preview, plan)
                    finish_reason = "clarification_required"
                    target_folder = self._runtime().mailbox_folders.processing
                else:
                    commit = await self.commit_service.commit(
                        CommitInput(preview_id=preview.preview_id, confirm=True)
                    )
                    reply = self._build_commit_reply(message, preview, commit, plan)
                    finish_reason = commit.status
                    target_folder = self._runtime().mailbox_folders.processed if commit.status != "blocked" else self._runtime().mailbox_folders.failed

                self.mailbox.send_reply(message, reply)
                if commit is not None:
                    await self._register_issue_subscriptions(message, commit)
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
                    raw_openwebui_response=planner_reply.raw_response if planner_reply and self._runtime().verbose else {},
                )
                self.processed.upsert(record.id, record)
                self.mailbox.move_message(message.mailbox_uid, target_folder)
                logger.info("Email processed successfully for message_id=%s", message.message_id)
                results.append(record)
            except PermissionError as exc:
                logger.warning("Mail automation permission denied for message_id=%s: %s", message.message_id, exc)
                denial_reply = str(exc)
                try:
                    self.mailbox.send_reply(message, denial_reply)
                except Exception:
                    logger.exception("Failed to send permission denial reply for message_id=%s", message.message_id)
                record = MailProcessingRecord(
                    message_id=message.message_id,
                    mailbox_uid=message.mailbox_uid,
                    sender=message.sender,
                    subject=message.subject,
                    status="processed",
                    response_text=denial_reply,
                    finish_reason="permission_denied",
                    raw_openwebui_response={},
                )
                self.processed.upsert(record.id, record)
                try:
                    self.mailbox.mark_seen(message.mailbox_uid)
                    self.mailbox.move_message(message.mailbox_uid, self._runtime().mailbox_folders.failed)
                except Exception:
                    logger.exception("Failed to finalize denied message_id=%s", message.message_id)
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
                    self.mailbox.move_message(message.mailbox_uid, self._runtime().mailbox_folders.failed)
                except Exception:
                    logger.exception("Failed to move message_id=%s to FAILED folder", message.message_id)
                results.append(record)
        await self._notify_issue_updates()
        logger.info("Mail polling cycle finished with %s processed record(s).", len(results))
        return results

    def _domain_allowed(self, domain: str | None) -> bool:
        allowed_domains = self._runtime().mailbox_allowed_sender_domains
        if not allowed_domains:
            return False
        if not domain:
            return False
        return domain.lower() in allowed_domains

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
            return fallback.model_copy(
                update={
                    "reply_intent": "clarify",
                    "needs_clarification": True,
                    "clarification_question": (
                        "Ho bisogno di interpretare meglio questa email prima di procedere. "
                        "Puoi dirmi se vuoi che io la inoltri a qualcuno, apra/aggiorni un ticket, oppure ti prepari solo una risposta?"
                    ),
                }
            )
        if planner_reply.tool_calls_detected:
            logger.warning(
                "YTBot planner returned tool calls for message_id=%s. Falling back to deterministic mode.",
                message.message_id,
            )
            return fallback.model_copy(
                update={
                    "reply_intent": "clarify",
                    "needs_clarification": True,
                    "clarification_question": "Non ho ottenuto un piano affidabile dal planner. Mi confermi l'azione da eseguire su questa email?",
                }
            )
        raw_content = (planner_reply.content or "").strip()
        if not raw_content:
            return fallback.model_copy(
                update={
                    "reply_intent": "clarify",
                    "needs_clarification": True,
                    "clarification_question": "Il planner non ha restituito un piano utilizzabile. Mi confermi cosa devo fare con questa email?",
                }
            )
        try:
            payload = self._extract_json_payload(raw_content)
            plan = MailExecutionPlan.model_validate(payload)
        except Exception:
            logger.exception("Failed to parse planner JSON for message_id=%s. Falling back to deterministic mode.", message.message_id)
            return fallback.model_copy(
                update={
                    "reply_intent": "clarify",
                    "needs_clarification": True,
                    "clarification_question": "La risposta del planner non era valida. Mi confermi l'azione desiderata su questa email?",
                }
            )

        plan = self._normalize_execution_plan(message, plan)
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
            '"workflow_mode": "youtrack"|"assist", '
            '"assist_intent": "summarize"|"translate"|"explain"|"extract_actions"|"draft_reply"|"classify_for_youtrack"|"delegate"|"time_report"|null, '
            '"admin_scope": boolean, '
            '"customer_label": string|null, '
            '"project_hint": string|null, '
            '"project_id": string|null, '
            '"issue_summary": string|null, '
            '"issue_description": string|null, '
            '"issue_assignee": string|null, '
            '"delegate_to_name": string|null, '
            '"delegate_to_email": string|null, '
            '"delegate_subject": string|null, '
            '"delegate_body": string|null, '
            '"report_date_from": "YYYY-MM-DD"|null, '
            '"report_date_to": "YYYY-MM-DD"|null, '
            '"report_group_by": "project"|"issue"|"author"|null, '
            '"report_author_hint": string|null, '
            '"needs_clarification": boolean, '
            '"clarification_question": string|null, '
            '"reply_intent": "execute"|"clarify"|"ignore", '
            '"reply_draft": string|null'
            "}\n"
            "Use workflow_mode='assist' when the email only asks for explanation, summary, translation, action extraction, or draft reply support.\n"
            "Use assist_intent='delegate' when the sender asks you to remind, contact, notify, hand off, forward, or write to another person on their behalf. Do not create a YouTrack issue in that case.\n"
            "Use assist_intent='time_report' when the sender asks for hours worked, timesheets, or a monthly/project summary of tracked time.\n"
            "Use workflow_mode='youtrack' only when the sender explicitly asks to create/update/log/search something in YouTrack or when ticketing is clearly requested.\n"
            "Set admin_scope=true for privileged operations such as advanced reporting, knowledge-base write/read requests with reserved content, archive/delete/project-level administration, or any operation that should require super-admin confirmation when requested by email.\n"
            "request_text must contain the operational request as a standalone text ready for backend processing.\n"
            "If you classify as delegate, you must extract the target person into delegate_to_name or delegate_to_email and prepare delegate_body as the actual outgoing email body for that person.\n"
            "If the sender is asking you to write to a third person, do not set only reply_draft for the original sender: set assist_intent='delegate'.\n"
            "If the request is a reporting request, set assist_intent='time_report' even if the sender uses words like 'riassunto' or 'summary'.\n"
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

    def _build_assist_reply(self, message: MailboxMessage, plan: MailExecutionPlan) -> str:
        if plan.reply_draft:
            return plan.reply_draft
        return (
            "Ho letto la mail e l'ho trattata come richiesta di assistenza, senza creare ticket YouTrack.\n\n"
            f"Intent rilevato: {plan.assist_intent or 'assist'}.\n"
            "Se vuoi, puoi rispondere a questa email chiedendomi esplicitamente di aprire o aggiornare un ticket."
        )

    async def _execute_assist_plan(self, message: MailboxMessage, plan: MailExecutionPlan) -> str:
        if plan.assist_intent == "delegate":
            return self._execute_delegate_request(message, plan)
        if plan.assist_intent == "time_report":
            return await self._execute_time_report_request(message, plan)
        self._guard_non_delegate_reply(message, plan)
        return plan.reply_draft or self._build_assist_reply(message, plan)

    def _execute_delegate_request(self, message: MailboxMessage, plan: MailExecutionPlan) -> str:
        recipient_email = (plan.delegate_to_email or self._delegate_email_from_name(plan.delegate_to_name)).strip() if (plan.delegate_to_email or plan.delegate_to_name) else ""
        if not recipient_email:
            return "Ho capito che vuoi inoltrare la lavorazione a un collega, ma mi manca il destinatario."

        recipient_name = plan.delegate_to_name or recipient_email.split("@", 1)[0]
        sender_name, sender_email = parse_mail_identity(message.sender)
        subject = plan.delegate_subject or f"Richiesta operativa da {sender_name or sender_email or 'collega'}"
        body = plan.delegate_body or self._default_delegate_body(message, recipient_name, sender_name, sender_email, plan)
        self.mailbox.send_message(recipient_email, subject, body)
        return (
            f"Ho inviato il riepilogo operativo a {recipient_email} senza creare un ticket YouTrack.\n\n"
            "Se vuoi, posso anche preparare una bozza piu' esecutiva o aggiungere contesto tecnico."
        )

    async def _execute_time_report_request(self, message: MailboxMessage, plan: MailExecutionPlan) -> str:
        date_from = plan.report_date_from
        date_to = plan.report_date_to
        if not date_from or not date_to:
            inferred_from, inferred_to = parse_reporting_period(plan.request_text or self._compose_request_text(message), today=date.today())
            date_from = date_from or inferred_from
            date_to = date_to or inferred_to
        if not date_from or not date_to:
            return "Ho capito che vuoi un report ore, ma mi serve il periodo esatto da analizzare."

        author_hints = sender_author_hints(message.sender)
        author_hint = plan.report_author_hint or (author_hints[-1] if author_hints else None)
        summary = await self.query_service.summarize_time_report(date_from, date_to, author_hint=author_hint)
        if not summary.project_breakdown:
            return (
                f"Ho controllato il timesheet dal {date_from.isoformat()} al {date_to.isoformat()}, "
                "ma non ho trovato ore registrate per il periodo richiesto."
            )

        lines = [
            f"Ho preparato il report ore dal {date_from.isoformat()} al {date_to.isoformat()}.",
            "",
            f"Totale ore: {summary.total_hours}",
            "Raggruppamento per progetto:",
        ]
        for item in summary.project_breakdown:
            lines.append(f"- {item.project_name or item.project_id}: {item.hours} ore su {item.issue_count} ticket")
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

    def _normalize_execution_plan(self, message: MailboxMessage, plan: MailExecutionPlan) -> MailExecutionPlan:
        updates: dict = {}

        if plan.assist_intent == "delegate":
            if not plan.delegate_to_email and plan.delegate_to_name:
                updates["delegate_to_email"] = self._delegate_email_from_name(plan.delegate_to_name)
            if not plan.delegate_body:
                sender_name, sender_email = parse_mail_identity(message.sender)
                recipient_name = plan.delegate_to_name or (updates.get("delegate_to_email") or "").split("@", 1)[0]
                if recipient_name:
                    updates["delegate_body"] = self._default_delegate_body(message, recipient_name, sender_name, sender_email, plan)

        if plan.assist_intent == "time_report":
            inferred_from, inferred_to = parse_reporting_period(plan.request_text or self._compose_request_text(message), today=date.today())
            if inferred_from and not plan.report_date_from:
                updates["report_date_from"] = inferred_from
            if inferred_to and not plan.report_date_to:
                updates["report_date_to"] = inferred_to
            if not plan.report_author_hint:
                hints = sender_author_hints(message.sender)
                if hints:
                    updates["report_author_hint"] = hints[-1]
            if not plan.report_group_by:
                updates["report_group_by"] = "project"

        if updates:
            return plan.model_copy(update=updates)
        return plan

    def _enforce_mail_permissions(self, message: MailboxMessage, user, plan: MailExecutionPlan) -> None:
        if not self.permissions or not self.user_directory:
            return
        if plan.admin_scope:
            self.permissions.assert_capability(user, "admin_scope_email")
            return
        if plan.workflow_mode == "assist":
            if plan.assist_intent == "time_report":
                self.permissions.assert_capability(user, "time_reports")
                return
            self.permissions.assert_capability(user, "assist_mail")
            return
        if plan.workflow_mode == "youtrack":
            self.permissions.assert_capability(user, "create_task")

    def _create_admin_approval(self, message: MailboxMessage, plan: MailExecutionPlan, requester_name: str | None, requester_email: str) -> str:
        if not self.admin_approvals:
            raise PermissionError("Approval admin non configurata.")
        self.admin_approvals.create(message, plan, requester_name, requester_email)
        return (
            "La richiesta e' stata classificata come operazione privilegiata.\n\n"
            "Ho inviato una richiesta di approvazione al super-admin. Appena arriva la conferma, riprendero' il flusso."
        )

    async def _resume_approved_request(self, approval_message: MailboxMessage, approval) -> MailProcessingRecord:
        original_message = MailboxMessage.model_validate(approval.message_payload)
        plan = MailExecutionPlan.model_validate(approval.plan_payload)
        planner_reply = None
        ingest = self.request_service.ingest(
            IngestRequestInput(
                source=RequestSource.email,
                text=plan.request_text,
                sender=original_message.sender,
                subject=original_message.subject,
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
        commit = await self.commit_service.commit(CommitInput(preview_id=preview.preview_id, confirm=True))
        reply = self._build_commit_reply(original_message, preview, commit, plan)
        self.mailbox.send_reply(original_message, reply)
        self.mailbox.mark_seen(approval_message.mailbox_uid)
        record = MailProcessingRecord(
            message_id=approval_message.message_id,
            mailbox_uid=approval_message.mailbox_uid,
            sender=approval_message.sender,
            subject=approval_message.subject,
            status="processed",
            response_text=reply,
            finish_reason="approved_and_executed",
            tool_calls_detected=planner_reply.tool_calls_detected if planner_reply else False,
            raw_openwebui_response={},
        )
        self.processed.upsert(record.id, record)
        self.mailbox.move_message(approval_message.mailbox_uid, self._runtime().mailbox_folders.processed)
        await self._register_issue_subscriptions(original_message, commit)
        return record

    def _guard_non_delegate_reply(self, message: MailboxMessage, plan: MailExecutionPlan) -> None:
        if plan.assist_intent == "delegate":
            return
        reply = (plan.reply_draft or "").strip()
        if not reply:
            return
        sender_name, _ = parse_mail_identity(message.sender)
        greeting_match = re.match(r"^(?:ciao|buongiorno|salve)\s+([^\n,!:]+)", reply, re.IGNORECASE)
        if not greeting_match:
            return
        greeted_name = greeting_match.group(1).strip().lower()
        sender_name_normalized = self._normalize_match_value(sender_name)
        greeted_name_normalized = self._normalize_match_value(greeted_name)
        if sender_name_normalized and greeted_name_normalized and sender_name_normalized != greeted_name_normalized:
            raise ValueError(
                "Il planner ha prodotto una bozza indirizzata a una terza persona ma senza classificare la mail come delega."
            )

    def _delegate_email_from_name(self, name: str | None) -> str | None:
        if not name:
            return None
        slug = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
        slug = re.sub(r"[^a-z0-9]+", ".", slug.lower()).strip(".")
        if not slug:
            return None
        return f"{slug}@{settings.mailbox_internal_domain}"

    def _default_delegate_body(
        self,
        message: MailboxMessage,
        recipient_name: str,
        sender_name: str | None,
        sender_email: str | None,
        plan: MailExecutionPlan,
    ) -> str:
        lines = [
            f"Ciao {recipient_name},",
            "",
            f"{sender_name or sender_email or 'Un collega'} chiede che ti occupi tu di questa lavorazione.",
            "",
            "Riepilogo operativo:",
            plan.request_text.strip(),
        ]
        if message.subject:
            lines.extend(["", f"Oggetto email originale: {message.subject}"])
        if sender_email:
            lines.append(f"Mittente originale: {sender_email}")
        lines.extend(["", "Questa email e' stata inoltrata dal bot senza apertura di ticket YouTrack."])
        return "\n".join(lines)

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

    async def _register_issue_subscriptions(self, message: MailboxMessage, commit) -> None:
        requester_name, requester_email = parse_mail_identity(message.sender)
        if not requester_email or not self.issue_subscription_service:
            return
        for result in commit.issue_results:
            if result.status != "success":
                continue
            issue_id_readable = result.remote_id or result.payload.get("idReadable") or result.payload.get("id")
            if not issue_id_readable:
                continue
            try:
                await self.issue_subscription_service.subscribe(
                    issue_id_readable,
                    requester_email,
                    requester_name=requester_name,
                    source_subject=message.subject,
                )
            except Exception:
                logger.exception("Failed to register issue subscription for issue=%s", issue_id_readable)

    async def _notify_issue_updates(self) -> None:
        if not self.issue_subscription_service:
            return
        try:
            await self.issue_subscription_service.notify_updates()
        except Exception:
            logger.exception("Failed to notify issue subscription updates.")

    def _build_failure_reply(self, exc: Exception) -> str:
        return (
            "I could not complete your request because of a technical problem in the automation layer.\n\n"
            f"Error: {exc}\n\n"
            "The message has been placed in the FAILED queue for review."
        )


@dataclass(slots=True)
class MailAutomationRunner:
    service: MailAutomationService
    runtime_config: any
    _task: asyncio.Task | None = field(default=None, init=False)
    _stopping: asyncio.Event | None = field(default=None, init=False)

    def start(self) -> None:
        if not settings.mailbox_poll_enabled or self._task is not None:
            if not settings.mailbox_poll_enabled:
                logger.info("Mail polling runner not started because MAILBOX_POLL_ENABLED is false.")
            return
        self._stopping = asyncio.Event()
        self._task = asyncio.create_task(self._loop())
        logger.info("Mail polling runner started with interval=%ss", self.runtime_config.get().mailbox_poll_interval_seconds)

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
                    timeout=max(self.runtime_config.get().mailbox_poll_interval_seconds, 10),
                )
            except asyncio.TimeoutError:
                continue
