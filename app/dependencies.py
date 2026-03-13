from __future__ import annotations

from functools import lru_cache

from app.clients import YouTrackClient
from app.repositories import CommitRepository, CustomerDirectoryRepository, PreviewRepository, RequestRepository
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
def get_commit_service() -> CommitService:
    return CommitService(
        previews=get_preview_repository(),
        commits=get_commit_repository(),
        requests=get_request_repository(),
        youtrack_client=get_youtrack_client(),
    )
