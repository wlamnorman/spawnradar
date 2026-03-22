"""Creator signup: opted-in creator directory and outreach research."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.database import get_connection
from app.email.service import EmailMessage
from app.security import (
    RateLimitRule,
    client_ip_key,
    consume_rate_limit,
    require_csrf_form,
)

log = logging.getLogger(__name__)

router = APIRouter()

_GENRES = [
    "action", "adventure", "puzzle", "rpg", "roguelike", "horror",
    "strategy", "simulation", "platformer", "narrative", "sports",
    "racing", "fighting", "sandbox", "mmo", "indie",
]

_PITCH_OPEN_TO_OPTIONS = [
    ("strong_trailer", "Strong trailer / gameplay footage"),
    ("genre_fit", "Clear genre fit for my channel"),
    ("personal_message", "Personal connection in the message"),
    ("no_obligation", "No-obligation key offer"),
    ("prior_relationship", "Prior relationship with the developer"),
    ("interesting_concept", "Genuinely interesting concept"),
    ("demo_available", "Demo or playable build available"),
]

_CREATOR_SIGNUP_HOURLY_LIMIT = 3


def _consume_creator_signup_attempt(db_path: str, request: Request) -> bool:
    """Allow a bounded number of public creator signups per IP each hour."""
    return consume_rate_limit(
        db_path,
        "creator_signup",
        [
            RateLimitRule(
                key=client_ip_key(request),
                limit=_CREATOR_SIGNUP_HOURLY_LIMIT,
                window_seconds=3600,
            )
        ],
    )


@router.get("/creators")
async def creator_landing(request: Request) -> HTMLResponse:
    """Creator opt-in landing page with signup form and research survey."""
    session_id = request.cookies.get("session_id")
    user = None
    if session_id:
        user = request.app.state.auth_service.get_user_for_session(session_id)
    return request.app.state.templates.TemplateResponse(
        request,
        "marketing/creators.html",
        {
            "user": user,
            "genres": _GENRES,
            "pitch_open_to_options": _PITCH_OPEN_TO_OPTIONS,
        },
    )


@router.post("/creators/signup")
async def creator_signup(
    request: Request,
    display_name: Annotated[str, Form()],
    email: Annotated[str, Form()],
    youtube_handle: Annotated[str, Form()] = "",
    twitch_handle: Annotated[str, Form()] = "",
    tiktok_handle: Annotated[str, Form()] = "",
    reddit_handle: Annotated[str, Form()] = "",
    bluesky_handle: Annotated[str, Form()] = "",
    platform_pref: Annotated[str, Form()] = "any",
    audience_size: Annotated[str, Form()] = "",
    accepts_keys: Annotated[str, Form()] = "yes",
    preferred_contact: Annotated[str, Form()] = "email",
    lead_time_pref: Annotated[str, Form()] = "no_pref",
    pitch_first_check: Annotated[str, Form()] = "",
    pitch_delete_why: Annotated[str, Form()] = "",
    contact_timing: Annotated[str, Form()] = "no_pref",
    creator_notes: Annotated[str, Form()] = "",
    company: Annotated[str, Form()] = "",
    _csrf: None = Depends(require_csrf_form),
) -> RedirectResponse:
    """Handle creator signup form submission."""
    if company.strip():
        log.info("Discarded creator signup with honeypot field populated")
        return RedirectResponse(url="/creators/thanks", status_code=303)

    settings = request.app.state.settings
    if not _consume_creator_signup_attempt(settings.db_path, request):
        log.warning("Rate-limited creator signup attempt")
        return RedirectResponse(url="/creators/thanks", status_code=303)

    form_data = await request.form()
    genre_interests = json.dumps(form_data.getlist("genre_interests"))
    pitch_open_to = json.dumps(form_data.getlist("pitch_open_to"))

    creator_id = str(uuid.uuid4())

    try:
        with get_connection(settings.db_path) as conn:
            conn.execute(
                """
                INSERT INTO creator_signups (
                    creator_id, display_name, email,
                    youtube_handle, twitch_handle, tiktok_handle,
                    reddit_handle, bluesky_handle,
                    genre_interests, platform_pref, audience_size,
                    accepts_keys, preferred_contact, lead_time_pref,
                    pitch_first_check, pitch_delete_why,
                    pitch_open_to, contact_timing, creator_notes
                ) VALUES (
                    ?, ?, ?,
                    ?, ?, ?,
                    ?, ?,
                    ?, ?, ?,
                    ?, ?, ?,
                    ?, ?,
                    ?, ?, ?
                )
                """,
                (
                    creator_id, display_name.strip(), email.strip().lower(),
                    youtube_handle.strip() or None,
                    twitch_handle.strip() or None,
                    tiktok_handle.strip() or None,
                    reddit_handle.strip() or None,
                    bluesky_handle.strip() or None,
                    genre_interests, platform_pref, audience_size or None,
                    accepts_keys, preferred_contact, lead_time_pref,
                    pitch_first_check.strip() or None,
                    pitch_delete_why.strip() or None,
                    pitch_open_to, contact_timing,
                    creator_notes.strip() or None,
                ),
            )
    except Exception as exc:
        # Duplicate email — redirect back with error flag
        if "UNIQUE" in str(exc):
            return RedirectResponse(
                url="/creators?error=already_registered", status_code=303
            )
        log.exception("Creator signup failed: %s", exc)
        return RedirectResponse(url="/creators?error=server", status_code=303)

    # Send confirmation email (best effort)
    try:
        body = (
            f"Hi {display_name},\n\n"
            "You're now listed in the SpawnRadar creator directory. "
            "Indie developers whose games match your stated genre interests "
            "will be able to reach out to you through the platform.\n\n"
            "We'll only connect you with games that fit what you cover. "
            "If you ever want to update your preferences, reply to this email.\n\n"
            "— The SpawnRadar team\nhttps://spawnradar.com\n"
        )
        request.app.state.email_service.send(
            EmailMessage(
                to=email.strip(),
                subject="You're on the SpawnRadar creator list",
                html=body.replace("\n", "<br>"),
                text=body,
            )
        )
    except Exception:
        log.warning("Creator confirmation email failed for %s", email)

    return RedirectResponse(url="/creators/thanks", status_code=303)


@router.get("/creators/thanks")
async def creator_thanks(request: Request) -> HTMLResponse:
    """Post-signup thank-you page."""
    session_id = request.cookies.get("session_id")
    user = None
    if session_id:
        user = request.app.state.auth_service.get_user_for_session(session_id)
    return request.app.state.templates.TemplateResponse(
        request,
        "marketing/creators_thanks.html",
        {"user": user},
    )
