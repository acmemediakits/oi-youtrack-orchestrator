from __future__ import annotations

import json
import re
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app.config import settings
from app.models import CommitInput, IngestRequestInput, MailExecutionPlan, MailProcessingRecord, MailboxMessage, OpenWebUIReply, PreviewInput, RequestSource, RuntimeMailboxFolders, UserType
from app.mail_agent import MailAutomationService
from app.repositories import AdminApprovalRepository, CommitRepository, CustomerDirectoryRepository, IssueSubscriptionRepository, MailProcessingRepository, PreviewRepository, RequestRepository, RuntimeConfigRepository, UserDirectoryRepository
from app.services import AdminApprovalService, CommitService, IssueSubscriptionService, PermissionService, PreviewService, ProjectMatcher, QueryService, RequestService, RuntimeConfigService, UserDirectoryService


class FakeYouTrackClient:
    def __init__(self) -> None:
        self.issue_counter = 0
        self.worklog_counter = 0
        self.article_counter = 0
        self.created_issue_payloads = []
        self.updated_issue_payloads = []
        self.updated_issue_custom_field_payloads = []
        self.created_work_item_payloads = []
        self.issue_details = {
            "SEA-1": {
                "id": "issue_1",
                "idReadable": "SEA-1",
                "summary": "Example issue",
                "resolved": False,
                "updated": 1741824000000,
                "customFields": [
                    {"id": "field-assignee-sea", "name": "ZD_SEA Team", "$type": "SingleUserIssueCustomField", "value": {"login": "acmemediakits", "fullName": "developers"}},
                    {"id": "field-state-sea", "name": "State", "$type": "StateIssueCustomField", "value": {"name": "Open", "isResolved": False}},
                ],
            }
        }
        self.issue_work_items = {
            "SEA-1": [
                {
                    "id": "155-1204",
                    "text": "call cliente",
                    "issue_id": "SEA-1",
                    "date": 1741132800000,
                    "duration": {"minutes": 120},
                    "author": {"fullName": "Mirko Bianco", "login": "mirko"},
                },
                {
                    "id": "155-1205",
                    "text": "follow-up",
                    "issue_id": "SEA-1",
                    "date": 1741305600000,
                    "duration": {"minutes": 60},
                    "author": {"fullName": "Mirko Bianco", "login": "mirko"},
                },
            ]
        }

    async def create_issue(self, payload):
        self.issue_counter += 1
        self.created_issue_payloads.append(payload)
        issue_id_readable = f"SEA-{self.issue_counter}"
        response = {"id": f"issue_{self.issue_counter}", "idReadable": issue_id_readable, **payload}
        self.issue_details[issue_id_readable] = {
            "id": response["id"],
            "idReadable": issue_id_readable,
            "summary": payload.get("summary"),
            "resolved": False,
            "updated": 1741824000000,
            "customFields": [
                {"id": "field-assignee-sea", "name": "ZD_SEA Team", "$type": "SingleUserIssueCustomField", "value": None},
                {"id": "field-state-sea", "name": "State", "$type": "StateIssueCustomField", "value": {"name": "Open", "isResolved": False}},
            ],
        }
        self.issue_work_items.setdefault(issue_id_readable, [])
        return response

    async def update_issue(self, issue_id, payload):
        self.updated_issue_payloads.append((issue_id, payload))
        details = self.issue_details.setdefault(
            issue_id,
            {"id": issue_id, "idReadable": issue_id, "summary": payload.get("summary") or issue_id, "resolved": False, "updated": 1741824000000, "customFields": []},
        )
        if "summary" in payload:
            details["summary"] = payload["summary"]
        if "customFields" in payload:
            details["customFields"] = payload["customFields"]
        return {"id": issue_id, "idReadable": issue_id, **payload}

    async def add_work_item(self, issue_id, payload):
        self.worklog_counter += 1
        self.created_work_item_payloads.append((issue_id, payload))
        self.issue_work_items.setdefault(issue_id, []).append(
            {
                "id": f"worklog_{self.worklog_counter}",
                "text": payload.get("text"),
                "issue_id": issue_id,
                "date": payload.get("date"),
                "duration": payload.get("duration"),
                "author": {"login": "mirko", "fullName": "Mirko Bianco"},
            }
        )
        return {"id": f"worklog_{self.worklog_counter}", "issue_id": issue_id, **payload}

    async def create_article(self, payload):
        self.article_counter += 1
        return {"id": f"article_{self.article_counter}", "idReadable": f"ART-{self.article_counter}", **payload}

    async def get_issue(self, issue_id):
        return self.issue_details.get(
            issue_id,
            {
                "id": issue_id,
                "idReadable": issue_id,
                "summary": "Example issue",
                "resolved": False,
                "updated": 1741824000000,
                "customFields": [
                    {"id": "field-assignee-sea", "name": "ZD_SEA Team", "$type": "SingleUserIssueCustomField", "value": None},
                    {"id": "field-state-sea", "name": "State", "$type": "StateIssueCustomField", "value": {"name": "Open", "isResolved": False}},
                ],
            },
        )

    async def list_issue_custom_fields(self, issue_id):
        details = await self.get_issue(issue_id)
        return details.get("customFields", [])

    async def update_issue_custom_field(self, issue_id, field_id, payload):
        self.updated_issue_custom_field_payloads.append((issue_id, field_id, payload))
        details = self.issue_details.setdefault(
            issue_id,
            {"id": issue_id, "idReadable": issue_id, "summary": issue_id, "resolved": False, "updated": 1741824000000, "customFields": []},
        )
        for field in details["customFields"]:
            if field.get("id") == field_id:
                field["value"] = payload.get("value")
                return {"id": field_id, "name": field.get("name"), "$type": field.get("$type"), "value": field.get("value")}
        raise RuntimeError(f"Unknown field {field_id}")

    async def list_issue_work_items(self, issue_id):
        return self.issue_work_items.get(
            issue_id,
            [{"id": "155-1204", "text": "old text", "issue_id": issue_id, "date": 1741305600000, "duration": {"minutes": 30}, "author": {"login": "other"}}],
        )

    async def update_work_item(self, issue_id, item_id, payload):
        return {"id": item_id, **payload}

    async def list_projects(self):
        return [
            {"id": "SEA", "shortName": "SEA", "name": "SEA", "archived": True},
            {"id": "ZSEA", "shortName": "ZSEA", "name": "SEA Supporto", "archived": False},
            {"id": "FUN", "shortName": "FJ", "name": "FJ Supporto", "archived": False},
            {"id": "0-7", "shortName": "ES", "name": "Stefano Leo"},
        ]

    async def search_issues(self, query, limit=20):
        issues = [
            {
                "id": "issue_1",
                "idReadable": "SEA-1",
                "summary": "Call cliente SEA marzo",
                "resolved": False,
                "updated": 1741824000000,
                "project": {"id": "SEA", "shortName": "SEA", "name": "SEA", "archived": True},
                "customFields": [
                    {"name": "State", "value": {"name": "Open", "isResolved": False}},
                    {"name": "Assignee", "value": {"login": "acmemediakits", "fullName": "developers"}},
                ],
            },
            {
                "id": "issue_2",
                "idReadable": "ZSEA-14",
                "summary": "[calls] Sprint5 call interna",
                "resolved": False,
                "updated": 1741900000000,
                "project": {"id": "ZSEA", "shortName": "ZSEA", "name": "SEA Supporto", "archived": False},
                "customFields": [
                    {"name": "State", "value": {"name": "Running", "isResolved": False}},
                    {"name": "Assignee", "value": {"login": "acmemediakits", "fullName": "developers"}},
                ],
            },
            {
                "id": "issue_3",
                "idReadable": "FJ-11",
                "summary": "Supporto funky catalogo",
                "resolved": False,
                "updated": 1741903600000,
                "project": {"id": "FUN", "shortName": "FJ", "name": "FJ Supporto", "archived": False},
                "customFields": [
                    {"name": "State", "value": {"name": "Open", "isResolved": False}},
                ],
            },
            {
                "id": "issue_4",
                "idReadable": "FJ-12",
                "summary": "Bug funky checkout risolto",
                "resolved": True,
                "updated": 1741000000000,
                "project": {"id": "FUN", "shortName": "FJ", "name": "FJ Supporto", "archived": False},
                "customFields": [
                    {"name": "State", "value": {"name": "Solved", "isResolved": True}},
                ],
            },
        ]
        lowered = query.lower()
        project_filter = None
        if "project:" in lowered:
            project_filter = lowered.split("project:", 1)[1].strip().split()[0]
        filtered = []
        for issue in issues:
            if project_filter:
                project_tokens = {
                    issue["project"]["id"].lower(),
                    issue["project"]["shortName"].lower(),
                    issue["project"]["name"].lower(),
                }
                if project_filter not in project_tokens:
                    continue
            haystack = " ".join(
                [
                    issue["idReadable"],
                    issue["summary"],
                    issue["project"]["id"],
                    issue["project"]["shortName"],
                    issue["project"]["name"],
                ]
            ).lower()
            non_control_tokens = [token for token in lowered.replace(":", " ").split() if token not in {"project", project_filter or ""}]
            if all(token in haystack or token in {"#unresolved"} for token in non_control_tokens):
                filtered.append(issue)
            elif any(token in haystack for token in lowered.split()):
                filtered.append(issue)
        return filtered[:limit]

    async def search_articles(self, query, limit=20):
        articles = [
            {
                "id": "article_1",
                "idReadable": "ART-1",
                "summary": "Procedura SEA deploy",
                "updated": 1741903600000,
                "project": {"id": "ZSEA", "name": "SEA Supporto", "shortName": "ZSEA"},
            },
            {
                "id": "article_2",
                "idReadable": "ART-2",
                "summary": "FAQ Funky catalogo",
                "updated": 1741900000000,
                "project": {"id": "FUN", "name": "FJ Supporto", "shortName": "FJ"},
            },
        ]
        if not query:
            return articles[:limit]
        return [item for item in articles if query.lower() in item["summary"].lower()][:limit]

    def issue_url(self, issue_id_readable):
        if not issue_id_readable:
            return None
        return f"https://youtrack.example.test/issue/{issue_id_readable}"


