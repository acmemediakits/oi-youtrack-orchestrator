from __future__ import annotations

import logging
from collections import deque
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.config import settings

_RECENT_LOGS: deque[str] = deque(maxlen=400)
_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


class RecentLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            _RECENT_LOGS.append(self.format(record))
        except Exception:
            self.handleError(record)


def _handler_present(root: logging.Logger, handler_type: type[logging.Handler], *, name: str) -> bool:
    for handler in root.handlers:
        if isinstance(handler, handler_type) and getattr(handler, "name", "") == name:
            return True
    return False


def setup_logging() -> Path:
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if settings.verbose else logging.INFO)

    formatter = logging.Formatter(_FORMAT)
    log_path = Path(settings.data_dir) / "app.log"

    if not _handler_present(root, logging.StreamHandler, name="console"):
        console_handler = logging.StreamHandler()
        console_handler.name = "console"
        console_handler.setFormatter(formatter)
        root.addHandler(console_handler)

    if not _handler_present(root, RotatingFileHandler, name="panel_file"):
        file_handler = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        file_handler.name = "panel_file"
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    if not _handler_present(root, RecentLogHandler, name="recent_buffer"):
        recent_handler = RecentLogHandler()
        recent_handler.name = "recent_buffer"
        recent_handler.setFormatter(formatter)
        root.addHandler(recent_handler)

    return log_path


def get_recent_logs(limit: int = 200) -> list[str]:
    if limit <= 0:
        return []
    return list(_RECENT_LOGS)[-limit:]


def get_log_file_path() -> Path:
    return Path(settings.data_dir) / "app.log"
