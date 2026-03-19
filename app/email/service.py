"""Email sending service with Resend as primary and SMTP as fallback.

Configure via environment variables:
  RESEND_API_KEY      — use Resend (preferred)
  SMTP_HOST           — use SMTP (fallback)
  SMTP_PORT           — default 587
  SMTP_USER
  SMTP_PASSWORD
  EMAIL_FROM          — sender address, default noreply@spawnradar.app
"""
from __future__ import annotations

import smtplib
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


@dataclass
class EmailMessage:
    to: str
    subject: str
    html: str
    text: str = ""


class EmailService:
    """Send transactional emails via Resend or SMTP.

    If neither is configured, logs to stdout (useful in dev).
    """

    def __init__(
        self,
        resend_api_key: str = "",
        smtp_host: str = "",
        smtp_port: int = 587,
        smtp_user: str = "",
        smtp_password: str = "",
        from_address: str = "noreply@spawnradar.app",
    ) -> None:
        self._resend_key = resend_api_key
        self._smtp_host = smtp_host
        self._smtp_port = smtp_port
        self._smtp_user = smtp_user
        self._smtp_password = smtp_password
        self._from = from_address

    @property
    def is_configured(self) -> bool:
        return bool(self._resend_key or self._smtp_host)

    def send(self, message: EmailMessage) -> None:
        """Send an email. Falls back to stdout if unconfigured."""
        if self._resend_key:
            self._send_resend(message)
        elif self._smtp_host:
            self._send_smtp(message)
        else:
            self._log(message)

    def _send_resend(self, message: EmailMessage) -> None:
        import resend  # type: ignore
        resend.api_key = self._resend_key
        resend.Emails.send({
            "from": self._from,
            "to": message.to,
            "subject": message.subject,
            "html": message.html,
        })

    def _send_smtp(self, message: EmailMessage) -> None:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = message.subject
        msg["From"] = self._from
        msg["To"] = message.to
        if message.text:
            msg.attach(MIMEText(message.text, "plain"))
        msg.attach(MIMEText(message.html, "html"))
        with smtplib.SMTP(self._smtp_host, self._smtp_port) as server:
            server.ehlo()
            server.starttls()
            if self._smtp_user:
                server.login(self._smtp_user, self._smtp_password)
            server.sendmail(self._from, message.to, msg.as_string())

    def _log(self, message: EmailMessage) -> None:
        print(f"[EMAIL] To: {message.to} | Subject: {message.subject}")
        print(message.text or "[html only]")
