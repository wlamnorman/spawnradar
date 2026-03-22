"""Routes for game management: list, create, setup, assets, templates."""

from __future__ import annotations

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Form,
    HTTPException,
    Request,
)
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)
from fastapi.templating import Jinja2Templates

from app.auth.dependencies import require_product_access
from app.auth.models import User
from app.billing.models import TIER_LIMITS, TRIAL_LIMITS
from app.billing.service import BillingService
from app.config import Settings
from app.dependencies import (
    get_asset_repo,
    get_billing_service,
    get_draft_repo,
    get_game_repo,
    get_game_service,
    get_metrics_service,
    get_settings,
    get_template_repo,
    get_templates,
)
from app.games.repository import (
    AssetRepository,
    GameRepository,
    MessageTemplateRepository,
)
from app.games.service import GameService
from app.games.tags import catalog_for, featured_tags_for
from app.ingestion.pipeline import run_ingestion
from app.metrics.service import MetricsService
from app.prospects.repository import DraftItemRepository
from app.security import require_csrf_form, require_csrf_header

router = APIRouter(tags=["games"])


def _platform_tags_from_form(request_form: object) -> list[str]:
    """Return only checkbox string values from a submitted Starlette form."""
    getlist = getattr(request_form, "getlist", None)
    if getlist is None:
        return []
    return [
        value for value in getlist("platform_tags") if isinstance(value, str)
    ]


def _tag_form_context(game: object | None = None) -> dict[str, object]:
    """Return shared tag picker context for create and setup forms."""
    genre_primary: list[str] = []
    genre_secondary: list[str] = []
    audience_tags: list[str] = []
    mechanics_tags: list[str] = []
    tone_tags: list[str] = []

    if game is not None:
        genre_primary = getattr(game, "genre_primary_tags", [])
        genre_secondary = getattr(game, "genre_secondary_tags", [])
        # Merge primary + secondary into a single list for the collapsed pickers
        aud_p = getattr(game, "audience_primary_tags", [])
        aud_s = getattr(game, "audience_secondary_tags", [])
        audience_tags = aud_p + [t for t in aud_s if t not in aud_p]
        mech_p = getattr(game, "mechanics_primary_tags", [])
        mech_s = getattr(game, "mechanics_secondary_tags", [])
        mechanics_tags = mech_p + [t for t in mech_s if t not in mech_p]
        tone_p = getattr(game, "tone_primary_tags", [])
        tone_s = getattr(game, "tone_secondary_tags", [])
        tone_tags = tone_p + [t for t in tone_s if t not in tone_p]

    return {
        "featured_genre_tags": featured_tags_for("genre"),
        "featured_audience_tags": featured_tags_for("audience"),
        "featured_mechanics_tags": featured_tags_for("mechanics"),
        "featured_tone_tags": featured_tags_for("tone"),
        "genre_tag_catalog": catalog_for("genre"),
        "audience_tag_catalog": catalog_for("audience"),
        "mechanics_tag_catalog": catalog_for("mechanics"),
        "tone_tag_catalog": catalog_for("tone"),
        "genre_primary_tags_value": ", ".join(genre_primary),
        "genre_secondary_tags_value": ", ".join(genre_secondary),
        "audience_tags_value": ", ".join(audience_tags),
        "mechanics_tags_value": ", ".join(mechanics_tags),
        "tone_tags_value": ", ".join(tone_tags),
    }


# ---------------------------------------------------------------------------
# Game list / dashboard
# ---------------------------------------------------------------------------


@router.get("/games", response_class=HTMLResponse)
async def list_games(
    request: Request,
    user: User = Depends(require_product_access),
    game_repo: GameRepository = Depends(get_game_repo),
    draft_repo: DraftItemRepository = Depends(get_draft_repo),
    billing_service: BillingService = Depends(get_billing_service),
    game_service: GameService = Depends(get_game_service),
    templates: Jinja2Templates = Depends(get_templates),
) -> HTMLResponse:
    """Render the dashboard showing all of the user's games."""
    games = game_repo.list_by_user(user.user_id)

    # Get queue counts for each game
    queue_counts = {
        g.game_id: draft_repo.count_queued(g.game_id) for g in games
    }
    game_discovery_readiness = {
        g.game_id: game_service.get_discovery_readiness(g) for g in games
    }

    subscription = billing_service.get_or_create_subscription(user.user_id)
    discovery_status = billing_service.get_discovery_run_status(user.user_id)
    can_add_game = billing_service.check_game_limit(user.user_id)
    max_game_slots = max(limit["games"] for limit in TIER_LIMITS.values())
    current_game_limit = (
        TRIAL_LIMITS["games"]
        if subscription.is_trialing
        else TIER_LIMITS[subscription.effective_tier]["games"]
    )
    placeholder_slots = max(0, max_game_slots - len(games))
    unlocked_placeholder_slots = max(0, current_game_limit - len(games))

    return templates.TemplateResponse(
        request,
        "games/list.html",
        {
            "user": user,
            "games": games,
            "queue_counts": queue_counts,
            "game_discovery_readiness": game_discovery_readiness,
            "subscription": subscription,
            "discovery_status": discovery_status,
            "can_add_game": can_add_game,
            "placeholder_slots": placeholder_slots,
            "unlocked_placeholder_slots": unlocked_placeholder_slots,
        },
    )


