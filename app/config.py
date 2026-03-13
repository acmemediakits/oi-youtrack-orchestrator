from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class Settings:
    app_env: str = os.getenv("APP_ENV", "development")
    data_dir: Path = Path(os.getenv("APP_DATA_DIR", "./data"))
    youtrack_base_url: str = os.getenv("YOUTRACK_BASE_URL", "https://example.youtrack.cloud")
    youtrack_token: str = os.getenv("YOUTRACK_TOKEN", "")
    personal_kb_project: str = os.getenv("YOUTRACK_PERSONAL_KB_PROJECT", "OPS")
    personal_kb_folder: str = os.getenv("YOUTRACK_PERSONAL_KB_FOLDER", "Personale")
    default_service_issue: str = os.getenv("YOUTRACK_DEFAULT_SERVICE_ISSUE", "")
    mailbox_imap_host: str = os.getenv("MAILBOX_IMAP_HOST", "")
    mailbox_imap_port: int = int(os.getenv("MAILBOX_IMAP_PORT", "993"))
    mailbox_username: str = os.getenv("MAILBOX_USERNAME", "")
    mailbox_password: str = os.getenv("MAILBOX_PASSWORD", "")
    mailbox_folder: str = os.getenv("MAILBOX_FOLDER", "INBOX")
    mailbox_smtp_host: str = os.getenv("MAILBOX_SMTP_HOST", "")
    mailbox_smtp_port: int = int(os.getenv("MAILBOX_SMTP_PORT", "587"))
    mailbox_smtp_protocol: str = os.getenv("MAILBOX_SMTP_PROTOCOL", "TLS")


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