class FakeMailboxService:
    def __init__(self, messages):
        self.messages = messages
        self.seen = []
        self.replies = []
        self.moves = []
        self.sent_messages = []

    def fetch_unseen(self, limit: int = 20):
        return self.messages[:limit]

    def sender_domain(self, sender: str):
        return sender.rsplit("@", 1)[1].lower() if "@" in sender else None

    def send_reply(self, original, body: str):
        self.replies.append((original.message_id, body))

    def send_message(self, recipient: str, subject: str, body: str):
        self.sent_messages.append((recipient, subject, body))

    def mark_seen(self, mailbox_uid: str):
        self.seen.append(mailbox_uid)

    def move_message(self, mailbox_uid: str, target_folder: str):
        self.moves.append((mailbox_uid, target_folder))


class FakeOpenWebUIClient:
    def __init__(self, payload: dict | None = None, *, tool_calls_detected: bool = False, content: str | None = None):
        self.payload = payload
        self.tool_calls_detected = tool_calls_detected
        self.content = content

    async def generate_structured_reply(self, *, system_prompt: str, user_prompt: str):
        if self.content is not None:
            body = self.content
        else:
            body = json.dumps(self.payload or {})
        return OpenWebUIReply(
            content=body,
            finish_reason="stop",
            tool_calls_detected=self.tool_calls_detected,
            raw_response={"messages": [system_prompt, user_prompt]},
        )


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        settings.data_dir = Path(self.tempdir.name)
        self.requests = RequestRepository()
        self.previews = PreviewRepository()
        self.commits = CommitRepository()
        self.directory = CustomerDirectoryRepository()
        self.runtime_configs = RuntimeConfigRepository()
        self.users = UserDirectoryRepository()
        self.approvals = AdminApprovalRepository()
        self.matcher = ProjectMatcher(self.directory)
        self.request_service = RequestService(self.requests, self.matcher)
        self.preview_service = PreviewService(self.requests, self.previews, self.matcher)
        self.youtrack_client = FakeYouTrackClient()
        self.query_service = QueryService(self.directory, self.youtrack_client)
        self.commit_service = CommitService(self.previews, self.commits, self.requests, self.youtrack_client)
        self.mail_processing = MailProcessingRepository()
        self.issue_subscriptions = IssueSubscriptionRepository()
        self.issue_subscription_service = IssueSubscriptionService(self.issue_subscriptions, self.youtrack_client, FakeMailboxService([]))
        self.runtime_config_service = RuntimeConfigService(self.runtime_configs)
        self.user_directory_service = UserDirectoryService(self.users)
        self.permission_service = PermissionService(self.issue_subscriptions)
        self.admin_approval_service = AdminApprovalService(self.approvals, FakeMailboxService([]))

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_ingest_matches_customer_domain(self):
        request = self.request_service.ingest(
            IngestRequestInput(
                source=RequestSource.email,
                text="Bug urgente per SEA sulla dashboard",
                sender="ops@sea.example.com",
                subject="Bug dashboard",
            )
        )
        self.assertEqual(request.project_match.status, "matched")
        self.assertEqual(request.project_match.selected_project_id, "SEA")

    def test_ingest_accepts_explicit_project_override(self):
        request = self.request_service.ingest(
            IngestRequestInput(
                source=RequestSource.manual,
                text="supporto e debug",
                customer_label="Ellesanti",
                project_id="0-7",
            )
        )
        self.assertEqual(request.project_match.status, "matched")
        self.assertEqual(request.project_match.selected_project_id, "0-7")
        self.assertEqual(request.customer_label, "Ellesanti")

    def test_preview_flags_ambiguous_worklog_without_issue(self):
        preview = self.preview_service.build_preview(
            PreviewInput(text="Ho fatto 2 ore di analisi ma non ricordo il progetto")
        )
        self.assertTrue(preview.requires_confirmation)
        self.assertGreaterEqual(len(preview.open_questions), 1)

    def test_preview_can_build_issue_from_short_title_with_explicit_project(self):
        preview = self.preview_service.build_preview(
            PreviewInput(text="supporto e debug", customer_label="Ellesanti", project_id="0-7")
        )
        self.assertEqual(preview.project_match.selected_project_id, "0-7")
        self.assertEqual(len(preview.issue_operations), 1)
        self.assertEqual(preview.issue_operations[0].summary, "supporto e debug")
        self.assertFalse(preview.requires_confirmation)

    def test_runtime_config_service_persists_editable_settings(self):
        config = self.runtime_config_service.update(
            verbose=True,
            mailbox_poll_interval_seconds=120,
            mailbox_allowed_sender_domains=["trusted.example", "acmemk.com"],
            mailbox_folders=RuntimeMailboxFolders(
                inbox="INBOX",
                processing="PROC",
                processed="DONE",
                failed="FAIL",
                rejected="REJ",
            ),
        )
        self.assertTrue(config.verbose)
        self.assertEqual(config.mailbox_poll_interval_seconds, 120)
        self.assertEqual(config.mailbox_folders.processed, "DONE")

    def test_user_directory_resolves_by_email(self):
        user = self.user_directory_service.upsert_user(
            full_name="Daiana Test",
            email="daiana@example.com",
            youtrack_assignee_email="daiana@acmemk.com",
            user_type=UserType.team,
            active=True,
        )
        resolved = self.user_directory_service.resolve("daiana@example.com")
        self.assertIsNotNone(resolved)
        assert resolved is not None
        self.assertEqual(resolved.id, user.id)
        self.assertEqual(resolved.user_type, UserType.team)

    def test_permission_service_allows_visitor_recent_issue_only(self):
        created = datetime.now(timezone.utc) - timedelta(minutes=10)
        self.issue_subscriptions.upsert(
            "sub_recent",
            self.issue_subscriptions.model_cls(
                id="sub_recent",
                issue_id="issue_1",
                issue_id_readable="SEA-1",
                summary="Example",
                requester_email="visitor@example.com",
                created_at=created,
            ),
        )
        visitor = self.user_directory_service.upsert_user(
            full_name="Visitor",
            email="visitor@example.com",
            youtrack_assignee_email="",
            user_type=UserType.visitor,
            active=True,
        )
        self.assertTrue(self.permission_service.can_modify_issue(visitor, "SEA-1", now=datetime.now(timezone.utc)))

    def test_admin_approval_service_creates_and_consumes_token(self):
        previous_super_admin = settings.super_admin_email
        settings.super_admin_email = "admin@example.com"
        try:
            mailbox = FakeMailboxService([])
            approval_service = AdminApprovalService(self.approvals, mailbox)
            message = MailboxMessage(
                message_id="msg-1",
                mailbox_uid="1",
                sender="power@example.com",
                subject="archive project",
                text="archivia il progetto",
                received_at=datetime.now(timezone.utc),
            )
            plan = MailExecutionPlan(request_text="archivia il progetto", workflow_mode="youtrack", admin_scope=True)
            approval, _ = approval_service.create(message, plan, "Power User", "power@example.com")
            self.assertTrue(mailbox.sent_messages)
            token = re.search(r"\b([A-Za-z0-9_\-]{20,})\b", mailbox.sent_messages[0][2]).group(1)
            approved = approval_service.approve_from_message("admin@example.com", token)
            self.assertEqual(approval.id, approved.id if approved else None)
        finally:
            settings.super_admin_email = previous_super_admin

    async def test_query_service_prefers_non_archived_project_match(self):
        results = await self.query_service.search_projects("sea", limit=2)
        self.assertEqual(results[0].project_id, "ZSEA")
        self.assertFalse(results[0].archived)

    async def test_query_service_lists_only_open_funky_issues(self):
        issues = await self.query_service.list_project_issues("FUN", only_open=True, limit=10)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].issue_id_readable, "FJ-11")

    async def test_query_service_summarizes_project_time(self):
        summary = await self.query_service.summarize_project_time("SEA", date(2025, 3, 1), date(2025, 3, 31))
        self.assertEqual(summary.total_minutes, 180)
        self.assertEqual(summary.issue_breakdown[0].issue_id_readable, "SEA-1")

    async def test_query_service_summarizes_time_report_by_author(self):
        summary = await self.query_service.summarize_time_report(date(2025, 3, 1), date(2025, 3, 31), author_hint="mirko")
        self.assertEqual(summary.total_minutes, 180)
        self.assertEqual(summary.project_breakdown[0].project_id, "SEA")

    async def test_query_service_builds_project_context(self):
        context = await self.query_service.build_project_context("funky", limit=5)
        self.assertIsNotNone(context)
        assert context is not None
        self.assertEqual(context.project.project_id, "FUN")
        self.assertEqual(context.open_issues[0].issue_id_readable, "FJ-11")

    async def test_direct_work_item_create_uses_issue_and_minutes(self):
        await self.youtrack_client.add_work_item(
            "ZSEA-14",
            {
                "text": "allineamento su Sprint5 - call interna",
                "date": 1742342400000,
                "duration": {"minutes": 60},
            },
        )
        self.assertEqual(self.youtrack_client.created_work_item_payloads[0][0], "ZSEA-14")
        self.assertEqual(self.youtrack_client.created_work_item_payloads[0][1]["duration"]["minutes"], 60)

    def test_close_day_generates_worklog_issue_and_kb(self):
        request = self.request_service.ingest(
            IngestRequestInput(
                source=RequestSource.manual,
                text=(
                    "oggi ho fatto un'ora di call con SEA, "
                    "ho risolto il bug di funky per la ricerca, segna 2 ore, "
                    "mi serve salvare questo comando cp -a tra la knowledge base dei miei script personali"
                ),
            )
        )
        preview = self.preview_service.build_preview(PreviewInput(request_id=request.id))
        self.assertGreaterEqual(len(preview.worklog_operations), 2)
        self.assertGreaterEqual(len(preview.issue_operations), 1)
        self.assertEqual(len(preview.knowledge_operations), 1)

    def test_preview_preserves_explicit_worklog_comment(self):
        preview = self.preview_service.build_preview(
            PreviewInput(
                text=(
                    "aggiungi 2 ore di lavorazione sul task ES-40. "
                    "Commento sulla lavorazione: ripristino funzionalita pagina catalogo B2B. "
                    "Indagine e sistemazione problematica"
                ),
                project_id="0-7",
                customer_label="Ellesanti",
            )
        )
        self.assertEqual(len(preview.worklog_operations), 1)
        self.assertEqual(
            preview.worklog_operations[0].description,
            "ripristino funzionalita pagina catalogo B2B. Indagine e sistemazione problematica",
        )

    async def test_commit_is_idempotent_for_same_preview(self):
        request = self.request_service.ingest(
            IngestRequestInput(
                source=RequestSource.manual,
                text="SEA BUG-1 fix completato, segna 1 ora e salva questo comando in kb personale",
            )
        )
        preview = self.preview_service.build_preview(PreviewInput(request_id=request.id))
        first = await self.commit_service.commit(CommitInput(preview_id=preview.preview_id, confirm=True))
        second = await self.commit_service.commit(CommitInput(preview_id=preview.preview_id, confirm=True))
        self.assertIn(first.status, {"success", "partial_success"})
        self.assertEqual(second.status, "duplicate")

    async def test_commit_returns_issue_url_in_payload(self):
        request = self.request_service.ingest(
            IngestRequestInput(
                source=RequestSource.manual,
                text="supporto e debug",
                project_id="0-7",
                customer_label="Ellesanti",
            )
        )
        preview = self.preview_service.build_preview(PreviewInput(request_id=request.id))
        result = await self.commit_service.commit(CommitInput(preview_id=preview.preview_id, confirm=True))
        self.assertEqual(result.issue_results[0].payload["url"], "https://youtrack.example.test/issue/SEA-1")

    async def test_mail_automation_rejects_unlisted_domains(self):
        previous_domains = settings.mailbox_allowed_sender_domains
        settings.mailbox_allowed_sender_domains = ("trusted.example",)
        previous_rejected = settings.mailbox_rejected_folder
        settings.mailbox_rejected_folder = "REJECTED"
        try:
            mailbox = FakeMailboxService(
                [
                    type(
                        "Message",
                        (),
                        {
                            "message_id": "m1",
                            "mailbox_uid": "1",
                            "sender": "user@blocked.example",
                            "subject": "hello",
                            "text": "please help",
                        },
                    )()
                ]
            )
            service = MailAutomationService(
                mailbox=mailbox,
                openwebui=FakeOpenWebUIClient(),
                processed=self.mail_processing,
                request_service=self.request_service,
                preview_service=self.preview_service,
                commit_service=self.commit_service,
                youtrack_client=self.youtrack_client,
                query_service=self.query_service,
                issue_subscription_service=IssueSubscriptionService(self.issue_subscriptions, self.youtrack_client, mailbox),
            )
            result = await service.run_once()
            self.assertEqual(result[0].status, "rejected_domain")
            self.assertEqual(mailbox.replies, [])
            self.assertEqual(mailbox.moves, [("1", "REJECTED")])
        finally:
            settings.mailbox_allowed_sender_domains = previous_domains
            settings.mailbox_rejected_folder = previous_rejected

    async def test_mail_automation_moves_processed_message_to_processed_folder(self):
        previous_domains = settings.mailbox_allowed_sender_domains
        previous_processed = settings.mailbox_processed_folder
        previous_assignee_login = settings.youtrack_default_assignee_login
        settings.mailbox_allowed_sender_domains = ("trusted.example",)
        settings.mailbox_processed_folder = "PROCESSED"
        settings.youtrack_default_assignee_login = "acmemediakits"
        try:
            mailbox = FakeMailboxService(
                [
                    type(
                        "Message",
                        (),
                        {
                            "message_id": "m2",
                            "mailbox_uid": "2",
                            "sender": "ops@trusted.example",
                            "subject": "Re: modifica sito omc-laser",
                            "text": "Il progetto e' Stefano Leo",
                        },
                    )()
                ]
            )
            planner = FakeOpenWebUIClient(
                payload={
                    "request_text": (
                        "Crea una issue per il progetto Stefano Leo: "
                        "aggiungere un pulsante Contattaci nel menu principale del sito omc-laser, "
                        "colore blu con testo bianco, link alla pagina contatti con form protetto da reCAPTCHA."
                    ),
                    "customer_label": "Stefano Leo",
                    "project_hint": "Stefano Leo",
                    "project_id": None,
                    "issue_summary": "Aggiungere pulsante Contattaci nel menu principale di omc-laser",
                    "issue_description": (
                        "Inserire un pulsante Contattaci nel menu principale del sito omc-laser.\n"
                        "- sfondo blu\n"
                        "- testo bianco\n"
                        "- collegamento alla pagina contatti con form\n"
                        "- protezione reCAPTCHA sul form"
                    ),
                    "issue_assignee": "developers",
                    "needs_clarification": False,
                    "clarification_question": None,
                    "reply_intent": "execute",
                    "reply_draft": None,
                }
            )
            service = MailAutomationService(
                mailbox=mailbox,
                openwebui=planner,
                processed=self.mail_processing,
                request_service=self.request_service,
                preview_service=self.preview_service,
                commit_service=self.commit_service,
                youtrack_client=self.youtrack_client,
                query_service=self.query_service,
                issue_subscription_service=IssueSubscriptionService(self.issue_subscriptions, self.youtrack_client, mailbox),
            )
            result = await service.run_once()
            self.assertEqual(result[0].status, "processed")
            self.assertEqual(mailbox.moves, [("2", "PROCESSED")])
            self.assertTrue(mailbox.replies)
            self.assertIn("Issue aggiornata", mailbox.replies[0][1])
            self.assertIn("Stefano Leo", self.requests.list_all()[0].text)
            payload = self.youtrack_client.created_issue_payloads[0]
            self.assertEqual(payload["summary"], "Aggiungere pulsante Contattaci nel menu principale di omc-laser")
            self.assertIn("reCAPTCHA", payload["description"])
            self.assertNotIn("customFields", payload)
            self.assertTrue(self.youtrack_client.updated_issue_custom_field_payloads)
            self.assertEqual(
                self.youtrack_client.updated_issue_custom_field_payloads[0][2]["value"]["login"],
                "acmemediakits",
            )
            self.assertEqual(
                self.youtrack_client.updated_issue_custom_field_payloads[0][2]["name"],
                "ZD_SEA Team",
            )
            self.assertIn("assegnata a developers", mailbox.replies[0][1])
        finally:
            settings.mailbox_allowed_sender_domains = previous_domains
            settings.mailbox_processed_folder = previous_processed
            settings.youtrack_default_assignee_login = previous_assignee_login

    async def test_mail_automation_moves_clarification_reply_to_processing_folder(self):
        previous_domains = settings.mailbox_allowed_sender_domains
        previous_processing = settings.mailbox_processing_folder
        settings.mailbox_allowed_sender_domains = ("trusted.example",)
        settings.mailbox_processing_folder = "PROCESSING"
        try:
            mailbox = FakeMailboxService(
                [
                    type(
                        "Message",
                        (),
                        {
                            "message_id": "m3",
                            "mailbox_uid": "3",
                            "sender": "user@trusted.example",
                            "subject": "hello",
                            "text": "mi aiuti?",
                        },
                    )()
                ]
            )
            service = MailAutomationService(
                mailbox=mailbox,
                openwebui=FakeOpenWebUIClient(
                    payload={
                        "request_text": "Richiesta generica di aiuto senza dettagli sufficienti.",
                        "customer_label": None,
                        "project_hint": None,
                        "project_id": None,
                        "needs_clarification": True,
                        "clarification_question": "Mi puoi confermare a quale progetto YouTrack si riferisce la richiesta?",
                        "reply_intent": "clarify",
                        "reply_draft": None,
                    }
                ),
                processed=self.mail_processing,
                request_service=self.request_service,
                preview_service=self.preview_service,
                commit_service=self.commit_service,
                youtrack_client=self.youtrack_client,
                query_service=self.query_service,
                issue_subscription_service=IssueSubscriptionService(self.issue_subscriptions, self.youtrack_client, mailbox),
            )
            result = await service.run_once()
            self.assertEqual(result[0].finish_reason, "clarification_required")
            self.assertEqual(mailbox.moves, [("3", "PROCESSING")])
            self.assertIn("progetto youtrack", mailbox.replies[0][1].lower())
        finally:
            settings.mailbox_allowed_sender_domains = previous_domains
            settings.mailbox_processing_folder = previous_processing

    async def test_mail_automation_assist_mode_does_not_create_ticket(self):
        previous_domains = settings.mailbox_allowed_sender_domains
        settings.mailbox_allowed_sender_domains = ("trusted.example",)
        try:
            mailbox = FakeMailboxService(
                [
                    type(
                        "Message",
                        (),
                        {
                            "message_id": "m-assist",
                            "mailbox_uid": "10",
                            "sender": "user@trusted.example",
                            "subject": "Fwd: mail rumorosa cliente",
                            "text": "Mi riassumi questa mail e dimmi cosa vuole il cliente?",
                        },
                    )()
                ]
            )
            service = MailAutomationService(
                mailbox=mailbox,
                openwebui=FakeOpenWebUIClient(
                    payload={
                        "request_text": "Riassumi la mail rumorosa e spiega cosa chiede il cliente.",
                        "workflow_mode": "assist",
                        "assist_intent": "summarize",
                        "customer_label": None,
                        "project_hint": None,
                        "project_id": None,
                        "needs_clarification": False,
                        "clarification_question": None,
                        "reply_intent": "execute",
                        "reply_draft": "Riassunto: il cliente chiede un aggiornamento sul catalogo e una verifica del form contatti.",
                    }
                ),
                processed=self.mail_processing,
                request_service=self.request_service,
                preview_service=self.preview_service,
                commit_service=self.commit_service,
                youtrack_client=self.youtrack_client,
                query_service=self.query_service,
                issue_subscription_service=IssueSubscriptionService(self.issue_subscriptions, self.youtrack_client, mailbox),
            )
            result = await service.run_once()
            self.assertEqual(result[0].finish_reason, "summarize")
            self.assertEqual(len(self.youtrack_client.created_issue_payloads), 0)
            self.assertIn("Riassunto", mailbox.replies[0][1])
        finally:
            settings.mailbox_allowed_sender_domains = previous_domains

    async def test_mail_automation_delegate_request_sends_internal_summary(self):
        previous_domains = settings.mailbox_allowed_sender_domains
        previous_internal_domain = settings.mailbox_internal_domain
        settings.mailbox_allowed_sender_domains = ("trusted.example",)
        settings.mailbox_internal_domain = "acmemk.com"
        try:
            mailbox = FakeMailboxService(
                [
                    type(
                        "Message",
                        (),
                        {
                            "message_id": "m-delegate",
                            "mailbox_uid": "11",
                            "sender": "daiana@trusted.example",
                            "subject": "Landing page cliente",
                            "text": "Manda riassunto a: Luca. Il cliente vuole che tu ti occupi del restyling della hero e del form contatti.",
                        },
                    )()
                ]
            )
            service = MailAutomationService(
                mailbox=mailbox,
                openwebui=FakeOpenWebUIClient(payload={"request_text": "Il cliente vuole che tu ti occupi del restyling della hero e del form contatti."}),
                processed=self.mail_processing,
                request_service=self.request_service,
                preview_service=self.preview_service,
                commit_service=self.commit_service,
                youtrack_client=self.youtrack_client,
                query_service=self.query_service,
                issue_subscription_service=IssueSubscriptionService(self.issue_subscriptions, self.youtrack_client, mailbox),
            )
            result = await service.run_once()
            self.assertEqual(result[0].finish_reason, "clarification_required")
            self.assertEqual(len(self.youtrack_client.created_issue_payloads), 0)
            self.assertIn("inoltri", mailbox.replies[0][1].lower())
        finally:
            settings.mailbox_allowed_sender_domains = previous_domains
            settings.mailbox_internal_domain = previous_internal_domain

    async def test_mail_automation_delegate_request_uses_planner_intent(self):
        previous_domains = settings.mailbox_allowed_sender_domains
        previous_internal_domain = settings.mailbox_internal_domain
        settings.mailbox_allowed_sender_domains = ("trusted.example",)
        settings.mailbox_internal_domain = "acmemk.com"
        try:
            mailbox = FakeMailboxService(
                [
                    type(
                        "Message",
                        (),
                        {
                            "message_id": "m-delegate-plan",
                            "mailbox_uid": "13",
                            "sender": "daiana@trusted.example",
                            "subject": "Landing page cliente",
                            "text": "Devi ricordare a Daiana che dobbiamo organizzare un incontro da Zampediverse.",
                        },
                    )()
                ]
            )
            service = MailAutomationService(
                mailbox=mailbox,
                openwebui=FakeOpenWebUIClient(
                    payload={
                        "request_text": "Ricorda a Daiana di organizzare un incontro da Zampediverse la prossima settimana.",
                        "workflow_mode": "assist",
                        "assist_intent": "delegate",
                        "delegate_to_name": "Daiana",
                        "delegate_body": "Ciao Daiana,\n\nMirko chiede di organizzare per la prossima settimana un incontro da Zampediverse sui progetti AI.",
                        "reply_intent": "execute",
                    }
                ),
                processed=self.mail_processing,
                request_service=self.request_service,
                preview_service=self.preview_service,
                commit_service=self.commit_service,
                youtrack_client=self.youtrack_client,
                query_service=self.query_service,
                issue_subscription_service=IssueSubscriptionService(self.issue_subscriptions, self.youtrack_client, mailbox),
            )
            result = await service.run_once()
            self.assertEqual(result[0].finish_reason, "delegate")
            self.assertEqual(mailbox.sent_messages[0][0], "daiana@acmemk.com")
            self.assertIn("organizzare", mailbox.sent_messages[0][2].lower())
        finally:
            settings.mailbox_allowed_sender_domains = previous_domains
            settings.mailbox_internal_domain = previous_internal_domain

    async def test_mail_automation_blocks_third_party_reply_when_not_delegate(self):
        previous_domains = settings.mailbox_allowed_sender_domains
        settings.mailbox_allowed_sender_domains = ("trusted.example",)
        try:
            mailbox = FakeMailboxService(
                [
                    type(
                        "Message",
                        (),
                        {
                            "message_id": "m-third-party-reply",
                            "mailbox_uid": "14",
                            "sender": "mirko@trusted.example",
                            "subject": "Promemoria",
                            "text": "Ricorda a Daiana che dobbiamo sentirci.",
                        },
                    )()
                ]
            )
            service = MailAutomationService(
                mailbox=mailbox,
                openwebui=FakeOpenWebUIClient(
                    payload={
                        "request_text": "Ricorda a Daiana che dobbiamo sentirci.",
                        "workflow_mode": "assist",
                        "assist_intent": "summarize",
                        "reply_intent": "execute",
                        "reply_draft": "Ciao Daiana,\n\nricorda che dobbiamo sentirci.",
                    }
                ),
                processed=self.mail_processing,
                request_service=self.request_service,
                preview_service=self.preview_service,
                commit_service=self.commit_service,
                youtrack_client=self.youtrack_client,
                query_service=self.query_service,
                issue_subscription_service=IssueSubscriptionService(self.issue_subscriptions, self.youtrack_client, mailbox),
            )
            result = await service.run_once()
            self.assertEqual(result[0].status, "error")
            self.assertEqual(mailbox.replies[0][0], "m-third-party-reply")
            self.assertIn("technical problem", mailbox.replies[0][1].lower())
        finally:
            settings.mailbox_allowed_sender_domains = previous_domains

    async def test_mail_automation_time_report_uses_timesheet_summary(self):
        previous_domains = settings.mailbox_allowed_sender_domains
        settings.mailbox_allowed_sender_domains = ("trusted.example",)
        try:
            mailbox = FakeMailboxService(
                [
                    type(
                        "Message",
                        (),
                        {
                            "message_id": "m-report",
                            "mailbox_uid": "12",
                            "sender": "mirko@trusted.example",
                            "subject": "Riassunto ore febbraio",
                            "text": "Ciao mi fai un riassunto delle ore spese nelle lavorazioni in febbraio 2025? Raggruppa per progetto e segna il totale delle ore.",
                        },
                    )()
                ]
            )
            service = MailAutomationService(
                mailbox=mailbox,
                openwebui=FakeOpenWebUIClient(payload={"request_text": "Riassunto ore febbraio 2025", "workflow_mode": "assist", "assist_intent": "summarize"}),
                processed=self.mail_processing,
                request_service=self.request_service,
                preview_service=self.preview_service,
                commit_service=self.commit_service,
                youtrack_client=self.youtrack_client,
                query_service=self.query_service,
                issue_subscription_service=IssueSubscriptionService(self.issue_subscriptions, self.youtrack_client, mailbox),
            )
            result = await service.run_once()
            self.assertEqual(result[0].finish_reason, "time_report")
            self.assertIn("Totale ore", mailbox.replies[0][1])
            self.assertIn("Raggruppamento per progetto", mailbox.replies[0][1])
        finally:
            settings.mailbox_allowed_sender_domains = previous_domains

    async def test_issue_subscription_service_notifies_requester_on_issue_changes(self):
        mailbox = FakeMailboxService([])
        subscription_service = IssueSubscriptionService(self.issue_subscriptions, self.youtrack_client, mailbox)
        await subscription_service.subscribe("SEA-1", "daiana@trusted.example", requester_name="Daiana", source_subject="Nuovo task")
        self.youtrack_client.issue_details["SEA-1"]["resolved"] = True
        self.youtrack_client.issue_details["SEA-1"]["updated"] = 1741910000000
        self.youtrack_client.issue_details["SEA-1"]["customFields"] = [
            {"name": "ZD_SEA Team", "$type": "SingleUserIssueCustomField", "value": {"login": "acmemediakits", "fullName": "developers"}},
            {"name": "State", "$type": "StateIssueCustomField", "value": {"name": "Done", "isResolved": True}},
        ]
        self.youtrack_client.issue_work_items["SEA-1"].append(
            {
                "id": "155-1206",
                "text": "chiusura task",
                "issue_id": "SEA-1",
                "date": 1741910000000,
                "duration": {"minutes": 30},
                "author": {"fullName": "Mirko Bianco", "login": "mirko"},
            }
        )
        updated = await subscription_service.notify_updates()
        self.assertEqual(len(updated), 1)
        self.assertEqual(mailbox.sent_messages[0][0], "daiana@trusted.example")
        self.assertIn("ticket chiuso", mailbox.sent_messages[0][2].lower())

    async def test_mail_automation_falls_back_when_planner_returns_tool_calls(self):
        previous_domains = settings.mailbox_allowed_sender_domains
        previous_processing = settings.mailbox_processing_folder
        settings.mailbox_allowed_sender_domains = ("trusted.example",)
        settings.mailbox_processing_folder = "PROCESSING"
        try:
            mailbox = FakeMailboxService(
                [
                    type(
                        "Message",
                        (),
                        {
                            "message_id": "m4",
                            "mailbox_uid": "4",
                            "sender": "user@trusted.example",
                            "subject": "supporto",
                            "text": "aiuto",
                        },
                    )()
                ]
            )
            service = MailAutomationService(
                mailbox=mailbox,
                openwebui=FakeOpenWebUIClient(tool_calls_detected=True, content=""),
                processed=self.mail_processing,
                request_service=self.request_service,
                preview_service=self.preview_service,
                commit_service=self.commit_service,
                youtrack_client=self.youtrack_client,
                query_service=self.query_service,
                issue_subscription_service=IssueSubscriptionService(self.issue_subscriptions, self.youtrack_client, mailbox),
            )
            result = await service.run_once()
            self.assertEqual(result[0].finish_reason, "clarification_required")
            self.assertEqual(mailbox.moves, [("4", "PROCESSING")])
        finally:
            settings.mailbox_allowed_sender_domains = previous_domains
            settings.mailbox_processing_folder = previous_processing

    async def test_mail_automation_skips_duplicate_message_id(self):
        previous_domains = settings.mailbox_allowed_sender_domains
        settings.mailbox_allowed_sender_domains = ("trusted.example",)
        try:
            mailbox = FakeMailboxService(
                [
                    type(
                        "Message",
                        (),
                        {
                            "message_id": "m4",
                            "mailbox_uid": "4",
                            "sender": "user@trusted.example",
                            "subject": "supporto e debug",
                            "text": "crea una issue",
                        },
                    )()
                ]
            )
            self.mail_processing.upsert(
                "existing",
                MailProcessingRecord(
                    id="existing",
                    message_id="m4",
                    mailbox_uid="4",
                    sender="user@trusted.example",
                    subject="supporto e debug",
                    status="processed",
                    response_text="already done",
                    finish_reason="success",
                ),
            )
            service = MailAutomationService(
                mailbox=mailbox,
                openwebui=FakeOpenWebUIClient(),
                processed=self.mail_processing,
                request_service=self.request_service,
                preview_service=self.preview_service,
                commit_service=self.commit_service,
                youtrack_client=self.youtrack_client,
                query_service=self.query_service,
                issue_subscription_service=IssueSubscriptionService(self.issue_subscriptions, self.youtrack_client, mailbox),
            )
            result = await service.run_once()
            self.assertEqual(result, [])
            self.assertEqual(mailbox.moves, [])
            self.assertEqual(mailbox.replies, [])
        finally:
            settings.mailbox_allowed_sender_domains = previous_domains


if __name__ == "__main__":
    unittest.main()
