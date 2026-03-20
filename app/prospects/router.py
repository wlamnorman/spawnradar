"""Routes for the review queue and draft item actions."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.auth.dependencies import require_user
from app.auth.models import User
from app.dependencies import get_game_repo, get_prospect_service, get_templates
from app.games.repository import GameRepository
from app.ingestion.constants import RECENT_VIDEO_THUMBNAIL_LIMIT
from app.prospects.presenter import ReviewQueuePresenter
from app.prospects.service import ProspectService

router = APIRouter(tags=["prospects"])

_QUEUE_PRESENTER = ReviewQueuePresenter()


# ---------------------------------------------------------------------------
# Queue view
# ---------------------------------------------------------------------------


@router.get("/games/{slug}/queue", response_class=HTMLResponse)
async def review_queue(
    slug: str,
    request: Request,
    user: User = Depends(require_user),
    game_repo: GameRepository = Depends(get_game_repo),
    prospect_service: ProspectService = Depends(get_prospect_service),
    templates: Jinja2Templates = Depends(get_templates),
) -> HTMLResponse:
    """Render the priority review queue for a game."""
    game = game_repo.get_by_slug(slug)
    if game is None or game.user_id != user.user_id:
        raise HTTPException(status_code=404, detail="Game not found.")

    queue_items = _QUEUE_PRESENTER.for_template(
        prospect_service.get_queue(game.game_id)
    )

    return templates.TemplateResponse(
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
    game_repo: GameRepository = Depends(get_game_repo),
    prospect_service: ProspectService = Depends(get_prospect_service),
) -> JSONResponse:
    """Return JSON queue data for a game."""
    game = game_repo.get_by_id(game_id)
    if game is None or game.user_id != user.user_id:
        raise HTTPException(status_code=404, detail="Game not found.")

    payload = _QUEUE_PRESENTER.for_api(prospect_service.get_queue(game_id))
    return JSONResponse({"items": payload})


@router.post("/api/drafts/{draft_item_id}/action")
async def draft_action(
    draft_item_id: str,
    request: Request,
    user: User = Depends(require_user),
    prospect_service: ProspectService = Depends(get_prospect_service),
) -> JSONResponse:
    """Apply an action to a draft item.

    Request body: {"action": "approve|reject|snooze|sent", "body_text": "...", "notes": "..."}
    """
    body = await request.json()
    action = str(body.get("action", "")).strip().lower()
    body_text = body.get("body_text")
    notes = str(body.get("notes", "")).strip() or None

    try:
        prospect_service.apply_action(
            draft_item_id,
            action=action,
            body_text=body_text if isinstance(body_text, str) else None,
            notes=notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return JSONResponse({"ok": True})
