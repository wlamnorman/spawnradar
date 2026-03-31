"""Routes for game management: list, create, setup, assets, templates."""

from __future__ import annotations

from fastapi import (
    APIRouter,
    Depends,
    Form,
    HTTPException,
    Request,
)
from fastapi.responses import (
    HTMLResponse,
    RedirectResponse,
    Response,
)
from fastapi.templating import Jinja2Templates

from app.auth.dependencies import (
    require_user_or_anonymous,
)
from app.auth.models import User
from app.billing.models import FREE_LIMITS, TIER_LIMITS
from app.billing.service import BillingService
from app.config import Settings
from app.dependencies import (
    get_billing_service,
    get_customer_game_repo,
    get_customer_game_service,
    get_game_import_service,
    get_settings,
    get_templates,
)
from app.game_import.service import GameImportService
from app.games.constants import MAX_DESCRIPTION_LENGTH, MAX_SUMMARY_LENGTH
from app.games.repository import CustomerGameRepository
from app.games.service import CustomerGameService
from app.igdb.platforms import PLATFORM_OPTIONS
from app.igdb.repository import IGDBRepository
from app.igdb.taxonomy import (
    IGDB_GENRE_KEYWORDS,
    IGDB_MECHANIC_KEYWORDS,
    IGDB_THEME_KEYWORDS,
    IGDBGameMode,
    IGDBGenre,
    IGDBPlayerPerspective,
    IGDBTheme,
    keyword_label_for_value,
)
from app.prospects.service import ProspectRankingService
from app.security import (
    RateLimitRule,
    client_ip_key,
    consume_rate_limit,
    require_csrf_form,
)

router = APIRouter(tags=["games"])

_CURATED_IGDB_KEYWORDS = (
    *IGDB_GENRE_KEYWORDS,
    *IGDB_THEME_KEYWORDS,
    *IGDB_MECHANIC_KEYWORDS,
)
_ALLOWED_IGDB_KEYWORD_IDS = frozenset(
    keyword.canonical for keyword in _CURATED_IGDB_KEYWORDS
)
_PLATFORM_OPTIONS = PLATFORM_OPTIONS
_ALLOWED_PLATFORM_VALUES = frozenset(value for value, _ in _PLATFORM_OPTIONS)
_PC_IMPORT_PLATFORM_LABELS = frozenset({"Windows", "macOS", "Linux"})


def _keyword_option_label(canonical: str) -> str:
    """Render a canonical keyword into a readable checkbox label."""
    return keyword_label_for_value(canonical) or canonical.title()


def _picker_option(
    field_name: str, value: int | str, label: str, pill_class: str
) -> dict[str, object]:
    """Build one searchable picker option for the game form."""
    return {
        "field_name": field_name,
        "value": value,
        "label": label,
        "pill_class": pill_class,
    }


def _igdb_form_context() -> dict[str, object]:
    """Return IGDB genre/theme picker context for create and setup forms."""
    igdb_genres = sorted(
        [(g.value, g.label) for g in IGDBGenre.gaming()], key=lambda x: x[1]
    )
    official_genre_labels = {label.casefold() for _, label in igdb_genres}
    igdb_themes = sorted(
        [(t.value, t.label) for t in IGDBTheme.gaming()], key=lambda x: x[1]
    )
    official_theme_labels = {label.casefold() for _, label in igdb_themes}
    igdb_game_modes = sorted(
        [(m.value, m.label) for m in IGDBGameMode], key=lambda x: x[1]
    )
    igdb_player_perspectives = sorted(
        [(p.value, p.label) for p in IGDBPlayerPerspective],
        key=lambda x: x[1],
    )
    igdb_genre_keywords = sorted(
        [
            (keyword.canonical, _keyword_option_label(keyword.canonical))
            for keyword in IGDB_GENRE_KEYWORDS
            if _keyword_option_label(keyword.canonical).casefold()
            not in official_genre_labels
        ],
        key=lambda item: item[1],
    )
    igdb_theme_keywords = sorted(
        [
            (keyword.canonical, _keyword_option_label(keyword.canonical))
            for keyword in IGDB_THEME_KEYWORDS
            if _keyword_option_label(keyword.canonical).casefold()
            not in official_theme_labels
        ],
        key=lambda item: item[1],
    )
    igdb_mechanic_keywords = sorted(
        [
            (keyword.canonical, _keyword_option_label(keyword.canonical))
            for keyword in IGDB_MECHANIC_KEYWORDS
        ],
        key=lambda item: item[1],
    )
    genre_picker_options = [
        _picker_option("igdb_genre_ids", value, label, "tag-genre")
        for value, label in igdb_genres
    ] + [
        _picker_option("igdb_keyword_ids", value, label, "tag-genre")
        for value, label in igdb_genre_keywords
    ]
    theme_picker_options = [
        _picker_option("igdb_theme_ids", value, label, "tag-theme")
        for value, label in igdb_themes
    ] + [
        _picker_option("igdb_keyword_ids", value, label, "tag-theme")
        for value, label in igdb_theme_keywords
    ]
    mechanic_picker_options = [
        _picker_option("igdb_keyword_ids", value, label, "tag-mechanics")
        for value, label in igdb_mechanic_keywords
    ]
    return {
        "description_max_length": MAX_DESCRIPTION_LENGTH,
        "summary_max_length": MAX_SUMMARY_LENGTH,
        "platform_options": _PLATFORM_OPTIONS,
        "igdb_genres": igdb_genres,
        "igdb_themes": igdb_themes,
        "igdb_game_modes": igdb_game_modes,
        "igdb_player_perspectives": igdb_player_perspectives,
        "igdb_genre_keywords": igdb_genre_keywords,
        "igdb_theme_keywords": igdb_theme_keywords,
        "igdb_mechanic_keywords": igdb_mechanic_keywords,
        "genre_picker_options": genre_picker_options,
        "theme_picker_options": theme_picker_options,
        "mechanic_picker_options": mechanic_picker_options,
    }