# ---------------------------------------------------------------------------
# Create game
# ---------------------------------------------------------------------------


@router.get("/games/new", response_class=HTMLResponse)
async def new_game_page(
    request: Request,
    user: User = Depends(require_product_access),
    templates: Jinja2Templates = Depends(get_templates),
) -> HTMLResponse:
    """Render the new game form."""
    return templates.TemplateResponse(
        request,
        "games/create.html",
        {"user": user, "error": None, **_tag_form_context()},
    )


@router.post("/games")
async def create_game_post(
    request: Request,
    user: User = Depends(require_product_access),
    name: str = Form(...),
    summary: str = Form(default=""),
    description: str = Form(...),
    genre_primary_tags: str = Form(default=""),
    genre_secondary_tags: str = Form(default=""),
    audience_tags: str = Form(default=""),
    mechanics_tags: str = Form(default=""),
    tone_tags: str = Form(default=""),
    website_url: str = Form(default=""),
    billing_service: BillingService = Depends(get_billing_service),
    game_service: GameService = Depends(get_game_service),
    templates: Jinja2Templates = Depends(get_templates),
    _csrf: None = Depends(require_csrf_form),
) -> RedirectResponse:
    """Handle game creation form submission."""
    form = await request.form()
    platform_tags = _platform_tags_from_form(form)
    genre_tags_raw = str(form.get("genre_tags", "")).strip()

    # Check subscription limit
    if not billing_service.check_game_limit(user.user_id):
        return templates.TemplateResponse(
            request,
            "games/create.html",
            {
                "user": user,
                "error": "You've reached your game limit. Upgrade your plan to add more games.",
                **_tag_form_context(),
            },
            status_code=400,
        )  # type: ignore[return-value]

    try:
        game = game_service.create_game(
            user_id=user.user_id,
            name=name,
            description=description,
            genre_tags_raw=genre_tags_raw,
            audience_tags_raw=audience_tags,
            summary=summary,
            platform_tags=platform_tags,
            website_url=website_url or None,
            genre_primary_tags_raw=genre_primary_tags,
            genre_secondary_tags_raw=genre_secondary_tags,
            audience_primary_tags_raw=audience_tags,
            mechanics_primary_tags_raw=mechanics_tags,
            tone_primary_tags_raw=tone_tags,
        )
    except ValueError as exc:
        return templates.TemplateResponse(
            request,
            "games/create.html",
            {"user": user, "error": str(exc), **_tag_form_context()},
            status_code=400,
        )  # type: ignore[return-value]

    return RedirectResponse(url=f"/games/{game.slug}/setup", status_code=303)


# ---------------------------------------------------------------------------
# Game setup
# ---------------------------------------------------------------------------


@router.get("/games/{slug}/setup", response_class=HTMLResponse)
async def game_setup_page(
    slug: str,
    request: Request,
    user: User = Depends(require_product_access),
    game_repo: GameRepository = Depends(get_game_repo),
    template_repo: MessageTemplateRepository = Depends(get_template_repo),
    asset_repo: AssetRepository = Depends(get_asset_repo),
    game_service: GameService = Depends(get_game_service),
    templates: Jinja2Templates = Depends(get_templates),
) -> HTMLResponse:
    """Render the game setup page with tags, templates, and assets."""
    game = game_repo.get_by_slug(slug)
    if game is None or game.user_id != user.user_id:
        raise HTTPException(status_code=404, detail="Game not found.")

    templates_list = template_repo.list_by_game(game.game_id)
    assets = asset_repo.list_by_game(game.game_id)
    discovery_readiness = game_service.get_discovery_readiness(game)

    return templates.TemplateResponse(
        request,
        "games/setup.html",
        {
            "user": user,
            "game": game,
            "message_templates": templates_list,
            "assets": assets,
            "error": None,
            "discovery_readiness": discovery_readiness,
            **_tag_form_context(game),
        },
    )


