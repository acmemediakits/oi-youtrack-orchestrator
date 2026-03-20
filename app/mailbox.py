from __future__ import annotations

import email
import imaplib
import logging
import socket
import smtplib
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import parseaddr

from app.config import settings
from app.models import MailboxMessage

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class MailboxService:
    runtime_config: any = None

    def _runtime(self):
        if self.runtime_config:
            return self.runtime_config.get()
        from app.models import RuntimeConfig, RuntimeMailboxFolders

        return RuntimeConfig(
            verbose=settings.verbose,
            mailbox_poll_interval_seconds=settings.mailbox_poll_interval_seconds,
            mailbox_allowed_sender_domains=list(settings.mailbox_allowed_sender_domains),
            mailbox_folders=RuntimeMailboxFolders(
                inbox=settings.mailbox_folder,
                processing=settings.mailbox_processing_folder,
                processed=settings.mailbox_processed_folder,
                failed=settings.mailbox_failed_folder,
                rejected=settings.mailbox_rejected_folder,
            ),
        )

    def _connect_imap(self):
        context = settings.build_imap_ssl_context()
        if settings.mailbox_imap_tls_mode == "starttls":
            logger.info(
                "Opening IMAP connection with STARTTLS host=%s port=%s",
                settings.mailbox_imap_host,
                settings.mailbox_imap_port,
            )
            mailbox = imaplib.IMAP4(settings.mailbox_imap_host, settings.mailbox_imap_port)
            mailbox.starttls(ssl_context=context)
            logger.info("IMAP STARTTLS negotiation completed.")
            return mailbox

        logger.info(
            "Opening IMAP implicit SSL connection host=%s port=%s legacy_tls=%s",
            settings.mailbox_imap_host,
            settings.mailbox_imap_port,
            settings.mailbox_imap_allow_legacy_tls,
        )
        mailbox = imaplib.IMAP4_SSL(
            settings.mailbox_imap_host,
            settings.mailbox_imap_port,
            ssl_context=context,
        )
        logger.info("IMAP SSL connection established.")
        return mailbox

    def fetch_unseen(self, limit: int = 20) -> list[MailboxMessage]:
        if not settings.mailbox_imap_host or not settings.mailbox_username or not settings.mailbox_password:
            logger.info("Mailbox polling skipped: IMAP configuration is incomplete.")
            return []

        runtime = self._runtime()
        messages: list[MailboxMessage] = []
        socket.setdefaulttimeout(settings.mailbox_imap_timeout_seconds)
        logger.info(
            "Connecting to IMAP host=%s port=%s folder=%s",
            settings.mailbox_imap_host,
            settings.mailbox_imap_port,
            runtime.mailbox_folders.inbox,
        )
        mailbox = None
        try:
            mailbox = self._connect_imap()
            mailbox.login(settings.mailbox_username, settings.mailbox_password)
            logger.info("IMAP login succeeded for user=%s", settings.mailbox_username)
            self._ensure_folders(mailbox)
            status, _ = mailbox.select(runtime.mailbox_folders.inbox)
            logger.info("IMAP folder selected: folder=%s status=%s", runtime.mailbox_folders.inbox, status)
            status, data = mailbox.search(None, "UNSEEN")
            if status != "OK":
                logger.warning("IMAP search returned non-OK status=%s", status)
                ids = []
            else:
                ids = list(reversed(data[0].split()))[:limit]
            logger.info("Fetched %s unseen email(s) from mailbox.", len(ids))

            for raw_id in ids:
                logger.info("Fetching IMAP message uid=%s", raw_id.decode("utf-8"))
                fetch_status, msg_data = mailbox.fetch(raw_id, "(BODY.PEEK[])")
                if fetch_status != "OK":
                    logger.warning("Failed to fetch IMAP message uid=%s status=%s", raw_id.decode("utf-8"), fetch_status)
                    continue
                parsed = email.message_from_bytes(msg_data[0][1])
                sender = parsed.get("From", "")
                subject = parsed.get("Subject", "")
                text = self._extract_text(parsed)
                message_id = parsed.get("Message-ID", raw_id.decode("utf-8"))
                messages.append(
                    MailboxMessage(
                        message_id=message_id,
                        mailbox_uid=raw_id.decode("utf-8"),
                        sender=sender,
                        subject=subject,
                        text=text,
                        received_at=datetime.now(timezone.utc),
                    )
                )
                logger.info("Loaded email uid=%s message_id=%s sender=%s", raw_id.decode("utf-8"), message_id, sender)
        finally:
            if mailbox is not None:
                try:
                    mailbox.logout()
                    logger.info("IMAP logout completed.")
                except Exception:
                    logger.warning("IMAP logout failed.", exc_info=settings.verbose)
        return messages

    def move_message(self, mailbox_uid: str, target_folder: str) -> None:
        if not settings.mailbox_imap_host or not settings.mailbox_username or not settings.mailbox_password:
            return
        runtime = self._runtime()
        socket.setdefaulttimeout(settings.mailbox_imap_timeout_seconds)
        mailbox = self._connect_imap()
        try:
            mailbox.login(settings.mailbox_username, settings.mailbox_password)
            self._ensure_folders(mailbox)
            mailbox.select(runtime.mailbox_folders.inbox)
            logger.info("Moving email uid=%s from %s to %s", mailbox_uid, runtime.mailbox_folders.inbox, target_folder)
            move_status = "NO"
            move_data = None
            if "MOVE" in self._capabilities(mailbox):
                move_status, move_data = mailbox.uid("MOVE", mailbox_uid, target_folder)
            if move_status != "OK":
                logger.info("IMAP MOVE unavailable or failed for uid=%s, using COPY+DELETE fallback.", mailbox_uid)
                copy_status, copy_data = mailbox.uid("COPY", mailbox_uid, target_folder)
                if copy_status != "OK":
                    raise RuntimeError(f"IMAP COPY failed for uid={mailbox_uid}: {copy_data}")
                store_status, store_data = mailbox.uid("STORE", mailbox_uid, "+FLAGS", "(\\Deleted)")
                if store_status != "OK":
                    raise RuntimeError(f"IMAP STORE delete flag failed for uid={mailbox_uid}: {store_data}")
                expunge_status, expunge_data = mailbox.expunge()
                if expunge_status != "OK":
                    raise RuntimeError(f"IMAP EXPUNGE failed for uid={mailbox_uid}: {expunge_data}")
            logger.info("Moved email uid=%s to folder=%s", mailbox_uid, target_folder)
        finally:
            try:
                mailbox.logout()
            except Exception:
                logger.warning("IMAP logout failed after move.", exc_info=settings.verbose)

    def mark_seen(self, mailbox_uid: str) -> None:
        if not settings.mailbox_imap_host or not settings.mailbox_username or not settings.mailbox_password:
            return
        runtime = self._runtime()
        socket.setdefaulttimeout(settings.mailbox_imap_timeout_seconds)
        mailbox = self._connect_imap()
        mailbox.login(settings.mailbox_username, settings.mailbox_password)
        mailbox.select(runtime.mailbox_folders.inbox)
        mailbox.store(mailbox_uid, "+FLAGS", "\\Seen")
        mailbox.logout()
        logger.info("Marked email uid=%s as seen.", mailbox_uid)

    def ensure_runtime_folders(self) -> None:
        if not settings.mailbox_imap_host or not settings.mailbox_username or not settings.mailbox_password:
            logger.info("IMAP folder bootstrap skipped: IMAP configuration is incomplete.")
            return
        runtime = self._runtime()
        socket.setdefaulttimeout(settings.mailbox_imap_timeout_seconds)
        mailbox = None
        logger.info(
            "Ensuring IMAP runtime folders exist for inbox=%s processing=%s processed=%s failed=%s rejected=%s",
            runtime.mailbox_folders.inbox,
            runtime.mailbox_folders.processing,
            runtime.mailbox_folders.processed,
            runtime.mailbox_folders.failed,
            runtime.mailbox_folders.rejected,
        )
        try:
            mailbox = self._connect_imap()
            mailbox.login(settings.mailbox_username, settings.mailbox_password)
            self._ensure_folders(mailbox)
            logger.info("IMAP folder bootstrap completed successfully.")
        finally:
            if mailbox is not None:
                try:
                    mailbox.logout()
                except Exception:
                    logger.warning("IMAP logout failed after folder bootstrap.", exc_info=settings.verbose)

    def sender_domain(self, sender: str) -> str | None:
        _, email_address = parseaddr(sender)
        if "@" not in email_address:
            return None
        return email_address.rsplit("@", 1)[1].lower()

    def send_reply(self, original: MailboxMessage, body: str) -> None:
        _, recipient = parseaddr(original.sender)
        if not recipient:
            logger.warning("SMTP reply skipped for message_id=%s because recipient is invalid.", original.message_id)
            return
        self.send_message(
            recipient,
            f"Re: {original.subject}" if original.subject else "Re: richiesta",
            body,
        )
        logger.info("SMTP reply sent to=%s for message_id=%s", recipient, original.message_id)

    def send_message(self, recipient: str, subject: str, body: str) -> None:
        if not settings.mailbox_smtp_host or not settings.mailbox_username or not settings.mailbox_password:
            logger.warning("SMTP send skipped for recipient=%s because SMTP configuration is incomplete.", recipient)
            return
        message = EmailMessage()
        message["From"] = settings.mailbox_username
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body)

        protocol = settings.mailbox_smtp_protocol.upper()
        logger.info(
            "Sending SMTP message to=%s subject=%s host=%s port=%s protocol=%s",
            recipient,
            message["Subject"],
            settings.mailbox_smtp_host,
            settings.mailbox_smtp_port,
            protocol,
        )
        if protocol == "SSL":
            with smtplib.SMTP_SSL(
                settings.mailbox_smtp_host,
                settings.mailbox_smtp_port,
                timeout=settings.mailbox_smtp_timeout_seconds,
            ) as smtp:
                smtp.login(settings.mailbox_username, settings.mailbox_password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(
                settings.mailbox_smtp_host,
                settings.mailbox_smtp_port,
                timeout=settings.mailbox_smtp_timeout_seconds,
            ) as smtp:
                if protocol == "TLS":
                    smtp.starttls()
                smtp.login(settings.mailbox_username, settings.mailbox_password)
                smtp.send_message(message)
        logger.info("SMTP message sent to=%s subject=%s", recipient, subject)

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

    def _ensure_folders(self, mailbox) -> None:
        runtime = self._runtime()
        for folder in (
            runtime.mailbox_folders.inbox,
            runtime.mailbox_folders.processing,
            runtime.mailbox_folders.processed,
            runtime.mailbox_folders.failed,
            runtime.mailbox_folders.rejected,
        ):
            create_status, create_data = mailbox.create(folder)
            response_text = " ".join(self._decode_imap_line(item) for item in (create_data or []))
            already_exists = "ALREADYEXISTS" in response_text.upper()
            if create_status == "OK":
                logger.info("IMAP created folder=%s", folder)
                self._subscribe_folder(mailbox, folder)
            elif create_status == "NO" and already_exists:
                logger.info("IMAP folder already exists folder=%s", folder)
                self._subscribe_folder(mailbox, folder)
            elif create_status == "NO":
                logger.error("IMAP could not create folder=%s response=%s", folder, create_data)
            else:
                logger.warning("Unexpected IMAP CREATE status for folder=%s status=%s response=%s", folder, create_status, create_data)

    def _subscribe_folder(self, mailbox, folder: str) -> None:
        status, data = mailbox.subscribe(folder)
        if status == "OK":
            logger.debug("IMAP subscribed folder=%s", folder)
        elif status == "NO":
            logger.warning("IMAP subscribe rejected for folder=%s response=%s", folder, data)
        else:
            logger.warning("Unexpected IMAP SUBSCRIBE status for folder=%s status=%s response=%s", folder, status, data)

    def _capabilities(self, mailbox) -> set[str]:
        caps = getattr(mailbox, "capabilities", ()) or ()
        normalized = set()
        for item in caps:
            if isinstance(item, bytes):
                normalized.add(item.decode("utf-8", errors="ignore").upper())
            else:
                normalized.add(str(item).upper())
        return normalized

    def _decode_imap_line(self, value) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="ignore")
        return str(value)
