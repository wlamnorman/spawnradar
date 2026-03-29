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

_REACH_FILTER_MAX = 2_000_000
_OVERLAP_FILTER_MAX = 100


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


_PAGE_SIZE = 50


@router.get("/games/{slug}/prospects", response_class=HTMLResponse)
def game_prospects_page(
    slug: str,
    request: Request,
    page: int = 1,
    min_reach: int = 0,
    max_reach: int = _REACH_FILTER_MAX,
    min_overlap: int = 0,
    max_overlap: int = _OVERLAP_FILTER_MAX,
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

    page = max(1, page)
    min_reach = max(0, min_reach)
    max_reach = max(0, min(_REACH_FILTER_MAX, max_reach))
    min_overlap = max(0, min(_OVERLAP_FILTER_MAX, min_overlap))
    max_overlap = max(0, min(_OVERLAP_FILTER_MAX, max_overlap))
    if min_reach > max_reach:
        min_reach, max_reach = max_reach, min_reach
    if min_overlap > max_overlap:
        min_overlap, max_overlap = max_overlap, min_overlap
    filter_params: dict[str, int] = {}
    if min_reach > 0:
        filter_params["min_reach"] = min_reach
    if max_reach < _REACH_FILTER_MAX:
        filter_params["max_reach"] = max_reach
    if min_overlap > 0:
        filter_params["min_overlap"] = min_overlap
    if max_overlap < _OVERLAP_FILTER_MAX:
        filter_params["max_overlap"] = max_overlap
    filter_query = urlencode(filter_params)
    filter_query_suffix = f"&{filter_query}" if filter_query else ""
    subscription = billing_service.get_or_create_subscription(user.user_id)
    if subscription.is_trialing:
        if page > 1 or filter_query:
            return RedirectResponse(
                url=f"/games/{slug}/prospects",
                status_code=303,
            )
        min_reach = 0
        max_reach = _REACH_FILTER_MAX
        min_overlap = 0
        max_overlap = _OVERLAP_FILTER_MAX
        filter_params = {}
        filter_query_suffix = ""
    offset = (page - 1) * _PAGE_SIZE

    service = ProspectRankingService(settings.db_path)
    prospects, total_count = service.rank_prospects(
        game,
        limit=_PAGE_SIZE,
        offset=offset,
        min_reach=min_reach,
        max_reach=(max_reach if max_reach < _REACH_FILTER_MAX else None),
        min_overlap_score=min_overlap / 100,
        max_overlap_score=max_overlap / 100,
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
            "page": page,
            "total_pages": total_pages,
            "total_count": total_count,
            "page_size": _PAGE_SIZE,
            "trial_page_locked": trial_page_locked,
            "filters_unlocked": not subscription.is_trialing,
            "min_reach": min_reach,
            "max_reach": max_reach,
            "min_overlap": min_overlap,
            "max_overlap": max_overlap,
            "filters_active": bool(filter_params),
            "reach_filter_active": min_reach > 0
            or max_reach < _REACH_FILTER_MAX,
            "overlap_filter_active": min_overlap > 0
            or max_overlap < _OVERLAP_FILTER_MAX,
            "reach_filter_max": _REACH_FILTER_MAX,
            "overlap_filter_max": _OVERLAP_FILTER_MAX,
            "filter_query_suffix": filter_query_suffix,
        },
    )