@router.post("/games/{slug}")
async def update_game_post(
    slug: str,
    request: Request,
    user: User = Depends(require_product_access),
    name: str = Form(...),
    summary: str = Form(default=""),
    description: str = Form(...),
    genre_primary_tags: str = Form(default=""),
    genre_secondary_tags: str = Form(default=""),
    audience_tags: str = Form(default=""),
    mechanics_tags: str = Form(default=""),
    tone_tags: str = Form(default=""),
    website_url: str = Form(default=""),
    game_repo: GameRepository = Depends(get_game_repo),
    template_repo: MessageTemplateRepository = Depends(get_template_repo),
    asset_repo: AssetRepository = Depends(get_asset_repo),
    game_service: GameService = Depends(get_game_service),
    templates: Jinja2Templates = Depends(get_templates),
    _csrf: None = Depends(require_csrf_form),
) -> Response:
    """Handle game info update form submission."""
    form = await request.form()
    platform_tags = _platform_tags_from_form(form)
    genre_tags_raw = str(form.get("genre_tags", "")).strip()

    game = game_repo.get_by_slug(slug)
    if game is None or game.user_id != user.user_id:
        raise HTTPException(status_code=404, detail="Game not found.")

    try:
        game_service.update_game(
            game_id=game.game_id,
            user_id=user.user_id,
            name=name,
            description=description,
            genre_tags_raw=genre_tags_raw,
            audience_tags_raw=audience_tags,
            summary=summary,
            platform_tags=platform_tags,
            website_url=website_url or None,
            genre_primary_tags_raw=genre_primary_tags,
            genre_secondary_tags_raw=genre_secondary_tags,
            audience_primary_tags_raw=audience_tags,
            mechanics_primary_tags_raw=mechanics_tags,
            tone_primary_tags_raw=tone_tags,
        )
    except ValueError as exc:
        templates_list = template_repo.list_by_game(game.game_id)
        assets = asset_repo.list_by_game(game.game_id)
        return templates.TemplateResponse(
            request,
            "games/setup.html",
            {
                "user": user,
                "game": game,
                "message_templates": templates_list,
                "assets": assets,
                "error": str(exc),
                "discovery_readiness": game_service.get_discovery_readiness(
                    game
                ),
                **_tag_form_context(game),
            },
            status_code=400,
        )

    return RedirectResponse(url=f"/games/{slug}/setup", status_code=303)


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


