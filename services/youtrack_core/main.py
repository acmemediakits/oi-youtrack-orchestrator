from __future__ import annotations

import os

os.environ.setdefault("SERVICE_ROLE", "tool_core")

from app.main import app  # noqa: E402