def _int_form_values(request_form: object, field_name: str) -> list[int]:
    """Return integer values from a Starlette form list field."""
    getlist = getattr(request_form, "getlist", None)
    if getlist is None:
        return []
    values = getlist(field_name)
    return [int(value) for value in values if isinstance(value, str) and value]


def _string_form_values(
    request_form: object,
    field_name: str,
    *,
    allowed_values: frozenset[str] | None = None,
) -> list[str]:
    """Return unique non-empty string values from a Starlette form list field."""
    getlist = getattr(request_form, "getlist", None)
    if getlist is None:
        return []
    seen: set[str] = set()
    result: list[str] = []
    for value in getlist(field_name):
        if not isinstance(value, str):
            continue
        normalized = value.strip()
        if (
            normalized
            and normalized not in seen
            and (allowed_values is None or normalized in allowed_values)
        ):
            seen.add(normalized)
            result.append(normalized)
    return result


def _game_form_state(
    *,
    name: str = "",
    summary: str = "",
    description: str = "",
    website_url: str = "",
    platforms: list[str] | None = None,
    igdb_genre_ids: list[int] | None = None,
    igdb_theme_ids: list[int] | None = None,
    igdb_game_mode_ids: list[int] | None = None,
    igdb_player_perspective_ids: list[int] | None = None,
    igdb_keyword_ids: list[str] | None = None,
    similar_game_names: list[str] | None = None,
) -> dict[str, object]:
    """Return a template-friendly snapshot of the current game form state."""
    return {
        "name_value": name,
        "summary_value": summary,
        "description_value": description,
        "website_url_value": website_url,
        "selected_platforms": tuple(platforms or ()),
        "selected_igdb_genre_ids": tuple(igdb_genre_ids or ()),
        "selected_igdb_theme_ids": tuple(igdb_theme_ids or ()),
        "selected_igdb_game_mode_ids": tuple(igdb_game_mode_ids or ()),
        "selected_igdb_player_perspective_ids": tuple(
            igdb_player_perspective_ids or ()
        ),
        "selected_igdb_keyword_ids": tuple(igdb_keyword_ids or ()),
        "selected_similar_game_names": tuple(similar_game_names or ()),
    }


def _game_form_state_from_game(game: object) -> dict[str, object]:
    """Build form state from a persisted customer game."""
    return _game_form_state(
        name=str(getattr(game, "name", "")),
        summary=str(getattr(game, "summary", "") or ""),
        description=str(getattr(game, "description", "") or ""),
        website_url=str(getattr(game, "website_url", "") or ""),
        platforms=list(getattr(game, "platforms", ()) or ()),
        igdb_genre_ids=list(getattr(game, "igdb_genre_ids", ()) or ()),
        igdb_theme_ids=list(getattr(game, "igdb_theme_ids", ()) or ()),
        igdb_game_mode_ids=list(getattr(game, "igdb_game_mode_ids", ()) or ()),
        igdb_player_perspective_ids=list(
            getattr(game, "igdb_player_perspective_ids", ()) or ()
        ),
        igdb_keyword_ids=list(getattr(game, "igdb_keyword_ids", ()) or ()),
        similar_game_names=list(getattr(game, "similar_game_names", ()) or ()),
    )