@router.post("/games/{slug}/templates")
async def create_template_post(
    slug: str,
    request: Request,
    user: User = Depends(require_product_access),
    name: str = Form(...),
    channel: str = Form(...),
    subject_template: str = Form(default=""),
    body_template: str = Form(...),
    game_repo: GameRepository = Depends(get_game_repo),
    game_service: GameService = Depends(get_game_service),
    _csrf: None = Depends(require_csrf_form),
) -> RedirectResponse:
    """Add a new message template to the game."""
    game = game_repo.get_by_slug(slug)
    if game is None or game.user_id != user.user_id:
        raise HTTPException(status_code=404, detail="Game not found.")

    try:
        game_service.add_template(
            game_id=game.game_id,
            user_id=user.user_id,
            name=name,
            channel=channel,
            subject_template=subject_template or None,
            body_template=body_template,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return RedirectResponse(url=f"/games/{slug}/setup", status_code=303)


@router.post("/games/{slug}/templates/{template_id}/delete")
async def delete_template_post(
    slug: str,
    template_id: str,
    request: Request,
    user: User = Depends(require_product_access),
    game_repo: GameRepository = Depends(get_game_repo),
    game_service: GameService = Depends(get_game_service),
    _csrf: None = Depends(require_csrf_form),
) -> RedirectResponse:
    """Delete a message template."""
    game = game_repo.get_by_slug(slug)
    if game is None or game.user_id != user.user_id:
        raise HTTPException(status_code=404, detail="Game not found.")

    try:
        game_service.delete_template(template_id, game.game_id, user.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return RedirectResponse(url=f"/games/{slug}/setup", status_code=303)


# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------


@router.post("/games/{slug}/assets")
async def create_asset_post(
    slug: str,
    request: Request,
    user: User = Depends(require_product_access),
    asset_type: str = Form(...),
    title: str = Form(...),
    body: str = Form(default=""),
    url: str = Form(default=""),
    game_repo: GameRepository = Depends(get_game_repo),
    game_service: GameService = Depends(get_game_service),
    _csrf: None = Depends(require_csrf_form),
) -> RedirectResponse:
    """Add a promotional asset to the game."""
    game = game_repo.get_by_slug(slug)
    if game is None or game.user_id != user.user_id:
        raise HTTPException(status_code=404, detail="Game not found.")

    try:
        game_service.add_asset(
            game_id=game.game_id,
            user_id=user.user_id,
            asset_type=asset_type,
            title=title,
            body=body or None,
            url=url or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return RedirectResponse(url=f"/games/{slug}/setup", status_code=303)


@router.post("/games/{slug}/assets/{asset_id}/delete")
async def delete_asset_post(
    slug: str,
    asset_id: str,
    request: Request,
    user: User = Depends(require_product_access),
    game_repo: GameRepository = Depends(get_game_repo),
    game_service: GameService = Depends(get_game_service),
    _csrf: None = Depends(require_csrf_form),
) -> RedirectResponse:
    """Delete an asset."""
    game = game_repo.get_by_slug(slug)
    if game is None or game.user_id != user.user_id:
        raise HTTPException(status_code=404, detail="Game not found.")

    try:
        game_service.delete_asset(asset_id, game.game_id, user.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return RedirectResponse(url=f"/games/{slug}/setup", status_code=303)


# ---------------------------------------------------------------------------
# Game lifecycle (duplicate / archive / delete)
# ---------------------------------------------------------------------------


@router.post("/games/{slug}/duplicate")
async def duplicate_game_post(
    slug: str,
    request: Request,
    user: User = Depends(require_product_access),
    game_repo: GameRepository = Depends(get_game_repo),
    game_service: GameService = Depends(get_game_service),
    billing_service: BillingService = Depends(get_billing_service),
    _csrf: None = Depends(require_csrf_form),
) -> RedirectResponse:
    """Duplicate a game, redirecting to the copy's setup page."""
    game = game_repo.get_by_slug(slug)
    if game is None or game.user_id != user.user_id:
        raise HTTPException(status_code=404, detail="Game not found.")
    if not billing_service.check_game_limit(user.user_id):
        raise HTTPException(
            status_code=400,
            detail="Game limit reached. Upgrade your plan to add more games.",
        )
    game_service.duplicate_game(game.game_id, user.user_id)
    return RedirectResponse(url="/games", status_code=303)


@router.post("/games/{slug}/delete")
async def delete_game_post(
    slug: str,
    request: Request,
    user: User = Depends(require_product_access),
    game_repo: GameRepository = Depends(get_game_repo),
    game_service: GameService = Depends(get_game_service),
    _csrf: None = Depends(require_csrf_form),
) -> RedirectResponse:
    """Permanently delete a game and all its data."""
    game = game_repo.get_by_slug(slug)
    if game is None or game.user_id != user.user_id:
        raise HTTPException(status_code=404, detail="Game not found.")
    game_service.delete_game(game.game_id, user.user_id)
    return RedirectResponse(url="/games", status_code=303)


# ---------------------------------------------------------------------------
# Ingestion trigger
# ---------------------------------------------------------------------------


@router.post("/api/games/{game_id}/run-ingestion")
async def run_ingestion_api(
    game_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_product_access),
    game_repo: GameRepository = Depends(get_game_repo),
    billing_service: BillingService = Depends(get_billing_service),
    game_service: GameService = Depends(get_game_service),
    metrics_service: MetricsService = Depends(get_metrics_service),
    settings: Settings = Depends(get_settings),
    _csrf: None = Depends(require_csrf_header),
) -> JSONResponse:
    """Trigger the discovery + scoring pipeline for a game (runs in background)."""
    game = game_repo.get_by_id(game_id)
    if game is None or game.user_id != user.user_id:
        raise HTTPException(status_code=404, detail="Game not found.")

    readiness = game_service.get_discovery_readiness(game)
    if not readiness.can_run:
        raise HTTPException(status_code=409, detail=readiness.message)

    try:
        discovery_status = billing_service.record_discovery_run(
            user.user_id, game.game_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc

    limit = billing_service.get_prospects_limit(user.user_id)

    background_tasks.add_task(
        run_ingestion,
        game,
        settings.db_path,
        limit,
        settings.youtube_api_key,
        settings.anthropic_api_key,
        settings.youtube_cache_dir,
        settings.twitch_client_id,
        settings.twitch_client_secret,
        run_id=discovery_status.run_id,
        metrics_service=metrics_service,
    )

    return JSONResponse(
        {
            "ok": True,
            "message": "Discovery pipeline started in the background.",
            "usage": discovery_status.as_payload(),
        }
    )
