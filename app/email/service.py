"""Transactional email delivery via Resend.

Configure via environment variables:
  RESEND_API_KEY      - Resend API key
  EMAIL_FROM          - sender address, default DEFAULT_FROM_ADDRESS
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_FROM_ADDRESS = "noreply@spawnradar.com"


@dataclass
class EmailMessage:
    to: str
    subject: str
    html: str
    text: str = ""


class EmailService:
    """Send transactional emails via Resend or log them in development."""

    def __init__(
        self,
        resend_api_key: str = "",
        from_address: str = DEFAULT_FROM_ADDRESS,
    ) -> None:
        self._resend_key = resend_api_key
        self._from = from_address

    @property
    def is_configured(self) -> bool:
        return bool(self._resend_key)

    def send(self, message: EmailMessage) -> None:
        """Send an email. Falls back to stdout if unconfigured."""
        if self._resend_key:
            self._send_resend(message)
        else:
            self._log(message)

    def _send_resend(self, message: EmailMessage) -> None:
        import resend  # type: ignore

        resend.api_key = self._resend_key
        resend.Emails.send(
            {
                "from": self._from,
                "to": message.to,
                "subject": message.subject,
                "html": message.html,
            }
        )

    def _log(self, message: EmailMessage) -> None:
        print(f"[EMAIL] To: {message.to} | Subject: {message.subject}")
        print(message.text or "[html only]")
