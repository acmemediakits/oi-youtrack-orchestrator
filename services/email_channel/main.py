from __future__ import annotations

import os

os.environ.setdefault("SERVICE_ROLE", "email_channel")

from app.email_channel_api import app  # noqa: E402
