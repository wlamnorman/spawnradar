"""Routes for ranked creator matches."""

from __future__ import annotations

import logging
import time
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
from app.billing.repository import SubscriptionRepository
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
from app.matches.models import (
    MATCH_WORKFLOW_STATUS_LABELS,
    MATCH_WORKFLOW_STATUS_ORDER,
    MatchWorkflowStatus,
)
from app.matches.service import MatchRankingService
from app.metrics.repository import MetricsRepository
from app.metrics.service import MetricsService
from app.ownership.dependencies import require_ownership_context
from app.ownership.service import OwnershipContext
from app.security import RateLimitRule, client_ip_key, consume_rate_limit

router = APIRouter(tags=["matches"])
log = logging.getLogger(__name__)

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


_PAGE_SIZE = 20
_DEFAULT_MATCHES_MIN_REACH = 250
_STATUS_FILTER_OPTIONS = (
    {"value": "all", "label": "All"},
    {"value": "suggested", "label": "Suggested"},
    {"value": "to_contact", "label": "To Contact"},
    {"value": "contacted", "label": "Contacted"},
    {"value": "replied", "label": "Replied"},
    {"value": "to_cover", "label": "To Cover"},
    {"value": "covered", "label": "Covered"},
    {"value": "not_pursuing", "label": "Not Pursuing"},
)
_LEGACY_STATUS_FILTERS = {
    "new": "suggested",
    "access_shared": "to_cover",
}


def _normalize_status_filter(status: str) -> str:
    """Map legacy workflow status values to the current public values."""
    return _LEGACY_STATUS_FILTERS.get(status, status)


def _status_pill_class(status: str) -> str:
    """Map workflow statuses to shared CSS modifier classes."""
    return f"match-status--{status}"


