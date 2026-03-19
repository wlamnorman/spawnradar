"""Routes for the review queue and draft item actions."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.auth.dependencies import require_user
from app.auth.models import User
from app.games.repository import GameRepository
from app.ingestion.constants import RECENT_VIDEO_THUMBNAIL_LIMIT
from app.prospects.service import ProspectService

router = APIRouter(tags=["prospects"])


def _templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


def _prospect_service(request: Request) -> ProspectService:
    return request.app.state.prospect_service


def _game_repo(request: Request) -> GameRepository:
    return request.app.state.game_repo


# ---------------------------------------------------------------------------
# Queue view
# ---------------------------------------------------------------------------


@router.get("/games/{slug}/queue", response_class=HTMLResponse)
async def review_queue(
    slug: str,
    request: Request,
    user: User = Depends(require_user),
) -> HTMLResponse:
    """Render the priority review queue for a game."""
    game_repo = _game_repo(request)
    game = game_repo.get_by_slug(slug)
    if game is None or game.user_id != user.user_id:
        raise HTTPException(status_code=404, detail="Game not found.")

    svc = _prospect_service(request)
    queue_items = svc.get_queue(game.game_id)

    tpl = _templates(request)
    return tpl.TemplateResponse(
        request,
        "queue/review.html",
        {
            "user": user,
            "game": game,
            "queue_items": queue_items,
            "thumbnail_limit": RECENT_VIDEO_THUMBNAIL_LIMIT,
        },
    )


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------


@router.get("/api/games/{game_id}/queue")
async def queue_api(
    game_id: str,
    request: Request,
    user: User = Depends(require_user),
) -> JSONResponse:
    """Return JSON queue data for a game."""
    game_repo = _game_repo(request)
    game = game_repo.get_by_id(game_id)
    if game is None or game.user_id != user.user_id:
        raise HTTPException(status_code=404, detail="Game not found.")

    svc = _prospect_service(request)
    queue_items = svc.get_queue(game_id)

    payload = []
    for item in queue_items:
        raw = item.prospect.raw_data
        payload.append(
            {
                "draft_item_id": item.draft.draft_item_id,
                "prospect_id": item.prospect.prospect_id,
                "platform": item.prospect.platform,
                "handle": item.prospect.handle,
                "display_name": item.prospect.display_name,
                "profile_url": item.prospect.profile_url,
                "contact_channel": item.prospect.contact_channel,
                "audience_size": item.prospect.audience_size,
                "avatar_url": raw.get("avatar_url"),
                "recent_video_thumbnails": raw.get(
                    "recent_video_thumbnails", []
                )[:RECENT_VIDEO_THUMBNAIL_LIMIT],
                "status": item.draft.status,
                "priority_score": item.draft.priority_score,
                "suggested_action": item.draft.suggested_action,
                "fit_summary": item.draft.fit_summary,
                "subject_line": item.draft.subject_line,
                "body_text": item.draft.body_text,
                "score_breakdown": item.draft.score_breakdown,
            }
        )

    return JSONResponse({"items": payload})


@router.post("/api/drafts/{draft_item_id}/action")
async def draft_action(
    draft_item_id: str,
    request: Request,
    user: User = Depends(require_user),
) -> JSONResponse:
    """Apply an action to a draft item.

    Request body: {"action": "approve|reject|snooze|sent", "body_text": "...", "notes": "..."}
    """
    body = await request.json()
    action = str(body.get("action", "")).strip().lower()
    body_text = body.get("body_text")
    notes = str(body.get("notes", "")).strip() or None

    svc = _prospect_service(request)
    try:
        svc.apply_action(
            draft_item_id,
            action=action,
            body_text=body_text if isinstance(body_text, str) else None,
            notes=notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return JSONResponse({"ok": True})
