from __future__ import annotations

import json
from pathlib import Path

from app.config import settings
from app.models import ActionPreview, CommitResult, CustomerRule, MailProcessingRecord, NormalizedRequest
from app.storage import JsonStore


class RequestRepository(JsonStore[NormalizedRequest]):
    def __init__(self) -> None:
        super().__init__("requests.json", NormalizedRequest)


class PreviewRepository(JsonStore[ActionPreview]):
    def __init__(self) -> None:
        super().__init__("previews.json", ActionPreview)


class CommitRepository(JsonStore[CommitResult]):
    def __init__(self) -> None:
        super().__init__("commits.json", CommitResult)

    def find_by_preview_id(self, preview_id: str) -> CommitResult | None:
        for item in self.list_all():
            if item.preview_id == preview_id:
                return item
        return None


class CustomerDirectoryRepository:
    def __init__(self) -> None:
        self.path = Path(settings.data_dir) / "client_directory.json"
        if not self.path.exists():
            self.path.write_text(
                json.dumps(
                    [
                        {
                            "customer_label": "SEA",
                            "aliases": ["sea", "sea agency"],
                            "domains": ["sea.example.com"],
                            "project_ids": ["SEA"],
                            "default_project_id": "SEA",
                            "tags": ["cliente:sea"],
                        },
                        {
                            "customer_label": "Funky",
                            "aliases": ["funky", "funky studio"],
                            "domains": ["funky.example.com"],
                            "project_ids": ["FUN"],
                            "default_project_id": "FUN",
                            "tags": ["cliente:funky"],
                        },
                    ],
                    indent=2,
                ),
                encoding="utf-8",
            )

    def list_all(self) -> list[CustomerRule]:
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return [CustomerRule.model_validate(item) for item in raw]


class MailProcessingRepository(JsonStore[MailProcessingRecord]):
    def __init__(self) -> None:
        super().__init__("mail_processing.json", MailProcessingRecord)

    def find_by_message_id(self, message_id: str) -> MailProcessingRecord | None:
        for item in self.list_all():
            if item.message_id == message_id:
                return item
        return None
