"""Public URL and host policy helpers."""

from __future__ import annotations

from fastapi import Request

from app.config import Settings


def public_url(settings: Settings, path: str) -> str:
    """Build an absolute public URL rooted at the configured base URL."""
    normalized_path = path if path.startswith("/") else f"/{path}"
    return f"{settings.base_origin}{normalized_path}"


def canonical_request_url(request: Request) -> str:
    """Return the canonical public URL for the current request."""
    settings: Settings = request.app.state.settings
    query = f"?{request.url.query}" if request.url.query else ""
    return f"{public_url(settings, request.url.path or '/')}{query}"


def should_redirect_to_canonical_host(
    request: Request, settings: Settings
) -> bool:
    """Return whether the request host should be normalized to BASE_URL."""
    redirect_host = settings.www_redirect_hostname
    return bool(redirect_host and request.url.hostname == redirect_host)
