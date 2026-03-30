"""Routes for ranked creator prospects."""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.auth.dependencies import require_product_access
from app.auth.models import User
from app.billing.service import BillingService
from app.config import Settings
from app.dependencies import (
    get_billing_service,
    get_customer_game_repo,
    get_settings,
    get_templates,
)
from app.games.repository import CustomerGameRepository
from app.igdb.taxonomy import IGDBGenre, IGDBTheme, keyword_label_for_value
from app.prospects.service import ProspectRankingService
from app.security import RateLimitRule, consume_rate_limit

router = APIRouter(tags=["prospects"])

_OVERLAP_FILTER_MAX = 100
_CONTACT_METHOD_OPTIONS = (
    ("", "Any"),
    ("email", "Email"),
    ("discord", "Discord"),
    ("twitch", "Twitch"),
    ("youtube", "YouTube"),
    ("x", "X / Twitter"),
    ("instagram", "Instagram"),
    ("bluesky", "Bluesky"),
)


def _tag_label(tag_type: str, tag_id: int | str) -> str:
    """Convert a (tag_type, tag_id) pair to a human-readable label."""
    if tag_type == "genre" and isinstance(tag_id, int):
        labels = IGDBGenre.labels_for_ids([tag_id])
        return labels[0] if labels else f"{tag_type}:{tag_id}"
    if tag_type == "theme" and isinstance(tag_id, int):
        labels = IGDBTheme.labels_for_ids([tag_id])
        return labels[0] if labels else f"{tag_type}:{tag_id}"
    if isinstance(tag_id, str):
        label = keyword_label_for_value(tag_id)
        if label is not None:
            return label
    return f"{tag_type}:{tag_id}"


def _tag_pill_class(tag_type: str) -> str:
    """Return the shared tag pill class for a tag group."""
    if tag_type == "genre":
        return "tag-genre"
    if tag_type == "theme":
        return "tag-theme"
    if tag_type == "mechanic":
        return "tag-mechanic"
    return ""


def _tag_observation_title(observed_game_count: int) -> str:
    """Return hover copy describing how many played games support a tag."""
    if observed_game_count == 1:
        return "Observed in 1 played game"
    return f"Observed in {observed_game_count} played games"


_PAGE_SIZE = 50


