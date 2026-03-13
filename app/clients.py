from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings


class YouTrackError(RuntimeError):
    pass


@dataclass(slots=True)
class YouTrackClient:
    base_url: str = settings.youtrack_base_url
    token: str = settings.youtrack_token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        if not self.token:
            raise YouTrackError("YOUTRACK_TOKEN is not configured.")

        url = f"{self.base_url.rstrip('/')}{path}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(
                method,
                url,
                headers=self._headers(),
                params=params,
                json=json_body,
            )
        if response.is_error:
            raise YouTrackError(f"YouTrack API error {response.status_code}: {response.text}")
        if not response.content:
            return {}
        return response.json()

    async def list_projects(self) -> list[dict[str, Any]]:
        return await self._request(
            "GET",
            "/api/admin/projects",
            params={"fields": "id,shortName,name,archived"},
        )

    async def create_issue(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/issues",
            params={"fields": "id,idReadable,summary"},
            json_body=payload,
        )

    async def update_issue(self, issue_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/api/issues/{issue_id}",
            params={"fields": "id,idReadable,summary"},
            json_body=payload,
        )

    async def add_work_item(self, issue_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/api/issues/{issue_id}/timeTracking/workItems",
            params={"fields": "id,duration(minutes),text,date"},
            json_body=payload,
        )

    async def create_article(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/articles",
            params={"fields": "id,idReadable,summary"},
            json_body=payload,
        )
