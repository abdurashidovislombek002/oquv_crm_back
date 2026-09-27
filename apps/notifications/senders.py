"""Pluggable senders (SMS / Telegram / e-mail).

Real providers are configured through environment variables. When a provider is
not configured the sender logs the message instead of failing hard, which keeps
local development and tests working.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from django.conf import settings
from django.core.mail import EmailMultiAlternatives

logger = logging.getLogger(__name__)


class BaseSender:
    channel = ""
    timeout = 10

    def __init__(self, **options: Any) -> None:
        self.options = options

    @property
    def is_configured(self) -> bool:
        raise NotImplementedError

    def send(self, address: str, subject: str, body: str) -> str:
        """Returns a provider message id (or a synthetic one when logging)."""
        if not address:
            raise ValueError("Yetkazish manzili (telefon/email) bo'sh.")
        if not self.is_configured:
            logger.info(
                "[%s] provider sozlanmagan — xabar logga yozildi: %s | %s",
                self.channel.upper(), address, body,
            )
            return f"log-{self.channel}"
        return self._deliver(address, subject, body)

    def _deliver(self, address: str, subject: str, body: str) -> str:  # pragma: no cover - network
        raise NotImplementedError


class SmsSender(BaseSender):
    """Generic HTTP SMS gateway (esms.uz / onlinesms.uz compatible)."""

    channel = "sms"

    @property
    def is_configured(self) -> bool:
        return bool(getattr(settings, "ESMS_API_URL", "") and getattr(settings, "ESMS_API_TOKEN", ""))

    def _deliver(self, address: str, subject: str, body: str) -> str:
        payload = json.dumps({"phone": address, "message": body}).encode("utf-8")
        request = urllib.request.Request(
            self.options.get("url", settings.ESMS_API_URL),
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {settings.ESMS_API_TOKEN}",
            },
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            content = response.read().decode("utf-8", errors="ignore")
        try:
            return str(json.loads(content).get("id", "sms-ok"))
        except json.JSONDecodeError:
            return "sms-ok"


class TelegramSender(BaseSender):
    """Telegram bot API ``sendMessage``."""

    channel = "telegram"
    api_url = "https://api.telegram.org/bot{token}/sendMessage"

    @property
    def is_configured(self) -> bool:
        return bool(getattr(settings, "TELEGRAM_BOT_TOKEN", ""))

    def _deliver(self, address: str, subject: str, body: str) -> str:
        token = settings.TELEGRAM_BOT_TOKEN
        payload = json.dumps(
            {
                "chat_id": address or settings.TELEGRAM_BOT_CHAT_ID,
                "text": f"{subject}\n{body}".strip() if subject else body,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            self.api_url.format(token=token),
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            content = response.read().decode("utf-8", errors="ignore")
        try:
            return str(json.loads(content)["result"]["message_id"])
        except (json.JSONDecodeError, KeyError):
            return "telegram-ok"


class EmailSender(BaseSender):
    """Django e-mail backend (console in dev, SMTP in production)."""

    channel = "email"

    @property
    def is_configured(self) -> bool:
        return bool(getattr(settings, "DEFAULT_FROM_EMAIL", ""))

    def _deliver(self, address: str, subject: str, body: str) -> str:
        message = EmailMultiAlternatives(
            subject=subject or "CRM bildirishnoma",
            body=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[address],
        )
        message.send(fail_silently=False)
        return f"email-{address}"


class InAppSender(BaseSender):
    """Stored in the database only (visible in the app)."""

    channel = "in_app"

    @property
    def is_configured(self) -> bool:
        return True

    def _deliver(self, address: str, subject: str, body: str) -> str:
        return "in-app"


SENDERS: Dict[str, BaseSender] = {
    SmsSender.channel: SmsSender(),
    TelegramSender.channel: TelegramSender(),
    EmailSender.channel: EmailSender(),
    InAppSender.channel: InAppSender(),
}


def get_sender(channel: str) -> BaseSender:
    sender = SENDERS.get(channel)
    if sender is None:
        raise ValueError(f"Noma'lum kanal: {channel}")
    return sender
