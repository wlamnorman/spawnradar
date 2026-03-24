"""Prospect domain models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Prospect:
    """A discovered marketing prospect (YouTube channel or Twitch streamer)."""

    prospect_id: str
    platform: str  # youtube | twitch | bluesky
    handle: str
    display_name: str
    profile_url: str | None
    contact_channel: str | None
    contact_value: str | None
    audience_size: int | None
    engagement_rate: float | None
    description: str | None
    raw_data: dict
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class DraftItem:
    """A generated outreach draft awaiting developer review."""

    draft_item_id: str
    game_id: str
    prospect_id: str
    template_id: str | None
    subject_line: str | None
    body_text: str
    status: str  # queued | approved | rejected | snoozed | sent
    priority_score: float
    fit_summary: str | None
    score_breakdown: dict  # deserialized from JSON
    last_edited_at: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Outcome:
    """Records the result of a developer action on a draft item."""

    outcome_id: str
    draft_item_id: str
    outcome_type: str  # approved | rejected | snoozed | sent
    notes: str | None
    created_at: str


@dataclass(frozen=True)
class ReviewQueueItem:
    """A combined view of a DraftItem with its associated Prospect."""

    draft: DraftItem
    prospect: Prospect
