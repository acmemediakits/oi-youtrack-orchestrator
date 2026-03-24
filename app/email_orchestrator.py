from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.config import settings
from app.models import EmailChannelPayload, OpenWebUIReply

logger = logging.getLogger(__name__)


class EmailOrchestrator(Protocol):
    async def plan(self, payload: EmailChannelPayload) -> OpenWebUIReply | None:
        ...


@dataclass(slots=True)
class OpenWebUIEmailOrchestrator:
    openwebui: any
    prompt_path: Path = Path(__file__).resolve().parents[1] / "prompts" / "email_channel_planner.md"

    def _system_prompt(self) -> str:
        if self.prompt_path.exists():
            return self.prompt_path.read_text(encoding="utf-8")
        logger.warning("Email planner prompt file missing at %s. Falling back to inline prompt.", self.prompt_path)
        return (
            "You are YTBot acting as a planner for an IMAP automation caller.\n"
            "You understand the whole email thread and must prepare a safe execution plan.\n"
            "Do not call tools directly. Return only valid JSON following the MailExecutionPlan schema.\n"
            "Use workflow_mode='assist' for non-YouTrack assistance. "
            "Use workflow_mode='youtrack' only for explicit ticketing/project/worklog/KB actions.\n"
            "Use issue_assignee='developers' only as a default for new issues when nothing better is specified.\n"
        )

    def _user_prompt(self, payload: EmailChannelPayload) -> str:
        return (
            f"Channel: {payload.channel}\n"
            f"From: {payload.sender}\n"
            f"Subject: {payload.subject or '(no subject)'}\n"
            f"Message-ID: {payload.message_id or '(unknown)'}\n\n"
            "Email body, including any quoted thread text if present:\n"
            f"{payload.body.strip()}\n"
        )

    async def plan(self, payload: EmailChannelPayload) -> OpenWebUIReply | None:
        if settings.email_orchestrator_mode != "openwebui":
            logger.warning("EMAIL_ORCHESTRATOR_MODE=%s is not supported yet.", settings.email_orchestrator_mode)
            return None
        try:
            return await self.openwebui.generate_structured_reply(
                system_prompt=self._system_prompt(),
                user_prompt=self._user_prompt(payload),
            )
        except Exception:
            logger.exception("Email channel orchestrator failed for message_id=%s", payload.message_id)
            return None
