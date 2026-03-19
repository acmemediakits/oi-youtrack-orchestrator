from __future__ import annotations

from functools import lru_cache

from app.clients import OpenWebUIClient, YouTrackClient
from app.mail_agent import MailAutomationRunner, MailAutomationService
from app.mailbox import MailboxService
from app.repositories import (
    CommitRepository,
    CustomerDirectoryRepository,
    MailProcessingRepository,
    PreviewRepository,
    RequestRepository,
)
from app.services import CommitService, PreviewService, ProjectMatcher, RequestService


@lru_cache
def get_request_repository() -> RequestRepository:
    return RequestRepository()


@lru_cache
def get_preview_repository() -> PreviewRepository:
    return PreviewRepository()


@lru_cache
def get_commit_repository() -> CommitRepository:
    return CommitRepository()


@lru_cache
def get_mail_processing_repository() -> MailProcessingRepository:
    return MailProcessingRepository()


@lru_cache
def get_customer_directory_repository() -> CustomerDirectoryRepository:
    return CustomerDirectoryRepository()


@lru_cache
def get_project_matcher() -> ProjectMatcher:
    return ProjectMatcher(directory=get_customer_directory_repository())


@lru_cache
def get_request_service() -> RequestService:
    return RequestService(requests=get_request_repository(), matcher=get_project_matcher())


@lru_cache
def get_preview_service() -> PreviewService:
    return PreviewService(
        requests=get_request_repository(),
        previews=get_preview_repository(),
        matcher=get_project_matcher(),
    )


@lru_cache
def get_youtrack_client() -> YouTrackClient:
    return YouTrackClient()


@lru_cache
def get_openwebui_client() -> OpenWebUIClient:
    return OpenWebUIClient()


@lru_cache
def get_mailbox_service() -> MailboxService:
    return MailboxService()


@lru_cache
def get_commit_service() -> CommitService:
    return CommitService(
        previews=get_preview_repository(),
        commits=get_commit_repository(),
        requests=get_request_repository(),
        youtrack_client=get_youtrack_client(),
    )


@lru_cache
def get_mail_automation_service() -> MailAutomationService:
    return MailAutomationService(
        mailbox=get_mailbox_service(),
        openwebui=get_openwebui_client(),
        processed=get_mail_processing_repository(),
        request_service=get_request_service(),
        preview_service=get_preview_service(),
        commit_service=get_commit_service(),
        youtrack_client=get_youtrack_client(),
    )


@lru_cache
def get_mail_automation_runner() -> MailAutomationRunner:
    return MailAutomationRunner(service=get_mail_automation_service())
