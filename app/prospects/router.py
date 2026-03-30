"""Routes for ranked creator prospects."""

from __future__ import annotations

from typing import cast
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)
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
from app.prospects.models import (
    PROSPECT_WORKFLOW_STATUS_LABELS,
    ProspectWorkflowStatus,
)
from app.prospects.service import ProspectRankingService
from app.security import RateLimitRule, consume_rate_limit

router = APIRouter(tags=["prospects"])

_OVERLAP_FILTER_MAX = 100
_CONTACT_METHOD_OPTIONS = (
    {"value": "email", "label": "Email", "icon_class": "contact-icon--email"},
    {
        "value": "discord",
        "label": "Discord",
        "icon_class": "contact-icon--discord",
    },
    {
        "value": "twitch",
        "label": "Twitch",
        "icon_class": "contact-icon--twitch",
    },
    {
        "value": "youtube",
        "label": "YouTube",
        "icon_class": "contact-icon--youtube",
    },
    {"value": "x", "label": "X / Twitter", "icon_class": "contact-icon--x"},
    {
        "value": "instagram",
        "label": "Instagram",
        "icon_class": "contact-icon--instagram",
    },
    {
        "value": "tiktok",
        "label": "TikTok",
        "icon_class": "contact-icon--tiktok",
    },
    {
        "value": "bluesky",
        "label": "Bluesky",
        "icon_class": "contact-icon--bluesky",
    },
)
_ALL_CONTACT_METHOD_VALUES = tuple(
    str(option["value"]) for option in _CONTACT_METHOD_OPTIONS
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
_STATUS_FILTER_OPTIONS = (
    {"value": "all", "label": "All"},
    {"value": "new", "label": "New"},
    {"value": "contacted", "label": "Contacted"},
    {"value": "replied", "label": "Replied"},
    {"value": "access_shared", "label": "Access Shared"},
    {"value": "covered", "label": "Covered"},
    {"value": "not_pursuing", "label": "Not Pursuing"},
)


def _status_pill_class(status: str) -> str:
    """Map workflow statuses to shared CSS modifier classes."""
    return f"prospect-status--{status}"


def _all_status_total(
    status_counts: dict[ProspectWorkflowStatus, int],
) -> int:
    """Return the default All tab count, excluding Not Pursuing."""
    return sum(
        count
        for status, count in status_counts.items()
        if status != "not_pursuing"
    )


def _safe_int(value: object, default: int) -> int:
    """Parse an integer-like value from a JSON payload safely."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value) if value else default
        except ValueError:
            return default
    return default


@router.get("/games/{slug}/prospects", response_class=HTMLResponse)
def game_prospects_page(
    slug: str,
    request: Request,
    page: int = 1,
    status: str = "all",
    min_reach: int = 0,
    max_reach: int | None = None,
    min_overlap: int = 0,
    max_overlap: int = _OVERLAP_FILTER_MAX,
    min_games: int = 0,
    max_games: int | None = None,
    user: User = Depends(require_product_access),
    billing_service: BillingService = Depends(get_billing_service),
    game_repo: CustomerGameRepository = Depends(get_customer_game_repo),
    settings: Settings = Depends(get_settings),
    templates: Jinja2Templates = Depends(get_templates),
) -> Response:
    """Render ranked creator prospects for a customer game."""
    # Rate limit: generous enough for active filtering and workflow updates.
    allowed = consume_rate_limit(
        settings.db_path,
        "prospects_view",
        [
            RateLimitRule(
                key=f"user:{user.user_id}", limit=40, window_seconds=60
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
    valid_status_filters = {
        option["value"] for option in _STATUS_FILTER_OPTIONS
    }
    if status not in valid_status_filters:
        raise HTTPException(status_code=400, detail="Invalid status filter.")
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
        option["value"] for option in _CONTACT_METHOD_OPTIONS
    }
    requested_reachable_via = tuple(
        value
        for value in request.query_params.getlist("reachable_via")
        if value in valid_contact_methods
    )
    # Keep stable order and remove duplicates.
    requested_reachable_via = tuple(dict.fromkeys(requested_reachable_via))
    if not requested_reachable_via:
        reachable_via = _ALL_CONTACT_METHOD_VALUES
        contact_methods: tuple[str, ...] = ()
    elif set(requested_reachable_via) == set(_ALL_CONTACT_METHOD_VALUES):
        reachable_via = _ALL_CONTACT_METHOD_VALUES
        contact_methods = ()
    else:
        reachable_via = requested_reachable_via
        contact_methods = requested_reachable_via
    if min_reach > max_reach:
        min_reach, max_reach = max_reach, min_reach
    if min_overlap > max_overlap:
        min_overlap, max_overlap = max_overlap, min_overlap
    if min_games > max_games:
        min_games, max_games = max_games, min_games
    filter_params: dict[str, int | str | list[str]] = {}
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
    if contact_methods:
        filter_params["reachable_via"] = list(reachable_via)
    filter_query = urlencode(filter_params, doseq=True)
    navigation_params: dict[str, int | str | list[str]] = dict(filter_params)
    if status != "all":
        navigation_params["status"] = status
    navigation_query = urlencode(navigation_params, doseq=True)
    filter_query_suffix = f"&{navigation_query}" if navigation_query else ""
    subscription = billing_service.get_or_create_subscription(user.user_id)
    if subscription.is_trialing:
        status = "all"
        if page > 1 or filter_query or request.query_params.get("status"):
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
        reachable_via = ()
        filter_params = {}
        filter_query_suffix = ""
    offset = (page - 1) * _PAGE_SIZE

    prospects, total_count, status_counts = service.rank_prospects(
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
        contact_methods=contact_methods,
        status_filter=status,
    )

    status_tab_links: list[dict[str, object]] = []
    for option in _STATUS_FILTER_OPTIONS:
        option_value = str(option["value"])
        count = (
            _all_status_total(status_counts)
            if option_value == "all"
            else int(
                status_counts.get(
                    cast(ProspectWorkflowStatus, option_value),
                    0,
                )
            )
        )
        tab_params: dict[str, int | str | list[str]] = dict(filter_params)
        if option_value != "all":
            tab_params["status"] = option_value
        href_query = urlencode(tab_params, doseq=True)
        href = (
            f"/games/{slug}/prospects?{href_query}"
            if href_query
            else f"/games/{slug}/prospects"
        )
        status_tab_links.append(
            {
                "value": option_value,
                "label": str(option["label"]),
                "count": count,
                "href": href,
                "active": option_value == status,
                "is_empty": count == 0,
            }
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
            "status_pill_class": _status_pill_class,
            "prospect_status_labels": PROSPECT_WORKFLOW_STATUS_LABELS,
            "prospect_status_options": _STATUS_FILTER_OPTIONS[1:-1],
            "status_tab_links": status_tab_links,
            "active_status_filter": status,
            "page": page,
            "total_pages": total_pages,
            "total_count": total_count,
            "page_size": _PAGE_SIZE,
            "trial_page_locked": trial_page_locked,
            "filters_unlocked": not subscription.is_trialing,
            "workflow_unlocked": not subscription.is_trialing,
            "min_reach": min_reach,
            "max_reach": max_reach,
            "default_min_reach": default_min_reach,
            "min_overlap": min_overlap,
            "max_overlap": max_overlap,
            "min_games": min_games,
            "max_games": max_games,
            "reachable_via": reachable_via,
            "contact_method_options": _CONTACT_METHOD_OPTIONS,
            "filters_active": bool(filter_params),
            "reach_filter_active": min_reach > default_min_reach
            or max_reach < reach_filter_max,
            "overlap_filter_active": min_overlap > 0
            or max_overlap < _OVERLAP_FILTER_MAX,
            "games_filter_active": min_games > 0
            or max_games < games_filter_max,
            "contact_filter_active": bool(contact_methods),
            "reach_filter_max": reach_filter_max,
            "overlap_filter_max": _OVERLAP_FILTER_MAX,
            "games_filter_max": games_filter_max,
            "filter_query_suffix": filter_query_suffix,
        },
    )


@router.post("/games/{slug}/prospects/{account_id}/workflow")
async def update_prospect_workflow(
    slug: str,
    account_id: str,
    request: Request,
    user: User = Depends(require_product_access),
    billing_service: BillingService = Depends(get_billing_service),
    game_repo: CustomerGameRepository = Depends(get_customer_game_repo),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """Persist workflow state for a prospect row without a page reload."""
    game = game_repo.get_by_slug(slug)
    if game is None or game.user_id != user.user_id:
        raise HTTPException(status_code=404, detail="Game not found.")
    subscription = billing_service.get_or_create_subscription(user.user_id)
    if subscription.is_trialing:
        raise HTTPException(
            status_code=403,
            detail="Prospect workflow tools require a subscription.",
        )

    payload = await request.json()
    status = cast(ProspectWorkflowStatus, str(payload.get("status") or "new"))
    if status not in PROSPECT_WORKFLOW_STATUS_LABELS:
        raise HTTPException(status_code=400, detail="Invalid prospect status.")
    notes = str(payload.get("notes") or "")

    service = ProspectRankingService(settings.db_path)
    state = service.update_prospect_workflow(
        game,
        account_id=account_id,
        status=status,
        notes=notes,
    )

    active_status = str(payload.get("active_status") or "all")
    if active_status not in {
        option["value"] for option in _STATUS_FILTER_OPTIONS
    }:
        active_status = "all"
    default_min_reach = settings.creator_index_twitch_min_followers
    current_min_reach = max(
        default_min_reach,
        _safe_int(payload.get("min_reach"), default_min_reach),
    )
    current_max_reach_raw = payload.get("max_reach")
    current_min_overlap = max(
        0, min(100, _safe_int(payload.get("min_overlap"), 0))
    )
    current_max_overlap = max(
        0, min(100, _safe_int(payload.get("max_overlap"), 100))
    )
    current_min_games = max(0, _safe_int(payload.get("min_games"), 0))
    current_max_games_raw = payload.get("max_games")
    reachable_via_payload = payload.get("reachable_via") or []
    reachable_via = tuple(
        value
        for value in reachable_via_payload
        if value in {option["value"] for option in _CONTACT_METHOD_OPTIONS}
    )

    reach_filter_max = max(
        default_min_reach,
        service.max_reach(game, min_reach=default_min_reach),
    )
    games_filter_max = max(
        1,
        service.max_relevant_games(game, min_reach=default_min_reach),
    )
    current_max_reach = (
        None
        if current_max_reach_raw in (None, "", reach_filter_max)
        else min(
            reach_filter_max,
            max(0, _safe_int(current_max_reach_raw, reach_filter_max)),
        )
    )
    current_max_games = (
        None
        if current_max_games_raw in (None, "", games_filter_max)
        else min(
            games_filter_max,
            max(0, _safe_int(current_max_games_raw, games_filter_max)),
        )
    )

    _, current_total_count, status_counts = service.rank_prospects(
        game,
        limit=1,
        offset=0,
        min_reach=current_min_reach,
        max_reach=current_max_reach,
        min_overlap_score=current_min_overlap / 100,
        max_overlap_score=current_max_overlap / 100,
        min_relevant_games=current_min_games,
        max_relevant_games=current_max_games,
        contact_methods=reachable_via,
        status_filter=active_status,
    )
    visible = (
        state.status != "not_pursuing"
        if active_status == "all"
        else state.status == active_status
    )
    return JSONResponse(
        {
            "status": state.status,
            "status_label": PROSPECT_WORKFLOW_STATUS_LABELS[state.status],
            "status_class": _status_pill_class(state.status),
            "notes": state.notes,
            "has_notes": state.has_notes,
            "status_counts": {
                **status_counts,
                "all": _all_status_total(status_counts),
            },
            "visible": visible,
            "current_total_count": current_total_count,
        }
    )
