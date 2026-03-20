from __future__ import annotations

from functools import lru_cache

from app.clients import OpenWebUIClient, YouTrackClient
from app.mail_agent import MailAutomationRunner, MailAutomationService
from app.mailbox import MailboxService
from app.repositories import (
    AdminApprovalRepository,
    CommitRepository,
    CustomerDirectoryRepository,
    IssueSubscriptionRepository,
    MailProcessingRepository,
    PreviewRepository,
    RequestRepository,
    RuntimeConfigRepository,
    UserDirectoryRepository,
)
from app.services import (
    AdminApprovalService,
    CommitService,
    IssueSubscriptionService,
    PermissionService,
    PreviewService,
    ProjectMatcher,
    QueryService,
    RequestService,
    RuntimeConfigService,
    UserDirectoryService,
)


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
def get_runtime_config_repository() -> RuntimeConfigRepository:
    return RuntimeConfigRepository()


@lru_cache
def get_user_directory_repository() -> UserDirectoryRepository:
    return UserDirectoryRepository()


@lru_cache
def get_admin_approval_repository() -> AdminApprovalRepository:
    return AdminApprovalRepository()


@lru_cache
def get_issue_subscription_repository() -> IssueSubscriptionRepository:
    return IssueSubscriptionRepository()


@lru_cache
def get_customer_directory_repository() -> CustomerDirectoryRepository:
    return CustomerDirectoryRepository()


@lru_cache
def get_runtime_config_service() -> RuntimeConfigService:
    return RuntimeConfigService(repository=get_runtime_config_repository())


@lru_cache
def get_user_directory_service() -> UserDirectoryService:
    return UserDirectoryService(repository=get_user_directory_repository())


@lru_cache
def get_permission_service() -> PermissionService:
    return PermissionService(subscriptions=get_issue_subscription_repository())


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
def get_query_service() -> QueryService:
    return QueryService(
        directory=get_customer_directory_repository(),
        youtrack_client=get_youtrack_client(),
    )


@lru_cache
def get_youtrack_client() -> YouTrackClient:
    return YouTrackClient()


@lru_cache
def get_openwebui_client() -> OpenWebUIClient:
    return OpenWebUIClient()


@lru_cache
def get_mailbox_service() -> MailboxService:
    return MailboxService(runtime_config=get_runtime_config_service())


@lru_cache
def get_commit_service() -> CommitService:
    return CommitService(
        previews=get_preview_repository(),
        commits=get_commit_repository(),
        requests=get_request_repository(),
        youtrack_client=get_youtrack_client(),
    )


@lru_cache
def get_issue_subscription_service() -> IssueSubscriptionService:
    return IssueSubscriptionService(
        subscriptions=get_issue_subscription_repository(),
        youtrack_client=get_youtrack_client(),
        mailbox=get_mailbox_service(),
    )


@lru_cache
def get_admin_approval_service() -> AdminApprovalService:
    return AdminApprovalService(
        approvals=get_admin_approval_repository(),
        mailbox=get_mailbox_service(),
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
        query_service=get_query_service(),
        issue_subscription_service=get_issue_subscription_service(),
        runtime_config=get_runtime_config_service(),
        user_directory=get_user_directory_service(),
        permissions=get_permission_service(),
        admin_approvals=get_admin_approval_service(),
    )


@lru_cache
def get_mail_automation_runner() -> MailAutomationRunner:
    return MailAutomationRunner(service=get_mail_automation_service(), runtime_config=get_runtime_config_service())
