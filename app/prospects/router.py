"""Routes for the review queue and draft item actions."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.auth.dependencies import require_product_access
from app.auth.models import User
from app.billing.service import BillingService
from app.config import Settings
from app.dependencies import (
    get_billing_service,
    get_game_repo,
    get_game_service,
    get_metrics_service,
    get_prospect_service,
    get_settings,
    get_templates,
)
from app.games.repository import GameRepository
from app.games.service import GameService
from app.ingestion.constants import RECENT_VIDEO_THUMBNAIL_LIMIT
from app.metrics.service import MetricsService
from app.prospects.presenter import ReviewQueuePresenter
from app.prospects.service import ProspectService
from app.security import require_csrf_header

router = APIRouter(tags=["prospects"])

_QUEUE_PRESENTER = ReviewQueuePresenter()


# ---------------------------------------------------------------------------
# Queue view
# ---------------------------------------------------------------------------


@router.get("/games/{slug}/queue", response_class=HTMLResponse)
async def review_queue(
    slug: str,
    request: Request,
    user: User = Depends(require_product_access),
    game_repo: GameRepository = Depends(get_game_repo),
    prospect_service: ProspectService = Depends(get_prospect_service),
    billing_service: BillingService = Depends(get_billing_service),
    game_service: GameService = Depends(get_game_service),
    templates: Jinja2Templates = Depends(get_templates),
    settings: Settings = Depends(get_settings),
) -> HTMLResponse:
    """Render the priority review queue for a game."""
    game = game_repo.get_by_slug(slug)
    if game is None or game.user_id != user.user_id:
        raise HTTPException(status_code=404, detail="Game not found.")

    queue_items = _QUEUE_PRESENTER.for_template(
        prospect_service.get_queue(game.game_id)
    )
    discovery_status = billing_service.get_discovery_run_status(user.user_id)
    game_discovery_readiness = game_service.get_discovery_readiness(game)

    source_credentials = {
        "youtube": True,  # scraping fallback always available
        "twitch": bool(
            settings.twitch_client_id and settings.twitch_client_secret
        ),
        "bluesky": True,
    }

    return templates.TemplateResponse(
        request,
        "queue/review.html",
        {
            "user": user,
            "game": game,
            "queue_items": queue_items,
            "thumbnail_limit": RECENT_VIDEO_THUMBNAIL_LIMIT,
            "discovery_status": discovery_status,
            "game_discovery_readiness": game_discovery_readiness,
            "source_credentials": source_credentials,
        },
    )


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------


@router.get("/api/games/{game_id}/queue")
async def queue_api(
    game_id: str,
    request: Request,
    run_id: str | None = None,
    user: User = Depends(require_product_access),
    game_repo: GameRepository = Depends(get_game_repo),
    prospect_service: ProspectService = Depends(get_prospect_service),
    metrics_service: MetricsService = Depends(get_metrics_service),
) -> JSONResponse:
    """Return JSON queue data for a game."""
    game = game_repo.get_by_id(game_id)
    if game is None or game.user_id != user.user_id:
        raise HTTPException(status_code=404, detail="Game not found.")

    payload = _QUEUE_PRESENTER.for_api(prospect_service.get_queue(game_id))
    response_payload: dict[str, object] = {"items": payload}
    if run_id:
        run_fact = metrics_service.get_discovery_run_fact(run_id)
        if run_fact is None:
            raise HTTPException(
                status_code=404, detail="Discovery run not found."
            )
        if run_fact.user_id != user.user_id or run_fact.game_id != game_id:
            raise HTTPException(
                status_code=404, detail="Discovery run not found."
            )
        response_payload["discovery_run"] = {
            "run_id": run_fact.run_id,
            "status": run_fact.status,
            "started_at": run_fact.started_at,
            "completed_at": run_fact.completed_at,
            "discovered_count": run_fact.discovered_count,
            "scored_count": run_fact.scored_count,
            "queued_count": run_fact.queued_count,
            "error_message": run_fact.error_message,
        }
    return JSONResponse(response_payload)


@router.post("/api/drafts/{draft_item_id}/action")
async def draft_action(
    draft_item_id: str,
    request: Request,
    user: User = Depends(require_product_access),
    prospect_service: ProspectService = Depends(get_prospect_service),
    _csrf: None = Depends(require_csrf_header),
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
