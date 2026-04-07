"""Auth routes: register, login, logout, password reset."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth.cookies import (
    clear_session_cookie,
    set_session_cookie,
)
from app.auth.dependencies import require_user
from app.auth.models import User
from app.auth.service import AuthService
from app.config import Settings
from app.dependencies import (
    get_auth_service,
    get_email_service,
    get_settings,
    get_templates,
)
from app.devtools.bootstrap import ensure_dev_user
from app.email.service import EmailService
from app.security import (
    RateLimitRule,
    client_ip_key,
    consume_rate_limit,
    require_csrf_form,
)
from app.url_policy import public_url

router = APIRouter(prefix="/auth", tags=["auth"])


def _normalized_email(value: str) -> str:
    return value.strip().lower()


def _consume_auth_rate_limit(
    request: Request,
    settings: Settings,
    *,
    scope: str,
    identifier: str | None = None,
    ip_limit: int = 10,
    ip_window_seconds: int = 900,
    identifier_limit: int | None = None,
    identifier_window_seconds: int = 900,
) -> bool:
    rules = [
        RateLimitRule(
            key=client_ip_key(request),
            limit=ip_limit,
            window_seconds=ip_window_seconds,
        )
    ]
    if identifier and identifier_limit is not None:
        rules.append(
            RateLimitRule(
                key=f"id:{identifier}",
                limit=identifier_limit,
                window_seconds=identifier_window_seconds,
            )
        )
    return consume_rate_limit(settings.db_path, scope, rules)


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    templates: Jinja2Templates = Depends(get_templates),
) -> HTMLResponse:
    """Render the login form."""
    return templates.TemplateResponse(
        request, "auth/login.html", {"error": None}
    )


@router.post("/login")
async def login_post(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    auth: AuthService = Depends(get_auth_service),
    templates: Jinja2Templates = Depends(get_templates),
    settings: Settings = Depends(get_settings),
    _csrf: None = Depends(require_csrf_form),
) -> RedirectResponse:
    """Handle login form submission."""
    guest_id = None
    existing_session_id = request.cookies.get("session_id")
    if existing_session_id:
        existing_actor = auth.get_actor_for_session(existing_session_id)
        if existing_actor is not None:
            guest_id = existing_actor.guest_id

    if not _consume_auth_rate_limit(
        request,
        settings,
        scope="auth_login",
        identifier=_normalized_email(email),
        ip_limit=10,
        ip_window_seconds=900,
        identifier_limit=5,
        identifier_window_seconds=900,
    ):
        response = templates.TemplateResponse(
            request,
            "auth/login.html",
            {"error": "Too many sign-in attempts. Please wait and try again."},
            status_code=429,
        )
        return response  # type: ignore[return-value]

    try:
        session = auth.login(email, password)
    except ValueError as exc:
        response = templates.TemplateResponse(
            request, "auth/login.html", {"error": str(exc)}, status_code=400
        )
        return response  # type: ignore[return-value]

    if guest_id is not None:
        assert session.user_id is not None
        auth.claim_guest_workspace(guest_id, session.user_id)
    redirect = RedirectResponse(url="/games", status_code=303)
    set_session_cookie(redirect, session.session_id, settings)
    return redirect


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------


@router.get("/register", response_class=HTMLResponse)
async def register_page(
    request: Request,
    templates: Jinja2Templates = Depends(get_templates),
) -> HTMLResponse:
    """Render the registration form."""
    return templates.TemplateResponse(
        request, "auth/register.html", {"error": None}
    )


@router.post("/register")
async def register_post(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    auth: AuthService = Depends(get_auth_service),
    email_service: EmailService = Depends(get_email_service),
    templates: Jinja2Templates = Depends(get_templates),
    settings: Settings = Depends(get_settings),
    _csrf: None = Depends(require_csrf_form),
) -> RedirectResponse:
    """Handle registration form submission."""
    if not _consume_auth_rate_limit(
        request,
        settings,
        scope="auth_register",
        identifier=_normalized_email(email),
        ip_limit=5,
        ip_window_seconds=3600,
        identifier_limit=3,
        identifier_window_seconds=3600,
    ):
        response = templates.TemplateResponse(
            request,
            "auth/register.html",
            {"error": "Too many registration attempts. Please wait and try again."},
            status_code=429,
        )
        return response  # type: ignore[return-value]

    # Capture guest session before registration replaces it
    guest_id = None
    existing_session_id = request.cookies.get("session_id")
    if existing_session_id:
        existing_actor = auth.get_actor_for_session(existing_session_id)
        if existing_actor is not None:
            guest_id = existing_actor.guest_id

    try:
        auth.register(email, password)
        session = auth.login(email, password)
    except ValueError as exc:
        response = templates.TemplateResponse(
            request, "auth/register.html", {"error": str(exc)}, status_code=400
        )
        return response  # type: ignore[return-value]

    user = auth.get_user_for_session(session.session_id)
    if user:
        auth.send_verification_email(user, email_service, settings.base_url)
    if guest_id and user:
        auth.claim_guest_workspace(guest_id, user.user_id)
    redirect = RedirectResponse(url="/auth/verify-pending", status_code=303)
    set_session_cookie(redirect, session.session_id, settings)
    return redirect


@router.get("/verify-pending", response_class=HTMLResponse)
async def verify_pending_page(
    request: Request,
    user: User = Depends(require_user),
    templates: Jinja2Templates = Depends(get_templates),
) -> HTMLResponse:
    """Render the email verification pending page."""
    if user.email_verified:
        return RedirectResponse(url="/games", status_code=303)  # type: ignore[return-value]
    return templates.TemplateResponse(request, "auth/verify_pending.html", {"user": user})


@router.get("/verify-email")
async def verify_email_get(
    token: str = "",
    auth: AuthService = Depends(get_auth_service),
) -> RedirectResponse:
    """Handle email verification link click."""
    if not token or not auth.verify_email(token):
        return RedirectResponse(
            url="/auth/verify-pending?error=invalid", status_code=303
        )
    return RedirectResponse(url="/games", status_code=303)


@router.get("/resend-verification")
async def resend_verification(
    user: User = Depends(require_user),
    auth: AuthService = Depends(get_auth_service),
    email_service: EmailService = Depends(get_email_service),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    """Resend the verification email."""
    if user.email_verified:
        return RedirectResponse(url="/games", status_code=303)
    auth.send_verification_email(user, email_service, settings.base_url)
    return RedirectResponse(url="/auth/verify-pending", status_code=303)


@router.get("/dev-login")
async def dev_login(
    settings: Settings = Depends(get_settings),
    auth_service: AuthService = Depends(get_auth_service),
) -> RedirectResponse:
    """Create a session for the local dev user when explicitly enabled."""
    if not settings.dev_auto_login:
        return RedirectResponse(url="/auth/login", status_code=303)

    user = ensure_dev_user(settings.db_path)
    session = auth_service.create_session_for_user(user.user_id)
    redirect = RedirectResponse(url="/", status_code=303)
    set_session_cookie(redirect, session.session_id, settings)
    return redirect


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


@router.post("/logout")
async def logout_post(
    request: Request,
    _user: User = Depends(require_user),
    auth: AuthService = Depends(get_auth_service),
    settings: Settings = Depends(get_settings),
    _csrf: None = Depends(require_csrf_form),
) -> RedirectResponse:
    """Clear the session cookie and redirect to login."""
    session_id = request.cookies.get("session_id")
    if session_id:
        auth.logout(session_id)

    response = RedirectResponse(url="/auth/login", status_code=303)
    clear_session_cookie(response, settings)
    return response


# ---------------------------------------------------------------------------
# Forgot password
# ---------------------------------------------------------------------------


@router.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(
    request: Request,
    sent: str = "",
    error: str = "",
    templates: Jinja2Templates = Depends(get_templates),
) -> HTMLResponse:
    """Render the forgot-password form."""
    return templates.TemplateResponse(
        request,
        "auth/forgot_password.html",
        {"sent": sent == "1", "error": error == "rate_limited"},
    )


@router.post("/forgot-password")
async def forgot_password_post(
    request: Request,
    email: str = Form(...),
    auth: AuthService = Depends(get_auth_service),
    email_service: EmailService = Depends(get_email_service),
    settings: Settings = Depends(get_settings),
    _csrf: None = Depends(require_csrf_form),
) -> RedirectResponse:
    """Handle forgot-password form submission."""
    if not _consume_auth_rate_limit(
        request,
        settings,
        scope="auth_forgot_password",
        identifier=_normalized_email(email),
        ip_limit=5,
        ip_window_seconds=3600,
        identifier_limit=3,
        identifier_window_seconds=3600,
    ):
        return RedirectResponse(
            url="/auth/forgot-password?error=rate_limited", status_code=303
        )

    auth.request_password_reset(email, email_service, settings.base_url)
    return RedirectResponse(
        url="/auth/forgot-password?sent=1", status_code=303
    )


# ---------------------------------------------------------------------------
# Reset password
# ---------------------------------------------------------------------------


@router.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page(
    request: Request,
    token: str = "",
    templates: Jinja2Templates = Depends(get_templates),
) -> HTMLResponse:
    """Render the reset-password form."""
    return templates.TemplateResponse(
        request, "auth/reset_password.html", {"token": token, "error": None}
    )


@router.post("/reset-password")
async def reset_password_post(
    request: Request,
    token: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    auth: AuthService = Depends(get_auth_service),
    templates: Jinja2Templates = Depends(get_templates),
    settings: Settings = Depends(get_settings),
    _csrf: None = Depends(require_csrf_form),
) -> RedirectResponse:
    """Handle reset-password form submission."""
    if not _consume_auth_rate_limit(
        request,
        settings,
        scope="auth_reset_password",
        ip_limit=10,
        ip_window_seconds=3600,
    ):
        response = templates.TemplateResponse(
            request,
            "auth/reset_password.html",
            {"token": token, "error": "Too many reset attempts. Please wait and try again."},
            status_code=429,
        )
        return response  # type: ignore[return-value]

    if new_password != confirm_password:
        response = templates.TemplateResponse(
            request,
            "auth/reset_password.html",
            {"token": token, "error": "Passwords do not match."},
            status_code=400,
        )
        return response  # type: ignore[return-value]

    try:
        auth.reset_password(token, new_password)
    except ValueError as exc:
        response = templates.TemplateResponse(
            request,
            "auth/reset_password.html",
            {"token": token, "error": str(exc)},
            status_code=400,
        )
        return response  # type: ignore[return-value]

    return RedirectResponse(url="/auth/login?reset=1", status_code=303)


# ---------------------------------------------------------------------------
# Google OAuth
# ---------------------------------------------------------------------------


@router.get("/google")
async def google_login(request: Request) -> RedirectResponse:
    """Redirect to Google's OAuth consent screen."""
    oauth = request.app.state.oauth
    if "google" not in oauth._clients:  # type: ignore[attr-defined]
        return RedirectResponse(
            url="/auth/login?error=google_not_configured", status_code=303
        )
    settings: Settings = request.app.state.settings
    redirect_uri = public_url(settings, "/auth/google/callback")
    return await oauth.google.authorize_redirect(request, redirect_uri)  # type: ignore[no-any-return]


