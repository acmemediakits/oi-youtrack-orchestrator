from __future__ import annotations

import os
import ssl
from dataclasses import dataclass
from pathlib import Path

from app.models import UserType


def _env_user_type(name: str, default: UserType) -> UserType:
    raw_value = os.getenv(name, default.value).strip().lower()
    try:
        return UserType(raw_value)
    except ValueError:
        return default


@dataclass(slots=True)
class Settings:
    service_role: str = os.getenv("SERVICE_ROLE", "monolith").strip().lower()
    state_backend: str = os.getenv("STATE_BACKEND", "json").strip().lower()
    database_url: str = os.getenv("DATABASE_URL", "").strip()
    app_env: str = os.getenv("APP_ENV", "development")
    verbose: bool = os.getenv("VERBOSE", "false").lower() == "true"
    data_dir: Path = Path(os.getenv("APP_DATA_DIR", "./data"))
    panel_admin_password: str = os.getenv("PANEL_ADMIN_PASSWORD", "")
    super_admin_email: str = os.getenv("SUPER_ADMIN_EMAIL", "")
    youtrack_base_url: str = os.getenv("YOUTRACK_BASE_URL", "https://example.youtrack.cloud")
    youtrack_browser_url: str = os.getenv("YOUTRACK_BROWSER_URL", os.getenv("YOUTRACK_BASE_URL", "https://example.youtrack.cloud"))
    youtrack_token: str = os.getenv("YOUTRACK_TOKEN", "")
    youtrack_default_assignee: str = os.getenv("YOUTRACK_DEFAULT_ASSIGNEE", "developers")
    youtrack_default_assignee_login: str = os.getenv("YOUTRACK_DEFAULT_ASSIGNEE_LOGIN", "")
    youtrack_assignee_field_name: str = os.getenv("YOUTRACK_ASSIGNEE_FIELD_NAME", "Assignee")
    youtrack_default_assignee_email: str = os.getenv("YOUTRACK_DEFAULT_ASSIGNEE_EMAIL", "developers@acmemk.com")
    mailbox_internal_domain: str = os.getenv("MAILBOX_INTERNAL_DOMAIN", "acmemk.com")
    personal_kb_project: str = os.getenv("YOUTRACK_PERSONAL_KB_PROJECT", "OPS")
    personal_kb_folder: str = os.getenv("YOUTRACK_PERSONAL_KB_FOLDER", "Personale")
    default_service_issue: str = os.getenv("YOUTRACK_DEFAULT_SERVICE_ISSUE", "")
    mailbox_imap_host: str = os.getenv("MAILBOX_IMAP_HOST", "")
    mailbox_imap_port: int = int(os.getenv("MAILBOX_IMAP_PORT", "993"))
    mailbox_imap_timeout_seconds: int = int(os.getenv("MAILBOX_IMAP_TIMEOUT_SECONDS", "30"))
    mailbox_imap_tls_mode: str = os.getenv("MAILBOX_IMAP_TLS_MODE", "ssl").lower()
    mailbox_imap_allow_legacy_tls: bool = os.getenv("MAILBOX_IMAP_ALLOW_LEGACY_TLS", "false").lower() == "true"
    mailbox_username: str = os.getenv("MAILBOX_USERNAME", "")
    mailbox_password: str = os.getenv("MAILBOX_PASSWORD", "")
    mailbox_folder: str = os.getenv("MAILBOX_FOLDER", "INBOX")
    mailbox_processing_folder: str = os.getenv("MAILBOX_PROCESSING_FOLDER", "PROCESSING")
    mailbox_processed_folder: str = os.getenv("MAILBOX_PROCESSED_FOLDER", "PROCESSED")
    mailbox_failed_folder: str = os.getenv("MAILBOX_FAILED_FOLDER", "FAILED")
    mailbox_rejected_folder: str = os.getenv("MAILBOX_REJECTED_FOLDER", "REJECTED")
    mailbox_smtp_host: str = os.getenv("MAILBOX_SMTP_HOST", "")
    mailbox_smtp_port: int = int(os.getenv("MAILBOX_SMTP_PORT", "587"))
    mailbox_smtp_protocol: str = os.getenv("MAILBOX_SMTP_PROTOCOL", "TLS")
    mailbox_smtp_timeout_seconds: int = int(os.getenv("MAILBOX_SMTP_TIMEOUT_SECONDS", "30"))
    mailbox_poll_enabled: bool = os.getenv("MAILBOX_POLL_ENABLED", "false").lower() == "true"
    mailbox_poll_interval_seconds: int = int(os.getenv("MAILBOX_POLL_INTERVAL_SECONDS", "60"))
    mailbox_allowed_sender_domains: tuple[str, ...] = tuple(
        domain.strip().lower()
        for domain in os.getenv("MAILBOX_ALLOWED_SENDER_DOMAINS", "").split(",")
        if domain.strip()
    )
    openwebui_base_url: str = os.getenv("OPENWEBUI_BASE_URL", "http://127.0.0.1:8081")
    openwebui_chat_completions_path: str = os.getenv("OPENWEBUI_CHAT_COMPLETIONS_PATH", "/api/chat/completions")
    openwebui_api_token: str = os.getenv("OPENWEBUI_API_TOKEN", "")
    openwebui_model_id: str = os.getenv("OPENWEBUI_MODEL_ID", "YTbot")
    openwebui_timeout_seconds: int = int(os.getenv("OPENWEBUI_TIMEOUT_SECONDS", "120"))
    openwebui_trusted_channel_enabled: bool = os.getenv("OPENWEBUI_TRUSTED_CHANNEL_ENABLED", "true").lower() == "true"
    openwebui_trusted_actor_email: str = os.getenv("OPENWEBUI_TRUSTED_ACTOR_EMAIL", "ytbot@local")
    openwebui_trusted_actor_name: str = os.getenv("OPENWEBUI_TRUSTED_ACTOR_NAME", "YTbot")
    openwebui_trusted_actor_role: UserType = _env_user_type("OPENWEBUI_TRUSTED_ACTOR_ROLE", UserType.power)
    email_orchestrator_mode: str = os.getenv("EMAIL_ORCHESTRATOR_MODE", "openwebui").strip().lower()

    def build_imap_ssl_context(self) -> ssl.SSLContext:
        context = ssl.create_default_context()
        if self.mailbox_imap_allow_legacy_tls:
            context.set_ciphers("DEFAULT@SECLEVEL=1")
        return context

    @property
    def run_mail_worker(self) -> bool:
        return self.service_role in {"monolith", "email_channel"}

    @property
    def expose_tool_core_api(self) -> bool:
        return self.service_role in {"monolith", "tool_core"}


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
