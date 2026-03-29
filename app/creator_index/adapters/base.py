"""Base adapter contract for source-index platform crawlers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.runtime import SourceRuntime


@dataclass(frozen=True)
class SourceAccountSeed:
    """Canonical shared fields for one platform account."""

    external_id: str
    handle_current: str | None
    display_name_current: str | None
    canonical_url: str | None
    account_type: str = "creator"
    status: str = "active"


@dataclass(frozen=True)
class ContentSampleSeed:
    """One recent content item associated with an indexed account."""

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
    raw_payload_json: dict[str, Any] | None = None


class ContactType(StrEnum):
    """Known contact-point categories stored in the creator index."""

    EMAIL = "email"
    DISCORD = "discord"
    SOCIAL_LINK = "social_link"


@dataclass(frozen=True)
class ContactPointSeed:
    """One extracted public contact route for an indexed account."""

    contact_type: ContactType
    contact_value: str
    source_kind: str
    source_url: str | None
    is_public: bool = True


@dataclass(frozen=True)
class ObservedGameSeed:
    """One platform game/category observed from a creator account."""

    game_name: str
    platform_game_id: str | None = None


@dataclass(frozen=True)
class TwitchProfileSeed:
    """Latest useful Twitch state for one indexed account."""

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
    games_played: tuple[str, ...]   # game names seen in stream/channel data
    avatar_url: str | None
    last_live_at: str | None
    fetched_at: str
    expires_at: str
    clip_cursor: str | None = None
    clips_exhausted: bool = False


@dataclass(frozen=True)
class YouTubeChannelSeed:
    """Latest useful YouTube state for one indexed account."""

    channel_id: str
    handle: str | None
    display_name: str
    description: str | None
    subscriber_count: int | None
    video_count: int | None
    recent_avg_views: int | None
    recent_median_views: int | None
    uploads_last_30d: int | None
    default_language: str | None    # BCP-47 code derived from channel or videos
    country: str | None
    channel_created_at: str | None
    avatar_url: str | None
    uploads_playlist_id: str | None
    last_upload_at: str | None
    fetched_at: str
    expires_at: str
    raw_payload_json: dict[str, Any] | None = None


@dataclass(frozen=True)
class AccountSeedBundle:
    """Full persisted payload for one discovered account."""

    account: SourceAccountSeed
    platform_profile: TwitchProfileSeed | YouTubeChannelSeed
    content_samples: tuple[ContentSampleSeed, ...] = ()
    contact_points: tuple[ContactPointSeed, ...] = ()
    observed_games: tuple[ObservedGameSeed, ...] = ()


class AccountSeedAdapter(ABC):
    """Platform-specific crawler used by the background creator index."""

    platform: str

    @classmethod
    @abstractmethod
    def build(cls, runtime: SourceRuntime) -> AccountSeedAdapter:
        """Construct an adapter from shared runtime credentials."""
