"""Presentation helpers for the review queue."""

from __future__ import annotations

from dataclasses import replace
from typing import TypedDict

from app.ingestion.constants import RECENT_VIDEO_THUMBNAIL_LIMIT
from app.prospects.models import ReviewQueueItem

_HIDDEN_REASON_PREFIXES = (
    "Contact channel available:",
    "Contact value present:",
)


class QueueItemPayload(TypedDict):
    draft_item_id: str
    prospect_id: str
    platform: str
    handle: str
    display_name: str
    profile_url: str | None
    contact_channel: str | None
    contact_value: str | None
    audience_size: int | None
    followers_count: int | None
    avatar_url: str | None
    recent_video_thumbnails: list[str]
    status: str
    priority_score: float
    fit_summary: str | None
    subject_line: str | None
    body_text: str
    score_breakdown: dict


class ReviewQueuePresenter:
    """Presents queue items for HTML templates and API payloads."""

    def __init__(
        self, thumbnail_limit: int = RECENT_VIDEO_THUMBNAIL_LIMIT
    ) -> None:
        self._thumbnail_limit = thumbnail_limit

    def for_template(
        self, items: list[ReviewQueueItem]
    ) -> list[ReviewQueueItem]:
        """Return queue items sanitized for template rendering."""
        return [self._sanitize_item(item) for item in items]

    def for_api(self, items: list[ReviewQueueItem]) -> list[QueueItemPayload]:
        """Return queue items as JSON-ready payload dictionaries."""
        payload: list[QueueItemPayload] = []
        for item in self.for_template(items):
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
                    "contact_value": item.prospect.contact_value,
                    "audience_size": item.prospect.audience_size,
                    "followers_count": _raw_int(raw, "followers_count"),
                    "avatar_url": raw.get("avatar_url"),
                    "recent_video_thumbnails": _recent_thumbnails(
                        raw, self._thumbnail_limit
                    ),
                    "status": item.draft.status,
                    "priority_score": item.draft.priority_score,
                    "fit_summary": item.draft.fit_summary,
                    "subject_line": item.draft.subject_line,
                    "body_text": item.draft.body_text,
                    "score_breakdown": item.draft.score_breakdown,
                }
            )
        return payload

    def _sanitize_item(self, item: ReviewQueueItem) -> ReviewQueueItem:
        """Hide stale internal score reasons from stored queue items."""
        return replace(
            item,
            draft=replace(
                item.draft,
                score_breakdown=_sanitize_score_breakdown(
                    item.draft.score_breakdown
                ),
            ),
        )


def _sanitize_score_breakdown(score_breakdown: dict) -> dict:
    """Remove internal contactability details from displayed score reasons."""
    reasons = score_breakdown.get("reasons")
    if not isinstance(reasons, list):
        return score_breakdown

    filtered_reasons = [
        reason
        for reason in reasons
        if isinstance(reason, str)
        and not reason.startswith(_HIDDEN_REASON_PREFIXES)
    ]
    if filtered_reasons == reasons:
        return score_breakdown

    return {**score_breakdown, "reasons": filtered_reasons}


def _recent_thumbnails(raw_data: dict, limit: int) -> list[str]:
    """Return the limited recent thumbnail strip for a prospect."""
    value = raw_data.get("recent_video_thumbnails")
    if not isinstance(value, list):
        return []
    return [thumb for thumb in value[:limit] if isinstance(thumb, str)]


def _raw_int(raw_data: dict, key: str) -> int | None:
    """Read an integer from stored raw prospect data when present."""
    value = raw_data.get(key)
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool)
        else None
    )
