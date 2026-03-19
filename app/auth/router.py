"""Auth routes: register, login, logout, password reset."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth.dependencies import require_user
from app.auth.models import User
from app.auth.service import AuthService
from app.devtools.bootstrap import ensure_dev_user

router = APIRouter(prefix="/auth", tags=["auth"])


def _templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


def _auth_service(request: Request) -> AuthService:
    return request.app.state.auth_service


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    """Render the login form."""
    tpl = _templates(request)
    return tpl.TemplateResponse(request, "auth/login.html", {"error": None})


@router.post("/login")
async def login_post(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
) -> RedirectResponse:
    """Handle login form submission."""
    auth = _auth_service(request)
    tpl = _templates(request)
    try:
        session = auth.login(email, password)
    except ValueError as exc:
        response = tpl.TemplateResponse(
            request, "auth/login.html", {"error": str(exc)}, status_code=400
        )
        return response  # type: ignore[return-value]

    redirect = RedirectResponse(url="/games", status_code=303)
    redirect.set_cookie(
        "session_id",
        session.session_id,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
    )
    return redirect


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request) -> HTMLResponse:
    """Render the registration form."""
    tpl = _templates(request)
    return tpl.TemplateResponse(request, "auth/register.html", {"error": None})


@router.post("/register")
async def register_post(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
) -> RedirectResponse:
    """Handle registration form submission."""
    auth = _auth_service(request)
    tpl = _templates(request)
    try:
        auth.register(email, password)
        session = auth.login(email, password)
    except ValueError as exc:
        response = tpl.TemplateResponse(
            request, "auth/register.html", {"error": str(exc)}, status_code=400
        )
        return response  # type: ignore[return-value]

    redirect = RedirectResponse(url="/games", status_code=303)
    redirect.set_cookie(
        "session_id",
        session.session_id,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
    )
    return redirect


@router.get("/dev-login")
async def dev_login(request: Request) -> RedirectResponse:
    """Create a session for the local dev user when explicitly enabled."""
    settings = request.app.state.settings
    if not settings.dev_auto_login:
        return RedirectResponse(url="/auth/login", status_code=303)

    user = ensure_dev_user(settings.db_path)
    session = _auth_service(request).create_session_for_user(user.user_id)
    redirect = RedirectResponse(url="/", status_code=303)
    redirect.set_cookie(
        "session_id",
        session.session_id,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
    )
    return redirect


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


@router.post("/logout")
async def logout_post(
    request: Request,
    user: User = Depends(require_user),
) -> RedirectResponse:
    """Clear the session cookie and redirect to login."""
    auth = _auth_service(request)
    session_id = request.cookies.get("session_id")
    if session_id:
        auth.logout(session_id)

    response = RedirectResponse(url="/auth/login", status_code=303)
    response.delete_cookie("session_id")
    return response


# ---------------------------------------------------------------------------
# Forgot password
# ---------------------------------------------------------------------------


@router.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(
    request: Request, sent: str = ""
) -> HTMLResponse:
    """Render the forgot-password form."""
    tpl = _templates(request)
    return tpl.TemplateResponse(
        request, "auth/forgot_password.html", {"sent": sent == "1"}
    )


@router.post("/forgot-password")
async def forgot_password_post(
    request: Request,
    email: str = Form(...),
) -> RedirectResponse:
    """Handle forgot-password form submission."""
    auth = _auth_service(request)
    email_service = request.app.state.email_service
    base_url: str = request.app.state.settings.base_url
    auth.request_password_reset(email, email_service, base_url)
    return RedirectResponse(
        url="/auth/forgot-password?sent=1", status_code=303
    )


# ---------------------------------------------------------------------------
# Reset password
# ---------------------------------------------------------------------------


@router.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page(
    request: Request, token: str = ""
) -> HTMLResponse:
    """Render the reset-password form."""
    tpl = _templates(request)
    return tpl.TemplateResponse(
        request, "auth/reset_password.html", {"token": token, "error": None}
    )


@router.post("/reset-password")
async def reset_password_post(
    request: Request,
    token: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
) -> RedirectResponse:
    """Handle reset-password form submission."""
    auth = _auth_service(request)
    tpl = _templates(request)

    if new_password != confirm_password:
        response = tpl.TemplateResponse(
            request,
            "auth/reset_password.html",
            {"token": token, "error": "Passwords do not match."},
            status_code=400,
        )
        return response  # type: ignore[return-value]

    try:
        auth.reset_password(token, new_password)
    except ValueError as exc:
        response = tpl.TemplateResponse(
            request,
            "auth/reset_password.html",
            {"token": token, "error": str(exc)},
            status_code=400,
        )
        return response  # type: ignore[return-value]

    return RedirectResponse(url="/auth/login?reset=1", status_code=303)