@router.get("/games/{slug}/prospects", response_class=HTMLResponse)
def game_prospects_page(
    slug: str,
    request: Request,
    page: int = 1,
    min_reach: int = 0,
    max_reach: int | None = None,
    min_overlap: int = 0,
    max_overlap: int = _OVERLAP_FILTER_MAX,
    min_games: int = 0,
    max_games: int | None = None,
    contact_method: str = "",
    user: User = Depends(require_product_access),
    billing_service: BillingService = Depends(get_billing_service),
    game_repo: CustomerGameRepository = Depends(get_customer_game_repo),
    settings: Settings = Depends(get_settings),
    templates: Jinja2Templates = Depends(get_templates),
) -> Response:
    """Render ranked creator prospects for a customer game."""
    # Rate limit: 10 requests/minute per user (generous for page browsing)
    allowed = consume_rate_limit(
        settings.db_path,
        "prospects_view",
        [
            RateLimitRule(
                key=f"user:{user.user_id}", limit=10, window_seconds=60
            )
        ],
    )
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many requests.")

    game = game_repo.get_by_slug(slug)
    if game is None or game.user_id != user.user_id:
        raise HTTPException(status_code=404, detail="Game not found.")

    # Record page view metric (best-effort)
    try:
        from app.billing.repository import SubscriptionRepository
        from app.metrics.repository import MetricsRepository
        from app.metrics.service import MetricsService

        MetricsService(
            MetricsRepository(settings.db_path),
            SubscriptionRepository(settings.db_path),
        ).record_prospect_page_viewed(
            user_id=user.user_id,
            customer_game_id=game.customer_game_id,
        )
    except Exception:
        pass

    service = ProspectRankingService(settings.db_path)
    default_min_reach = settings.creator_index_twitch_min_followers
    reach_filter_max = max(
        default_min_reach,
        service.max_reach(game, min_reach=default_min_reach),
    )
    games_filter_max = max(
        1,
        service.max_relevant_games(game, min_reach=default_min_reach),
    )
    page = max(1, page)
    min_reach = max(default_min_reach, min_reach)
    max_reach = reach_filter_max if max_reach is None else max(0, max_reach)
    max_reach = min(reach_filter_max, max_reach)
    min_overlap = max(0, min(_OVERLAP_FILTER_MAX, min_overlap))
    max_overlap = max(0, min(_OVERLAP_FILTER_MAX, max_overlap))
    min_games = max(0, min_games)
    max_games = games_filter_max if max_games is None else max(0, max_games)
    max_games = min(games_filter_max, max_games)
    valid_contact_methods = {
        value for value, _ in _CONTACT_METHOD_OPTIONS if value
    }
    contact_method = (
        contact_method if contact_method in valid_contact_methods else ""
    )
    if min_reach > max_reach:
        min_reach, max_reach = max_reach, min_reach
    if min_overlap > max_overlap:
        min_overlap, max_overlap = max_overlap, min_overlap
    if min_games > max_games:
        min_games, max_games = max_games, min_games
    filter_params: dict[str, int | str] = {}
    if min_reach > default_min_reach:
        filter_params["min_reach"] = min_reach
    if max_reach < reach_filter_max:
        filter_params["max_reach"] = max_reach
    if min_overlap > 0:
        filter_params["min_overlap"] = min_overlap
    if max_overlap < _OVERLAP_FILTER_MAX:
        filter_params["max_overlap"] = max_overlap
    if min_games > 0:
        filter_params["min_games"] = min_games
    if max_games < games_filter_max:
        filter_params["max_games"] = max_games
    if contact_method:
        filter_params["contact_method"] = contact_method
    filter_query = urlencode(filter_params)
    filter_query_suffix = f"&{filter_query}" if filter_query else ""
    subscription = billing_service.get_or_create_subscription(user.user_id)
    if subscription.is_trialing:
        if page > 1 or filter_query:
            return RedirectResponse(
                url=f"/games/{slug}/prospects",
                status_code=303,
            )
        min_reach = default_min_reach
        max_reach = reach_filter_max
        min_overlap = 0
        max_overlap = _OVERLAP_FILTER_MAX
        min_games = 0
        max_games = games_filter_max
        contact_method = ""
        filter_params = {}
        filter_query_suffix = ""
    offset = (page - 1) * _PAGE_SIZE

    prospects, total_count = service.rank_prospects(
        game,
        limit=_PAGE_SIZE,
        offset=offset,
        min_reach=min_reach,
        max_reach=(max_reach if max_reach < reach_filter_max else None),
        min_overlap_score=min_overlap / 100,
        max_overlap_score=max_overlap / 100,
        min_relevant_games=min_games,
        max_relevant_games=(
            max_games if max_games < games_filter_max else None
        ),
        contact_method=(contact_method or None),
    )

    total_pages = (
        (total_count + _PAGE_SIZE - 1) // _PAGE_SIZE if total_count > 0 else 1
    )
    trial_page_locked = subscription.is_trialing and total_count > _PAGE_SIZE

    return templates.TemplateResponse(
        request,
        "games/prospects.html",
        {
            "user": user,
            "game": game,
            "prospects": prospects,
            "tag_label": _tag_label,
            "tag_pill_class": _tag_pill_class,
            "tag_observation_title": _tag_observation_title,
            "page": page,
            "total_pages": total_pages,
            "total_count": total_count,
            "page_size": _PAGE_SIZE,
            "trial_page_locked": trial_page_locked,
            "filters_unlocked": not subscription.is_trialing,
            "min_reach": min_reach,
            "max_reach": max_reach,
            "default_min_reach": default_min_reach,
            "min_overlap": min_overlap,
            "max_overlap": max_overlap,
            "min_games": min_games,
            "max_games": max_games,
            "contact_method": contact_method,
            "contact_method_options": _CONTACT_METHOD_OPTIONS,
            "filters_active": bool(filter_params),
            "reach_filter_active": min_reach > default_min_reach
            or max_reach < reach_filter_max,
            "overlap_filter_active": min_overlap > 0
            or max_overlap < _OVERLAP_FILTER_MAX,
            "games_filter_active": min_games > 0
            or max_games < games_filter_max,
            "contact_filter_active": bool(contact_method),
            "reach_filter_max": reach_filter_max,
            "overlap_filter_max": _OVERLAP_FILTER_MAX,
            "games_filter_max": games_filter_max,
            "filter_query_suffix": filter_query_suffix,
        },
    )
