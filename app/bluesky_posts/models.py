"""Domain models for internal Bluesky post drafts."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BlueskyPostDraft:
    """One reviewable internal draft destined for Bluesky."""

    draft_id: str
    customer_game_id: str
    source_game_slug: str
    workspace_id: str
    creator_summary: str
    status: str
    body: str
    hashtags: list[str] = field(default_factory=list)
    creator_handle: str | None = None
    image_filename: str | None = None
    image_media_type: str | None = None
    image_bytes: bytes | None = None
    image_alt_text: str = ""
    created_at: str = ""
    updated_at: str = ""
    reviewed_at: str | None = None
    approved_at: str | None = None
    rejected_at: str | None = None

    @property
    def has_image(self) -> bool:
        return bool(self.image_bytes)