@router.get("/google/callback", name="google_callback")
async def google_callback(
    request: Request,
    auth: AuthService = Depends(get_auth_service),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    """Handle the OAuth callback from Google, create or log in the user."""
    oauth = request.app.state.oauth
    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception:
        logging.getLogger(__name__).exception("Google OAuth token exchange failed")
        return RedirectResponse(
            url="/auth/login?error=google_failed", status_code=303
        )

    user_info = token.get("userinfo")
    if not user_info or not user_info.get("email"):
        return RedirectResponse(
            url="/auth/login?error=google_failed", status_code=303
        )

    google_id: str = user_info["sub"]
    email: str = user_info["email"]

    guest_id = None
    existing_session_id = request.cookies.get("session_id")
    if existing_session_id:
        existing_actor = auth.get_actor_for_session(existing_session_id)
        if existing_actor is not None:
            guest_id = existing_actor.guest_id

    user = auth.get_or_create_google_user(google_id, email)
    auth.mark_google_user_verified(user.user_id)
    session = auth.create_session_for_user(user.user_id)

    if guest_id is not None:
        auth.claim_guest_workspace(guest_id, user.user_id)

    redirect = RedirectResponse(url="/games", status_code=303)
    set_session_cookie(redirect, session.session_id, settings)
    return redirect
