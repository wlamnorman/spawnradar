"""Domain models for the background-built creator index."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SourceAccount:
    """One platform-specific account discovered by the crawler."""

    account_id: str
    platform: str
    external_id: str
    handle_current: str | None
    display_name_current: str | None
    canonical_url: str | None
    account_type: str
    status: str
    first_seen_at: str
    last_seen_at: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class TwitchProfileLatest:
    """Latest stored Twitch state for one source account."""

    account_id: str
    broadcaster_id: str
    login: str
    display_name: str
    description: str | None
    followers_count: int | None
    viewer_count: int | None
    recent_avg_live_viewers: int | None
    recent_median_live_viewers: int | None
    recent_avg_vod_views: int | None
    recent_median_vod_views: int | None
    streams_last_30d: int | None
    language: str | None
    avatar_url: str | None
    last_live_at: str | None
    fetched_at: str
    expires_at: str
    clip_cursor: str | None = None
    clips_exhausted: bool = False


@dataclass(frozen=True)
class YouTubeChannelLatest:
    """Latest stored YouTube channel state for one source account."""

    account_id: str
    channel_id: str
    handle: str | None
    display_name: str
    description: str | None
    subscriber_count: int | None
    video_count: int | None
    recent_avg_views: int | None
    recent_median_views: int | None
    uploads_last_30d: int | None
    default_language: str | None
    country: str | None
    channel_created_at: str | None
    avatar_url: str | None
    uploads_playlist_id: str | None
    last_upload_at: str | None
    fetched_at: str
    expires_at: str
    raw_payload_json: dict[str, Any] | None


@dataclass(frozen=True)
class ContentSample:
    """Latest stored content item used for later matching and UI cards."""

    sample_id: str
    account_id: str
    platform: str
    external_content_id: str
    content_type: str
    title_or_text: str
    body_text: str | None
    url: str | None
    thumbnail_url: str | None
    published_at: str | None
    engagement_count: int | None
    language: str | None
    position_rank: int
    fetched_at: str
    expires_at: str
    raw_payload_json: dict[str, Any] | None


@dataclass(frozen=True)
class CreatorProfileFacetLatest:
    """Derived creator-card data for one indexed account."""

    account_id: str
    platform: str
    summary_text: str
    genre_tags: tuple[str, ...]
    interest_tags: tuple[str, ...]
    language: str | None
    last_activity_at: str | None
    fetched_at: str


@dataclass(frozen=True)
class ContactPoint:
    """Latest public contact route for an indexed account."""

    contact_point_id: str
    account_id: str
    contact_type: str
    contact_value: str
    source_kind: str
    source_url: str | None
    is_public: bool
    first_seen_at: str
    last_seen_at: str
    updated_at: str


@dataclass(frozen=True)
class CrawlJob:
    """One recorded crawl execution for debugging and scheduling state."""

    job_id: str
    platform: str
    job_type: str
    seed_key: str
    status: str
    attempt: int
    started_at: str
    finished_at: str | None
    error_message: str | None
    args_json: dict[str, Any]


@dataclass(frozen=True)
class CrawlCursor:
    """Stored pagination or resume state for one crawl scope."""

    platform: str
    cursor_scope: str
    cursor_key: str
    cursor_value: str
    updated_at: str


@dataclass(frozen=True)
class CrawlSeed:
    """One stored bootstrap discovery seed."""

    seed_id: str
    platform: str
    query_text: str
    seed_kind: str
    status: str
    weight: float
    created_at: str
    updated_at: str
    last_synced_at: str | None


@dataclass(frozen=True)
class TwitchCategoryRecord:
    """One Twitch category, optionally linked to an IGDB game."""

    twitch_category_id: str
    name: str
    box_art_url: str | None
    igdb_game_id: int | None
    last_synced_at: str


@dataclass(frozen=True)
class PlatformSyncSummary:
    """Counts from syncing one platform for one game."""

    platform: str
    accounts_synced: int
    content_samples_synced: int
    contact_points_synced: int
    skipped_reason: str | None = None


@dataclass(frozen=True)
class CustomerGameSyncSummary:
    """Counts from syncing all requested platforms for one game."""

    customer_game_id: str
    customer_game_name: str
    platform_summaries: tuple[PlatformSyncSummary, ...]

    @property
    def accounts_synced(self) -> int:
        return sum(item.accounts_synced for item in self.platform_summaries)

    @property
    def content_samples_synced(self) -> int:
        return sum(
            item.content_samples_synced for item in self.platform_summaries
        )

    @property
    def contact_points_synced(self) -> int:
        return sum(
            item.contact_points_synced for item in self.platform_summaries
        )


@dataclass(frozen=True)
class SweepSyncSummary:
    """Aggregate counts for one scheduled crawler sweep."""

    games_seen: int
    accounts_synced: int
    content_samples_synced: int
    contact_points_synced: int
    game_summaries: tuple[CustomerGameSyncSummary, ...] = ()


@dataclass(frozen=True)
class SeedSyncSummary:
    """Aggregate counts for syncing non-game bootstrap seeds."""

    seeds_seen: int
    accounts_synced: int
    content_samples_synced: int
    contact_points_synced: int


@dataclass(frozen=True)
class CreatorGamePlayed:
    """One game the creator has been observed playing."""

    account_id: str
    game_name_raw: str
    game_name_key: str
    platform: str
    first_seen_at: str
    last_seen_at: str
    observation_count: int
    igdb_game_id: int | None
