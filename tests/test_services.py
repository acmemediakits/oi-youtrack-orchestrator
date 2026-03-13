from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.config import settings
from app.models import CommitInput, IngestRequestInput, PreviewInput, RequestSource
from app.repositories import CommitRepository, CustomerDirectoryRepository, PreviewRepository, RequestRepository
from app.services import CommitService, PreviewService, ProjectMatcher, RequestService


class FakeYouTrackClient:
    def __init__(self) -> None:
        self.issue_counter = 0
        self.worklog_counter = 0
        self.article_counter = 0

    async def create_issue(self, payload):
        self.issue_counter += 1
        return {"id": f"issue_{self.issue_counter}", "idReadable": f"SEA-{self.issue_counter}", **payload}

    async def update_issue(self, issue_id, payload):
        return {"id": issue_id, "idReadable": issue_id, **payload}

    async def add_work_item(self, issue_id, payload):
        self.worklog_counter += 1
        return {"id": f"worklog_{self.worklog_counter}", "issue_id": issue_id, **payload}

    async def create_article(self, payload):
        self.article_counter += 1
        return {"id": f"article_{self.article_counter}", "idReadable": f"ART-{self.article_counter}", **payload}


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
        self.commit_service = CommitService(self.previews, self.commits, self.requests, FakeYouTrackClient())

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

    def test_preview_flags_ambiguous_worklog_without_issue(self):
        preview = self.preview_service.build_preview(
            PreviewInput(text="Ho fatto 2 ore di analisi ma non ricordo il progetto")
        )
        self.assertTrue(preview.requires_confirmation)
        self.assertGreaterEqual(len(preview.open_questions), 1)

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


if __name__ == "__main__":
    unittest.main()
