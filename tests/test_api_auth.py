from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.config import settings
from app.main import TRUSTED_ASSISTANT_ACTOR_ID, _resolve_actor
from app.models import UserType, WhitelistedUser


class ResolveActorTests(unittest.TestCase):
    def test_missing_actor_header_uses_trusted_openwebui_actor(self):
        previous_enabled = settings.openwebui_trusted_channel_enabled
        previous_email = settings.openwebui_trusted_actor_email
        previous_name = settings.openwebui_trusted_actor_name
        previous_role = settings.openwebui_trusted_actor_role
        settings.openwebui_trusted_channel_enabled = True
        settings.openwebui_trusted_actor_email = "ytbot@local"
        settings.openwebui_trusted_actor_name = "YTbot"
        settings.openwebui_trusted_actor_role = UserType.power
        try:
            actor = _resolve_actor(None)
            self.assertEqual(actor.id, TRUSTED_ASSISTANT_ACTOR_ID)
            self.assertEqual(actor.email, "ytbot@local")
            self.assertEqual(actor.full_name, "YTbot")
            self.assertEqual(actor.user_type, UserType.power)
            self.assertTrue(actor.active)
        finally:
            settings.openwebui_trusted_channel_enabled = previous_enabled
            settings.openwebui_trusted_actor_email = previous_email
            settings.openwebui_trusted_actor_name = previous_name
            settings.openwebui_trusted_actor_role = previous_role

    def test_missing_actor_header_still_fails_when_trusted_channel_disabled(self):
        previous_enabled = settings.openwebui_trusted_channel_enabled
        settings.openwebui_trusted_channel_enabled = False
        try:
            with self.assertRaises(HTTPException) as ctx:
                _resolve_actor(None)
            self.assertEqual(ctx.exception.status_code, 401)
            self.assertIn("X-Actor-Email", ctx.exception.detail)
        finally:
            settings.openwebui_trusted_channel_enabled = previous_enabled

    def test_explicit_actor_header_still_uses_whitelist_flow(self):
        whitelisted_user = WhitelistedUser(
            full_name="Daiana Test",
            email="daiana@example.com",
            user_type=UserType.team,
            active=True,
        )
        with patch("app.main.get_user_directory_service") as get_directory, patch("app.main.get_permission_service") as get_permissions:
            get_directory.return_value.resolve.return_value = whitelisted_user
            get_permissions.return_value.ensure_active_user.return_value = whitelisted_user
            actor = _resolve_actor("daiana@example.com")
        self.assertEqual(actor.email, "daiana@example.com")
        self.assertEqual(actor.user_type, UserType.team)

