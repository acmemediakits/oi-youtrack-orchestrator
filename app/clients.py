from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings
from app.models import OpenWebUIReply

logger = logging.getLogger(__name__)


class YouTrackError(RuntimeError):
    pass


@dataclass(slots=True)
class YouTrackClient:
    base_url: str = settings.youtrack_base_url
    browser_url: str = settings.youtrack_browser_url
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
            params={"fields": "id,shortName,name,description,archived"},
        )

    async def get_project(self, project_id: str) -> dict[str, Any]:
        return await self._request(
            "GET",
            f"/api/admin/projects/{project_id}",
            params={"fields": "id,shortName,name,description,archived"},
        )

    async def update_project(self, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/api/admin/projects/{project_id}",
            params={"fields": "id,shortName,name,description,archived"},
            json_body=payload,
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

    async def list_issue_custom_fields(self, issue_id: str) -> list[dict[str, Any]]:
        return await self._request(
            "GET",
            f"/api/issues/{issue_id}/customFields",
            params={
                "fields": self._issue_custom_field_fields(),
            },
        )

    async def get_issue_custom_field(self, issue_id: str, field_id: str) -> dict[str, Any]:
        return await self._request(
            "GET",
            f"/api/issues/{issue_id}/customFields/{field_id}",
            params={
                "fields": self._issue_custom_field_fields(),
            },
        )

    async def get_user_bundle(self, bundle_id: str) -> dict[str, Any]:
        return await self._request(
            "GET",
            f"/api/admin/customFieldSettings/bundles/user/{bundle_id}",
            params={
                "fields": (
                    "id,"
                    "aggregatedUsers(id,name,fullName,login,email),"
                    "individuals(id,name,fullName,login,email),"
                    "groups(id,name,presentation)"
                )
            },
        )

    async def update_issue_custom_field(self, issue_id: str, field_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/api/issues/{issue_id}/customFields/{field_id}",
            params={"fields": "id,name,$type,value(id,name,fullName,login,presentation,isResolved)"},
            json_body=payload,
        )

    async def apply_command(self, issue_id: str, query: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/commands",
            params={"fields": "id,query,issues(id,idReadable,summary)"},
            json_body={
                "query": query,
                "issues": [{"idReadable": issue_id}],
            },
        )

    async def add_work_item(self, issue_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/api/issues/{issue_id}/timeTracking/workItems",
            params={"fields": "id,duration(minutes),text,date"},
            json_body=payload,
        )

    async def search_issues(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        return await self._request(
            "GET",
            "/api/issues",
            params={
                "query": query,
                "$top": limit,
                "fields": (
                    "id,idReadable,summary,resolved,updated,"
                    "project(id,shortName,name,archived),"
                    "customFields(name,value(name,fullName,login,presentation,isResolved))"
                ),
            },
        )

    async def create_article(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/articles",
            params={"fields": "id,idReadable,summary"},
            json_body=payload,
        )

    async def search_articles(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        return await self._request(
            "GET",
            "/api/articles",
            params={
                "query": query,
                "$top": limit,
                "fields": "id,idReadable,summary,updated,project(id,name,shortName)",
            },
        )

    async def get_issue(self, issue_id: str) -> dict[str, Any]:
        return await self._request(
            "GET",
            f"/api/issues/{issue_id}",
            params={
                "fields": (
                    "id,idReadable,summary,description,resolved,updated,project(id,shortName,name),"
                    "customFields(name,$type,value(name,fullName,login,presentation,isResolved))"
                )
            },
        )

    async def list_issue_work_items(self, issue_id: str) -> list[dict[str, Any]]:
        return await self._request(
            "GET",
            f"/api/issues/{issue_id}/timeTracking/workItems",
            params={"fields": "id,text,date,duration(minutes),type(id,name),author(id,login,fullName)"},
        )

    async def update_work_item(self, issue_id: str, item_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/api/issues/{issue_id}/timeTracking/workItems/{item_id}",
            params={"fields": "id,text,date,duration(minutes)"},
            json_body=payload,
        )

    def issue_url(self, issue_id_readable: str | None) -> str | None:
        if not issue_id_readable:
            return None
        return f"{self.browser_url.rstrip('/')}/issue/{issue_id_readable}"

    def _issue_custom_field_fields(self) -> str:
        return (
            "id,name,$type,"
            "projectCustomField("
            "id,canBeEmpty,field(id,name),"
            "bundle("
            "id,"
            "values(id,name,presentation,fullName,login,email),"
            "aggregatedUsers(id,name,fullName,login,email),"
            "individuals(id,name,fullName,login,email),"
            "groups(id,name,presentation)"
            ")"
            "),"
            "value(id,name,fullName,login,presentation,email,isResolved,text),"
            "possibleEvents(id,name,presentation)"
        )


@dataclass(slots=True)
class OpenWebUIClient:
    base_url: str = settings.openwebui_base_url
    chat_completions_path: str = settings.openwebui_chat_completions_path
    api_token: str = settings.openwebui_api_token
    model_id: str = settings.openwebui_model_id
    timeout_seconds: int = settings.openwebui_timeout_seconds

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        return headers

    async def _chat(self, messages: list[dict[str, str]], response_format: dict[str, Any] | None = None) -> OpenWebUIReply:
        if not self.api_token:
            raise RuntimeError("OPENWEBUI_API_TOKEN is not configured.")

        url = f"{self.base_url.rstrip('/')}/{self.chat_completions_path.lstrip('/')}"
        payload = {
            "model": self.model_id,
            "messages": messages,
        }
        if response_format:
            payload["response_format"] = response_format
        logger.info("Calling Open WebUI model '%s' at %s", self.model_id, url)
        async with httpx.AsyncClient(timeout=float(self.timeout_seconds)) as client:
            response = await client.post(url, headers=self._headers(), json=payload)
        if response.is_error:
            logger.error("Open WebUI request failed: status=%s body=%s", response.status_code, response.text)
            raise RuntimeError(f"Open WebUI API error {response.status_code}: {response.text}")
        data = response.json()
        if not isinstance(data, dict):
            logger.error("Open WebUI returned non-object JSON payload: %r", data)
            raise RuntimeError("Open WebUI returned an invalid JSON payload: expected an object.")
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            logger.error("Open WebUI returned an invalid choices payload: %s", data)
            raise RuntimeError("Open WebUI returned an invalid response: missing choices[0].")
        choice = choices[0]
        message = choice.get("message") or {}
        if not isinstance(message, dict):
            logger.error("Open WebUI returned an invalid message payload: %s", data)
            raise RuntimeError("Open WebUI returned an invalid response: missing message object.")
        content = (message.get("content") or "").strip()
        finish_reason = choice.get("finish_reason")
        tool_calls = message.get("tool_calls") or []
        tool_calls_detected = bool(tool_calls)
        if settings.verbose:
            logger.debug("Open WebUI raw response: %s", data)
        logger.info(
            "Open WebUI reply received successfully for model '%s' finish_reason=%s tool_calls=%s content_length=%s",
            self.model_id,
            finish_reason,
            tool_calls_detected,
            len(content),
        )
        return OpenWebUIReply(
            content=content,
            finish_reason=finish_reason,
            tool_calls_detected=tool_calls_detected,
            raw_response=data,
        )

    async def generate_reply(self, prompt: str) -> OpenWebUIReply:
        return await self._chat(
            [
                {
                    "role": "user",
                    "content": prompt,
                }
            ]
        )

    async def generate_structured_reply(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> OpenWebUIReply:
        return await self._chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
        )
