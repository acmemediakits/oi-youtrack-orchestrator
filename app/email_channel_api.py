from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.dependencies import get_mail_automation_runner, get_mail_automation_service, get_mailbox_service
from app.logging_utils import setup_logging

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    runner = get_mail_automation_runner()
    try:
        get_mailbox_service().ensure_runtime_folders()
    except Exception:
        logger.exception("IMAP folder bootstrap failed during email-channel startup.")
    if settings.run_mail_worker:
        runner.start()
    try:
        yield
    finally:
        await runner.stop()


app = FastAPI(
    title="Email Channel Adapter",
    version="0.1.0",
    description="Channel adapter that normalizes mailbox traffic and delegates orchestration to OpenWebUI.",
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "email-channel",
        "state_backend": settings.state_backend,
        "orchestrator_mode": settings.email_orchestrator_mode,
    }


@app.post("/run-once")
async def run_once() -> dict[str, object]:
    records = await get_mail_automation_service().run_once()
    return {
        "processed": len(records),
        "statuses": [record.status for record in records],
        "message_ids": [record.message_id for record in records],
    }
