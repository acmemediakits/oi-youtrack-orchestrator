from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.config import settings
from app.models import CommitInput, IngestRequestInput, MailProcessingRecord, OpenWebUIReply, PreviewInput, RequestSource
from app.mail_agent import MailAutomationService
from app.repositories import CommitRepository, CustomerDirectoryRepository, MailProcessingRepository, PreviewRepository, RequestRepository
from app.services import CommitService, PreviewService, ProjectMatcher, RequestService


class FakeYouTrackClient:
    def __init__(self) -> None:
        self.issue_counter = 0
        self.worklog_counter = 0
        self.article_counter = 0
        self.created_issue_payloads = []
        self.updated_issue_payloads = []

    async def create_issue(self, payload):
        self.issue_counter += 1
        self.created_issue_payloads.append(payload)
        return {"id": f"issue_{self.issue_counter}", "idReadable": f"SEA-{self.issue_counter}", **payload}

    async def update_issue(self, issue_id, payload):
        self.updated_issue_payloads.append((issue_id, payload))
        return {"id": issue_id, "idReadable": issue_id, **payload}

    async def add_work_item(self, issue_id, payload):
        self.worklog_counter += 1
        return {"id": f"worklog_{self.worklog_counter}", "issue_id": issue_id, **payload}

    async def create_article(self, payload):
        self.article_counter += 1
        return {"id": f"article_{self.article_counter}", "idReadable": f"ART-{self.article_counter}", **payload}

    async def get_issue(self, issue_id):
        return {"id": issue_id, "idReadable": issue_id, "summary": "Example issue"}

    async def list_issue_work_items(self, issue_id):
        return [{"id": "155-1204", "text": "old text", "issue_id": issue_id}]

    async def update_work_item(self, issue_id, item_id, payload):
        return {"id": item_id, **payload}

    async def list_projects(self):
        return [
            {"id": "SEA", "shortName": "SEA", "name": "SEA"},
            {"id": "0-7", "shortName": "ES", "name": "Stefano Leo"},
        ]

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

    def fetch_unseen(self, limit: int = 20):
        return self.messages[:limit]

    def sender_domain(self, sender: str):
        return sender.rsplit("@", 1)[1].lower() if "@" in sender else None

    def send_reply(self, original, body: str):
        self.replies.append((original.message_id, body))

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
        self.matcher = ProjectMatcher(self.directory)
        self.request_service = RequestService(self.requests, self.matcher)
        self.preview_service = PreviewService(self.requests, self.previews, self.matcher)
        self.youtrack_client = FakeYouTrackClient()
        self.commit_service = CommitService(self.previews, self.commits, self.requests, self.youtrack_client)
        self.mail_processing = MailProcessingRepository()

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
        settings.mailbox_allowed_sender_domains = ("sea.example.com",)
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
            self.assertTrue(self.youtrack_client.updated_issue_payloads)
            self.assertEqual(
                self.youtrack_client.updated_issue_payloads[0][1]["customFields"][0]["value"]["login"],
                "acmemediakits",
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
            )
            result = await service.run_once()
            self.assertEqual(result[0].finish_reason, "clarification_required")
            self.assertEqual(mailbox.moves, [("3", "PROCESSING")])
            self.assertIn("progetto youtrack", mailbox.replies[0][1].lower())
        finally:
            settings.mailbox_allowed_sender_domains = previous_domains
            settings.mailbox_processing_folder = previous_processing

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
            )
            result = await service.run_once()
            self.assertEqual(result, [])
            self.assertEqual(mailbox.moves, [])
            self.assertEqual(mailbox.replies, [])
        finally:
            settings.mailbox_allowed_sender_domains = previous_domains


if __name__ == "__main__":
    unittest.main()