def _platform_values_from_import(platform_labels: list[str]) -> list[str]:
    """Map imported platform labels into the current form platform values."""
    if any(label in _PC_IMPORT_PLATFORM_LABELS for label in platform_labels):
        return ["pc"]
    return []


# ---------------------------------------------------------------------------
# Game list / dashboard
# ---------------------------------------------------------------------------


@router.get("/games", response_class=HTMLResponse)
def list_games(
    request: Request,
    user: User = Depends(require_user_or_anonymous),
    game_repo: CustomerGameRepository = Depends(get_customer_game_repo),
    billing_service: BillingService = Depends(get_billing_service),
    settings: Settings = Depends(get_settings),
    templates: Jinja2Templates = Depends(get_templates),
) -> HTMLResponse:
    """Render the dashboard showing all of the user's games."""
    games = game_repo.list_by_user(user.user_id)

    subscription = billing_service.get_subscription(user.user_id)
    can_add_game = billing_service.check_game_limit(user.user_id)
    max_game_slots = max(limit["games"] for limit in TIER_LIMITS.values())
    is_limited = subscription is None or not subscription.has_access
    if is_limited:
        current_game_limit = FREE_LIMITS["games"]
    else:
        assert subscription is not None  # narrowing for type checker
        current_game_limit = TIER_LIMITS[subscription.effective_tier]["games"]
    prospect_service = ProspectRankingService(settings.db_path)
    game_match_counts = {
        game.customer_game_id: prospect_service.count_prospects(
            game,
            min_reach=settings.creator_index_twitch_min_followers,
        )
        for game in games
    }
    placeholder_slots = max(0, max_game_slots - len(games))
    unlocked_placeholder_slots = max(0, current_game_limit - len(games))

    return templates.TemplateResponse(
        request,
        "games/list.html",
        {
            "user": user,
            "games": games,
            "subscription": subscription,
            "can_add_game": can_add_game,
            "game_match_counts": game_match_counts,
            "placeholder_slots": placeholder_slots,
            "unlocked_placeholder_slots": unlocked_placeholder_slots,
            "is_limited": is_limited,
        },
    )


@router.get("/games/igdb-search")
def search_cached_igdb_games(
    q: str,
    user: User = Depends(require_user_or_anonymous),
    settings: Settings = Depends(get_settings),
) -> list[dict[str, object]]:
    """Return cached IGDB game name suggestions for similar-games inputs."""
    del user
    rows = IGDBRepository(settings.db_path).search_by_name(q)
    return [
        {
            "igdb_id": int(row["igdb_id"]),
            "name": str(row["name"]),
            "slug": str(row["slug"]),
        }
        for row in rows
    ]