def _all_status_total(
    status_counts: dict[MatchWorkflowStatus, int],
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


def _matches_reach_floor(settings: Settings) -> int:
    """Return the minimum allowed reach filter value."""
    return max(0, settings.creator_index_twitch_min_followers)


def _matches_default_min_reach(settings: Settings) -> int:
    """Return the default reach filter value shown on the matches page."""
    return max(_matches_reach_floor(settings), _DEFAULT_MATCHES_MIN_REACH)


@router.get("/games/{slug}/matches", response_class=HTMLResponse)
def game_matches_page(
    slug: str,
    request: Request,
    page: int = 1,
    status: str = "all",
    min_reach: int | None = None,
    max_reach: int | None = None,
    min_games: int = 0,
    max_games: int | None = None,
    ownership: OwnershipContext = Depends(require_ownership_context),
    game_repo: CustomerGameRepository = Depends(get_customer_game_repo),
    settings: Settings = Depends(get_settings),
    templates: Jinja2Templates = Depends(get_templates),
) -> Response:
    """Render ranked creator matches for a customer game."""
    user = ownership.require_actor()
    started_at = time.perf_counter()
    # Rate limit: generous enough for active filtering and workflow updates.
    if user.is_anonymous:
        rules = [
            RateLimitRule(
                key=client_ip_key(request), limit=20, window_seconds=60
            )
        ]
    elif not user.is_admin:
        rules = [
            RateLimitRule(
                key=f"user:{user.user_id}", limit=40, window_seconds=60
            )
        ]
    else:
        rules = []
    if rules and not consume_rate_limit(
        settings.db_path, "matches_page", rules
    ):
        raise HTTPException(status_code=429, detail="Too many requests.")

    game = game_repo.get_by_slug(slug)
    if game is None or not ownership.can_access_workspace(game.workspace_id):
        raise HTTPException(status_code=404, detail="Game not found.")

    # Record page view metric (best-effort)
    try:
        MetricsService(
            MetricsRepository(settings.db_path),
            SubscriptionRepository(settings.db_path),
        ).record_match_page_viewed(
            user_id=user.user_id,
            workspace_id=user.workspace_id,
            customer_game_id=game.customer_game_id,
        )
    except Exception:
        log.warning("Failed to record match page view metric", exc_info=True)

    status = _normalize_status_filter(status)
    service = MatchRankingService(settings.db_path)
    valid_status_filters = {
        option["value"] for option in _STATUS_FILTER_OPTIONS
    }
    if status not in valid_status_filters:
        raise HTTPException(status_code=400, detail="Invalid status filter.")
    reach_floor = _matches_reach_floor(settings)
    default_min_reach = _matches_default_min_reach(settings)

    is_limited = ownership.is_limited

    if min_reach is None:
        min_reach = default_min_reach
    else:
        min_reach = max(reach_floor, min_reach)

    page = max(1, page)
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

    offset = (page - 1) * _PAGE_SIZE

    matches, total_count, status_counts, raw_reach_max, raw_games_max = (
        service.rank_matches(
            game,
            limit=_PAGE_SIZE,
            offset=offset,
            min_reach=min_reach,
            max_reach=max_reach,
            min_relevant_games=min_games,
            max_relevant_games=max_games,
            contact_methods=contact_methods,
            status_filter=status,
        )
    )

    # Keep the reach control usable even when the default threshold filters
    # everything out.
    reach_filter_max = max(reach_floor, default_min_reach, raw_reach_max)
    games_filter_max = max(1, raw_games_max)

    # Clamp filter values for template display.
    if max_reach is None:
        max_reach = reach_filter_max
    else:
        max_reach = min(reach_filter_max, max(0, max_reach))
    if max_games is None:
        max_games = games_filter_max
    else:
        max_games = min(games_filter_max, max(0, max_games))
    min_games = max(0, min_games)

    if min_reach > max_reach:
        min_reach, max_reach = max_reach, min_reach
    if min_games > max_games:
        min_games, max_games = max_games, min_games

    filter_params: dict[str, int | str | list[str]] = {}
    if min_reach != default_min_reach:
        filter_params["min_reach"] = min_reach
    if max_reach < reach_filter_max:
        filter_params["max_reach"] = max_reach
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

    if is_limited:
        status = "all"
        if page > 1 or filter_query or request.query_params.get("status"):
            return RedirectResponse(
                url=f"/games/{slug}/matches",
                status_code=303,
            )
        min_reach = default_min_reach
        max_reach = reach_filter_max
        min_games = 0
        max_games = games_filter_max
        reachable_via = ()
        filter_params = {}
        filter_query_suffix = ""
    log.info(
        "[matches] GET slug=%s user_id=%s page=%s status=%s total=%s rendered=%s elapsed_ms=%.1f",
        slug,
        user.user_id or user.guest_id,
        page,
        status,
        total_count,
        len(matches),
        (time.perf_counter() - started_at) * 1000,
    )

    status_tab_links: list[dict[str, object]] = []
    for option in _STATUS_FILTER_OPTIONS:
        option_value = str(option["value"])
        count = (
            _all_status_total(status_counts)
            if option_value == "all"
            else int(
                status_counts.get(
                    cast(MatchWorkflowStatus, option_value),
                    0,
                )
            )
        )
        tab_params: dict[str, int | str | list[str]] = dict(filter_params)
        if option_value != "all":
            tab_params["status"] = option_value
        href_query = urlencode(tab_params, doseq=True)
        href = (
            f"/games/{slug}/matches?{href_query}"
            if href_query
            else f"/games/{slug}/matches"
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
    page_locked = is_limited and total_count > _PAGE_SIZE

    return templates.TemplateResponse(
        request,
        "games/matches.html",
        {
            "user": user,
            "game": game,
            "matches": matches,
            "tag_label": _tag_label,
            "tag_pill_class": _tag_pill_class,
            "tag_observation_title": _tag_observation_title,
            "status_pill_class": _status_pill_class,
            "match_status_labels": MATCH_WORKFLOW_STATUS_LABELS,
            "match_status_names": MATCH_WORKFLOW_STATUS_ORDER,
            "match_status_options": _STATUS_FILTER_OPTIONS[1:-1],
            "status_tab_links": status_tab_links,
            "active_status_filter": status,
            "page": page,
            "total_pages": total_pages,
            "total_count": total_count,
            "page_size": _PAGE_SIZE,
            "page_locked": page_locked,
            "filters_unlocked": not is_limited,
            "workflow_unlocked": not is_limited,
            "min_reach": min_reach,
            "max_reach": max_reach,
            "default_min_reach": default_min_reach,
            "reach_filter_floor": reach_floor,
            "min_games": min_games,
            "max_games": max_games,
            "reachable_via": reachable_via,
            "contact_method_options": _CONTACT_METHOD_OPTIONS,
            "filters_active": bool(filter_params),
            "reach_filter_active": min_reach != default_min_reach
            or max_reach < reach_filter_max,
            "games_filter_active": min_games > 0
            or max_games < games_filter_max,
            "contact_filter_active": bool(contact_methods),
            "reach_filter_max": reach_filter_max,
            "games_filter_max": games_filter_max,
            "filter_query_suffix": filter_query_suffix,
        },
    )


@router.post("/games/{slug}/matches/{account_id}/workflow")
async def update_match_workflow(
    slug: str,
    account_id: str,
    request: Request,
    user: User = Depends(require_product_access),
    billing_service: BillingService = Depends(get_billing_service),
    game_repo: CustomerGameRepository = Depends(get_customer_game_repo),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """Persist workflow state for a match row without a page reload."""
    started_at = time.perf_counter()
    game = game_repo.get_by_slug(slug)
    if game is None or (game.user_id != user.user_id and not user.is_admin):
        raise HTTPException(status_code=404, detail="Game not found.")
    if not user.is_admin:
        subscription = billing_service.get_subscription(user.user_id)
        if subscription is None or not subscription.has_access:
            raise HTTPException(
                status_code=403,
                detail="Match workflow tools require a subscription.",
            )

    payload = await request.json()
    status = cast(
        MatchWorkflowStatus,
        _normalize_status_filter(str(payload.get("status") or "suggested")),
    )
    if status not in MATCH_WORKFLOW_STATUS_LABELS:
        raise HTTPException(status_code=400, detail="Invalid match status.")
    notes = str(payload.get("notes") or "")

    service = MatchRankingService(settings.db_path)
    state = service.update_match_workflow(
        game,
        account_id=account_id,
        status=status,
        notes=notes,
    )

    active_status = _normalize_status_filter(
        str(payload.get("active_status") or "all")
    )
    if active_status not in {
        option["value"] for option in _STATUS_FILTER_OPTIONS
    }:
        active_status = "all"
    reach_floor = _matches_reach_floor(settings)
    default_min_reach = _matches_default_min_reach(settings)
    current_min_reach_raw = payload.get("min_reach")
    if current_min_reach_raw in (None, ""):
        current_min_reach = default_min_reach
    else:
        current_min_reach = max(
            reach_floor,
            _safe_int(current_min_reach_raw, default_min_reach),
        )
    current_max_reach_raw = payload.get("max_reach")
    current_min_games = max(0, _safe_int(payload.get("min_games"), 0))
    current_max_games_raw = payload.get("max_games")
    reachable_via_payload = payload.get("reachable_via") or []
    reachable_via = tuple(
        value
        for value in reachable_via_payload
        if value in {option["value"] for option in _CONTACT_METHOD_OPTIONS}
    )

    current_max_reach = (
        None
        if current_max_reach_raw in (None, "")
        else max(0, _safe_int(current_max_reach_raw, 0))
    )
    current_max_games = (
        None
        if current_max_games_raw in (None, "")
        else max(0, _safe_int(current_max_games_raw, 0))
    )

    current_total_count, status_counts = service.count_ranked_matches(
        game,
        min_reach=current_min_reach,
        max_reach=current_max_reach,
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
    log.info(
        "[matches] workflow slug=%s user_id=%s account_id=%s status=%s active_status=%s visible=%s total=%s elapsed_ms=%.1f",
        slug,
        user.user_id,
        account_id,
        state.status,
        active_status,
        visible,
        current_total_count,
        (time.perf_counter() - started_at) * 1000,
    )
    return JSONResponse(
        {
            "status": state.status,
            "status_label": MATCH_WORKFLOW_STATUS_LABELS[state.status],
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
