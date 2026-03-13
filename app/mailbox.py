from __future__ import annotations

import email
import imaplib
from datetime import datetime, timezone

from app.config import settings
from app.models import MailboxMessage


class MailboxService:
    def fetch_unseen(self, limit: int = 20) -> list[MailboxMessage]:
        if not settings.mailbox_imap_host or not settings.mailbox_username or not settings.mailbox_password:
            return []

        messages: list[MailboxMessage] = []
        mailbox = imaplib.IMAP4_SSL(settings.mailbox_imap_host, settings.mailbox_imap_port)
        mailbox.login(settings.mailbox_username, settings.mailbox_password)
        mailbox.select(settings.mailbox_folder)
        _, data = mailbox.search(None, "UNSEEN")
        ids = list(reversed(data[0].split()))[:limit]

        for raw_id in ids:
            _, msg_data = mailbox.fetch(raw_id, "(RFC822)")
            parsed = email.message_from_bytes(msg_data[0][1])
            sender = parsed.get("From", "")
            subject = parsed.get("Subject", "")
            text = self._extract_text(parsed)
            message_id = parsed.get("Message-ID", raw_id.decode("utf-8"))
            messages.append(
                MailboxMessage(
                    message_id=message_id,
                    sender=sender,
                    subject=subject,
                    text=text,
                    received_at=datetime.now(timezone.utc),
                )
            )
        mailbox.logout()
        return messages

    def _extract_text(self, parsed: email.message.Message) -> str:
        if parsed.is_multipart():
            for part in parsed.walk():
                content_type = part.get_content_type()
                if content_type == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        return payload.decode(errors="ignore")
        payload = parsed.get_payload(decode=True)
        if isinstance(payload, bytes):
            return payload.decode(errors="ignore")
        return str(payload)
