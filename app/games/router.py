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
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth.dependencies import require_user
from app.auth.models import User
from app.games.repository import (
    AssetRepository,
    GameRepository,
    MessageTemplateRepository,
)
from app.games.service import GameService

router = APIRouter(tags=["games"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


def _game_service(request: Request) -> GameService:
    return request.app.state.game_service


def _game_repo(request: Request) -> GameRepository:
    return request.app.state.game_repo


def _asset_repo(request: Request) -> AssetRepository:
    return request.app.state.asset_repo


def _template_repo(request: Request) -> MessageTemplateRepository:
    return request.app.state.template_repo


def _platform_tags_from_form(request_form: object) -> list[str]:
    """Return only checkbox string values from a submitted Starlette form."""
    getlist = getattr(request_form, "getlist", None)
    if getlist is None:
        return []
    return [
        value for value in getlist("platform_tags") if isinstance(value, str)
    ]


# ---------------------------------------------------------------------------
# Game list / dashboard
# ---------------------------------------------------------------------------


@router.get("/games", response_class=HTMLResponse)
async def list_games(
    request: Request,
    user: User = Depends(require_user),
) -> HTMLResponse:
    """Render the dashboard showing all of the user's games."""
    game_repo = _game_repo(request)
    games = game_repo.list_by_user(user.user_id)

    # Get queue counts for each game
    from app.prospects.repository import DraftItemRepository

    draft_repo = DraftItemRepository(request.app.state.settings.db_path)
    queue_counts = {
        g.game_id: draft_repo.count_queued(g.game_id) for g in games
    }

    subscription = (
        request.app.state.billing_service.get_or_create_subscription(
            user.user_id
        )
    )

    tpl = _templates(request)
    return tpl.TemplateResponse(
        request,
        "games/list.html",
        {
            "user": user,
            "games": games,
            "queue_counts": queue_counts,
            "subscription": subscription,
        },
    )


# ---------------------------------------------------------------------------
# Create game
# ---------------------------------------------------------------------------


@router.get("/games/new", response_class=HTMLResponse)
async def new_game_page(
    request: Request,
    user: User = Depends(require_user),
) -> HTMLResponse:
    """Render the new game form."""
    tpl = _templates(request)
    return tpl.TemplateResponse(
        request,
        "games/create.html",
        {"user": user, "error": None},
    )


@router.post("/games")
async def create_game_post(
    request: Request,
    user: User = Depends(require_user),
    name: str = Form(...),
    description: str = Form(...),
    genre_tags: str = Form(default=""),
    audience_tags: str = Form(default=""),
    website_url: str = Form(default=""),
    discovery_schedule: str = Form(default="manual"),
) -> RedirectResponse:
    """Handle game creation form submission."""
    form = await request.form()
    platform_tags = _platform_tags_from_form(form)

    # Check subscription limit
    billing = request.app.state.billing_service
    if not billing.check_game_limit(user.user_id):
        tpl = _templates(request)
        return tpl.TemplateResponse(
            request,
            "games/create.html",
            {
                "user": user,
                "error": "You've reached your game limit. Upgrade your plan to add more games.",
            },
            status_code=400,
        )  # type: ignore[return-value]

    svc = _game_service(request)
    try:
        game = svc.create_game(
            user_id=user.user_id,
            name=name,
            description=description,
            genre_tags_raw=genre_tags,
            audience_tags_raw=audience_tags,
            platform_tags=platform_tags,
            website_url=website_url or None,
            discovery_schedule=discovery_schedule,
        )
    except ValueError as exc:
        tpl = _templates(request)
        return tpl.TemplateResponse(
            request,
            "games/create.html",
            {"user": user, "error": str(exc)},
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
    user: User = Depends(require_user),
) -> HTMLResponse:
    """Render the game setup page with tags, templates, and assets."""
    game_repo = _game_repo(request)
    game = game_repo.get_by_slug(slug)
    if game is None or game.user_id != user.user_id:
        raise HTTPException(status_code=404, detail="Game not found.")

    template_repo = _template_repo(request)
    asset_repo = _asset_repo(request)
    templates_list = template_repo.list_by_game(game.game_id)
    assets = asset_repo.list_by_game(game.game_id)

    tpl = _templates(request)
    return tpl.TemplateResponse(
        request,
        "games/setup.html",
        {
            "user": user,
            "game": game,
            "message_templates": templates_list,
            "assets": assets,
            "error": None,
        },
    )


@router.post("/games/{slug}")
async def update_game_post(
    slug: str,
    request: Request,
    user: User = Depends(require_user),
    name: str = Form(...),
    description: str = Form(...),
    genre_tags: str = Form(default=""),
    audience_tags: str = Form(default=""),
    website_url: str = Form(default=""),
    discovery_schedule: str = Form(default="manual"),
) -> RedirectResponse:
    """Handle game info update form submission."""
    form = await request.form()
    platform_tags = _platform_tags_from_form(form)

    game_repo = _game_repo(request)
    game = game_repo.get_by_slug(slug)
    if game is None or game.user_id != user.user_id:
        raise HTTPException(status_code=404, detail="Game not found.")

    svc = _game_service(request)
    try:
        svc.update_game(
            game_id=game.game_id,
            user_id=user.user_id,
            name=name,
            description=description,
            genre_tags_raw=genre_tags,
            audience_tags_raw=audience_tags,
            platform_tags=platform_tags,
            website_url=website_url or None,
            discovery_schedule=discovery_schedule,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return RedirectResponse(url=f"/games/{slug}/setup", status_code=303)


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


@router.post("/games/{slug}/templates")
async def create_template_post(
    slug: str,
    request: Request,
    user: User = Depends(require_user),
    name: str = Form(...),
    channel: str = Form(...),
    subject_template: str = Form(default=""),
    body_template: str = Form(...),
) -> RedirectResponse:
    """Add a new message template to the game."""
    game_repo = _game_repo(request)
    game = game_repo.get_by_slug(slug)
    if game is None or game.user_id != user.user_id:
        raise HTTPException(status_code=404, detail="Game not found.")

    svc = _game_service(request)
    try:
        svc.add_template(
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
    user: User = Depends(require_user),
) -> RedirectResponse:
    """Delete a message template."""
    game_repo = _game_repo(request)
    game = game_repo.get_by_slug(slug)
    if game is None or game.user_id != user.user_id:
        raise HTTPException(status_code=404, detail="Game not found.")

    svc = _game_service(request)
    try:
        svc.delete_template(template_id, game.game_id, user.user_id)
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
    user: User = Depends(require_user),
    asset_type: str = Form(...),
    title: str = Form(...),
    body: str = Form(default=""),
    url: str = Form(default=""),
) -> RedirectResponse:
    """Add a promotional asset to the game."""
    game_repo = _game_repo(request)
    game = game_repo.get_by_slug(slug)
    if game is None or game.user_id != user.user_id:
        raise HTTPException(status_code=404, detail="Game not found.")

    svc = _game_service(request)
    try:
        svc.add_asset(
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
    user: User = Depends(require_user),
) -> RedirectResponse:
    """Delete an asset."""
    game_repo = _game_repo(request)
    game = game_repo.get_by_slug(slug)
    if game is None or game.user_id != user.user_id:
        raise HTTPException(status_code=404, detail="Game not found.")

    svc = _game_service(request)
    try:
        svc.delete_asset(asset_id, game.game_id, user.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return RedirectResponse(url=f"/games/{slug}/setup", status_code=303)


# ---------------------------------------------------------------------------
# Ingestion trigger
# ---------------------------------------------------------------------------


@router.post("/api/games/{game_id}/run-ingestion")
async def run_ingestion_api(
    game_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_user),
) -> JSONResponse:
    """Trigger the discovery + scoring pipeline for a game (runs in background)."""
    game_repo = _game_repo(request)
    game = game_repo.get_by_id(game_id)
    if game is None or game.user_id != user.user_id:
        raise HTTPException(status_code=404, detail="Game not found.")

    billing = request.app.state.billing_service
    limit = billing.get_prospects_limit(user.user_id)
    settings = request.app.state.settings

    from app.ingestion.pipeline import run_ingestion

    background_tasks.add_task(
        run_ingestion,
        game,
        settings.db_path,
        limit,
        settings.youtube_api_key,
        settings.anthropic_api_key,
        settings.youtube_cache_dir,
    )

    return JSONResponse(
        {
            "ok": True,
            "message": "Discovery pipeline started in the background.",
        }
    )
