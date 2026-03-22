"""Shared security helpers for configuration, CSRF, and rate limiting."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Form, HTTPException, Request

from app.database import get_connection


@dataclass(frozen=True)
class RateLimitRule:
    """A coarse request-rate rule for a hashed key over a time window."""

    key: str
    limit: int
    window_seconds: int


def client_ip(request: Request) -> str:
    """Return the best-effort client IP, honoring a single forwarded value."""
    forwarded = request.headers.get("x-forwarded-for", "")
    ip_address = forwarded.split(",", 1)[0].strip() if forwarded else ""
    if not ip_address and request.client is not None:
        ip_address = request.client.host
    return ip_address or "unknown"


def client_ip_key(request: Request) -> str:
    """Build a stable rate-limit key for the request IP without exposing it."""
    return f"ip:{client_ip(request)}"


def csrf_token_for(request: Request) -> str:
    """Return a per-session CSRF token, creating one if it does not exist yet."""
    token = request.session.get("csrf_token")
    if not isinstance(token, str) or not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


def validate_csrf(request: Request, provided_token: str | None) -> None:
    """Reject requests whose CSRF token does not match the session token."""
    expected_token = csrf_token_for(request)
    if not provided_token or not secrets.compare_digest(provided_token, expected_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token.")


def require_csrf_form(
    request: Request, csrf_token: Annotated[str, Form()]
) -> None:
    """Protect browser form posts with a hidden CSRF token."""
    validate_csrf(request, csrf_token)


def require_csrf_header(request: Request) -> None:
    """Protect JS-issued mutating requests with an X-CSRF-Token header."""
    validate_csrf(request, request.headers.get("x-csrf-token"))


def consume_rate_limit(
    db_path: str, scope: str, rules: list[RateLimitRule]
) -> bool:
    """Record a request if every supplied rule remains under its limit."""
    if not rules:
        return True

    hashed_rules = [
        (
            hashlib.sha256(f"{scope}:{rule.key}".encode()).hexdigest(),
            rule.limit,
            rule.window_seconds,
        )
        for rule in rules
    ]

    with get_connection(db_path) as conn:
        conn.execute(
            """
            DELETE FROM request_rate_limits
            WHERE created_at < datetime('now', '-7 days')
            """
        )

        for key_hash, limit, window_seconds in hashed_rules:
            row = conn.execute(
                """
                SELECT COUNT(*) AS attempt_count
                FROM request_rate_limits
                WHERE scope = ?
                  AND key_hash = ?
                  AND created_at >= datetime('now', ?)
                """,
                (scope, key_hash, f"-{window_seconds} seconds"),
            ).fetchone()
            attempt_count = int(row["attempt_count"]) if row is not None else 0
            if attempt_count >= limit:
                return False

        for key_hash, _, _ in hashed_rules:
            conn.execute(
                """
                INSERT INTO request_rate_limits (event_id, scope, key_hash)
                VALUES (?, ?, ?)
                """,
                (str(uuid.uuid4()), scope, key_hash),
            )

    return True