@router.post("/games/import-url")
async def import_url_json(
    request: Request,
    user: User = Depends(require_user_or_anonymous),
    game_import_service: GameImportService = Depends(get_game_import_service),
) -> dict[str, object]:
    """Return imported game data as JSON for client-side form filling."""
    payload = await request.json()
    url = str(payload.get("url") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL is required.")
    try:
        preview = await game_import_service.import_url(url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    draft = preview.draft
    return {
        "name": draft.name,
        "summary": draft.summary,
        "description": draft.description,
        "website_url": draft.website_url or "",
        "platform_labels": draft.platform_labels,
        "platforms": _platform_values_from_import(draft.platform_labels),
        "igdb_genre_ids": draft.igdb_genre_ids,
        "igdb_theme_ids": draft.igdb_theme_ids,
        "igdb_game_mode_ids": draft.igdb_game_mode_ids,
        "igdb_keyword_ids": draft.igdb_keyword_ids,
    }


def _parse_game_form(
    form: object,
    *,
    name: str,
    summary: str,
    description: str,
    website_url: str,
) -> tuple[
    list[int], list[int], list[int], list[int],
    list[str], list[str], list[str], dict[str, object],
]:
    """Parse multi-value form fields and build form state.

    Returns (igdb_genre_ids, igdb_theme_ids, igdb_game_mode_ids,
    igdb_player_perspective_ids, igdb_keyword_ids, platforms,
    similar_game_names, form_state).
    """
    igdb_genre_ids = _int_form_values(form, "igdb_genre_ids")
    igdb_theme_ids = _int_form_values(form, "igdb_theme_ids")
    igdb_game_mode_ids = _int_form_values(form, "igdb_game_mode_ids")
    igdb_player_perspective_ids = _int_form_values(
        form, "igdb_player_perspective_ids"
    )
    igdb_keyword_ids = _string_form_values(
        form,
        "igdb_keyword_ids",
        allowed_values=_ALLOWED_IGDB_KEYWORD_IDS,
    )
    platforms = _string_form_values(
        form, "platforms", allowed_values=_ALLOWED_PLATFORM_VALUES
    )
    similar_game_names = _string_form_values(form, "similar_game_names")
    form_state = _game_form_state(
        name=name,
        summary=summary,
        description=description,
        website_url=website_url,
        platforms=platforms,
        igdb_genre_ids=igdb_genre_ids,
        igdb_theme_ids=igdb_theme_ids,
        igdb_game_mode_ids=igdb_game_mode_ids,
        igdb_player_perspective_ids=igdb_player_perspective_ids,
        igdb_keyword_ids=igdb_keyword_ids,
        similar_game_names=similar_game_names,
    )
    return (
        igdb_genre_ids, igdb_theme_ids, igdb_game_mode_ids,
        igdb_player_perspective_ids, igdb_keyword_ids, platforms,
        similar_game_names, form_state,
    )


# ---------------------------------------------------------------------------
# Game setup (unified create + edit)
# ---------------------------------------------------------------------------


@router.get("/games/new")
def new_game_redirect() -> Response:
    """Backward-compatible redirect from old create page."""
    return RedirectResponse(url="/games/setup", status_code=301)


@router.get("/games/setup", response_class=HTMLResponse)
def new_game_setup_page(
    request: Request,
    user: User = Depends(require_user_or_anonymous),
    templates: Jinja2Templates = Depends(get_templates),
) -> HTMLResponse:
    """Render the setup page for a new game (empty form)."""
    return templates.TemplateResponse(
        request,
        "games/setup.html",
        {
            "user": user,
            "game": None,
            "error": None,
            "form_state": _game_form_state(),
            **_igdb_form_context(),
        },
    )


@router.post("/games/setup")
async def create_game_post(
    request: Request,
    user: User = Depends(require_user_or_anonymous),
    name: str = Form(default=""),
    summary: str = Form(default=""),
    description: str = Form(default=""),
    website_url: str = Form(default=""),
    billing_service: BillingService = Depends(get_billing_service),
    game_service: CustomerGameService = Depends(get_customer_game_service),
    settings: Settings = Depends(get_settings),
    templates: Jinja2Templates = Depends(get_templates),
    _csrf: None = Depends(require_csrf_form),
) -> Response:
    """Handle game creation form submission."""
    form = await request.form()
    igdb_genre_ids, igdb_theme_ids, igdb_game_mode_ids, \
        igdb_player_perspective_ids, igdb_keyword_ids, platforms, \
        similar_game_names, form_state = _parse_game_form(
            form, name=name, summary=summary, description=description,
            website_url=website_url,
        )

    # Rate-limit anonymous game creation
    if user.is_anonymous and not consume_rate_limit(settings.db_path, "game_create_anon", [
        RateLimitRule(key=client_ip_key(request), limit=3, window_seconds=600),
    ]):
        response = _render_game_setup_form(
            request,
            templates,
            user,
            None,
            error="Too many games created. Please wait a few minutes and try again.",
            form_state=form_state,
        )
        response.status_code = 429
        return response

    # Check subscription limit
    if not billing_service.check_game_limit(user.user_id):
        response = _render_game_setup_form(
            request,
            templates,
            user,
            None,
            error="You've reached your game limit. Upgrade your plan to add more games.",
            form_state=form_state,
        )
        response.status_code = 400
        return response  # type: ignore[return-value]

    try:
        game_service.create_game(
            user_id=user.user_id,
            name=name,
            description=description,
            website_url=website_url or None,
            summary=summary,
            platforms=platforms or None,
            igdb_genre_ids=igdb_genre_ids or None,
            igdb_theme_ids=igdb_theme_ids or None,
            igdb_game_mode_ids=igdb_game_mode_ids or None,
            igdb_player_perspective_ids=igdb_player_perspective_ids or None,
            igdb_keyword_ids=igdb_keyword_ids or None,
            similar_game_names=similar_game_names or None,
        )
    except ValueError as exc:
        response = _render_game_setup_form(
            request,
            templates,
            user,
            None,
            error=str(exc),
            form_state=form_state,
        )
        response.status_code = 400
        return response  # type: ignore[return-value]

    return RedirectResponse(url="/games", status_code=303)


@router.get("/games/{slug}/setup", response_class=HTMLResponse)
def game_setup_page(
    slug: str,
    request: Request,
    user: User = Depends(require_user_or_anonymous),
    game_repo: CustomerGameRepository = Depends(get_customer_game_repo),
    templates: Jinja2Templates = Depends(get_templates),
) -> HTMLResponse:
    """Render the game setup page."""
    game = game_repo.get_by_slug(slug)
    if game is None or (game.user_id != user.user_id and not user.is_admin):
        raise HTTPException(status_code=404, detail="Game not found.")

    return templates.TemplateResponse(
        request,
        "games/setup.html",
        {
            "user": user,
            "game": game,
            "error": None,
            "form_state": _game_form_state_from_game(game),
            **_igdb_form_context(),
        },
    )


def _render_game_setup_form(
    request: Request,
    templates: Jinja2Templates,
    user: User,
    game: object,
    *,
    error: str | None,
    form_state: dict[str, object],
) -> HTMLResponse:
    """Render the game setup page with shared template context."""
    return templates.TemplateResponse(
        request,
        "games/setup.html",
        {
            "user": user,
            "game": game,
            "error": error,
            "form_state": form_state,
            **_igdb_form_context(),
        },
    )


@router.post("/games/{slug}/setup")
async def update_game_post(
    slug: str,
    request: Request,
    user: User = Depends(require_user_or_anonymous),
    name: str = Form(default=""),
    summary: str = Form(default=""),
    description: str = Form(default=""),
    website_url: str = Form(default=""),
    game_repo: CustomerGameRepository = Depends(get_customer_game_repo),
    game_service: CustomerGameService = Depends(get_customer_game_service),
    templates: Jinja2Templates = Depends(get_templates),
    _csrf: None = Depends(require_csrf_form),
) -> Response:
    """Handle game info update form submission."""
    form = await request.form()
    igdb_genre_ids, igdb_theme_ids, igdb_game_mode_ids, \
        igdb_player_perspective_ids, igdb_keyword_ids, platforms, \
        similar_game_names, form_state = _parse_game_form(
            form, name=name, summary=summary, description=description,
            website_url=website_url,
        )

    game = game_repo.get_by_slug(slug)
    if game is None or (game.user_id != user.user_id and not user.is_admin):
        raise HTTPException(status_code=404, detail="Game not found.")

    try:
        game_service.update_game(
            customer_game_id=game.customer_game_id,
            user_id=game.user_id,  # use owner's ID so service ownership check passes
            name=name,
            description=description,
            website_url=website_url or None,
            summary=summary,
            platforms=platforms,
            igdb_genre_ids=igdb_genre_ids,
            igdb_theme_ids=igdb_theme_ids,
            igdb_game_mode_ids=igdb_game_mode_ids,
            igdb_player_perspective_ids=igdb_player_perspective_ids,
            igdb_keyword_ids=igdb_keyword_ids,
            similar_game_names=similar_game_names,
        )
    except ValueError as exc:
        response = _render_game_setup_form(
            request,
            templates,
            user,
            game,
            error=str(exc),
            form_state=form_state,
        )
        response.status_code = 400
        return response

    return RedirectResponse(url="/games", status_code=303)


# ---------------------------------------------------------------------------
# Game lifecycle (duplicate / archive / delete)
# ---------------------------------------------------------------------------


@router.post("/games/{slug}/duplicate")
def duplicate_game_post(
    slug: str,
    request: Request,
    user: User = Depends(require_user_or_anonymous),
    game_repo: CustomerGameRepository = Depends(get_customer_game_repo),
    game_service: CustomerGameService = Depends(get_customer_game_service),
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
    game_service.duplicate_game(game.customer_game_id, user.user_id)
    return RedirectResponse(url="/games", status_code=303)


@router.post("/games/{slug}/delete")
def delete_game_post(
    slug: str,
    request: Request,
    user: User = Depends(require_user_or_anonymous),
    game_repo: CustomerGameRepository = Depends(get_customer_game_repo),
    game_service: CustomerGameService = Depends(get_customer_game_service),
    _csrf: None = Depends(require_csrf_form),
) -> RedirectResponse:
    """Permanently delete a game and all its data."""
    game = game_repo.get_by_slug(slug)
    if game is None or game.user_id != user.user_id:
        raise HTTPException(status_code=404, detail="Game not found.")
    game_service.delete_game(game.customer_game_id, user.user_id)
    return RedirectResponse(url="/games", status_code=303)
