"""Typed models for raw data returned by each ingestion source.

These models document exactly what fields each source collects and provide
validation + autocomplete when working with CandidateRecord.raw_data.

Usage
-----
Build a typed model in the source, then serialise to dict for storage:

    data = YouTubeChannelData(channel_id="UC…", video_count=42, …)
    record = CandidateRecord(…, raw_data=data.model_dump())

Reconstruct from a stored dict:

    data = YouTubeChannelData.model_validate(prospect.raw_data)
    print(data.video_count)
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.ingestion.constants import (
    RECENT_TEXT_SIGNAL_LIMIT,
    RECENT_VIDEO_THUMBNAIL_LIMIT,
    RECENT_VIDEO_TITLE_LIMIT,
)


class YouTubeChannelData(BaseModel):
    """Raw data scraped from a YouTube channel search result + videos page."""

    source: Literal["youtube_search"] = "youtube_search"

    # Identifiers
    channel_id: str = Field(
        description="YouTube internal channel ID (UCxxxxxxx)"
    )
    query: str = Field(description="Search query that surfaced this channel")

    # Channel stats
    subscriber_text: str | None = Field(
        default=None,
        description="Raw subscriber count string as shown on YouTube, e.g. '1.2M subscribers'",
    )
    video_count: int | None = Field(
        default=None,
        description="Total number of public videos on the channel",
    )

    # Activity
    last_upload_days_ago: int | None = Field(
        default=None,
        description=(
            "Approximate number of days since the most recent upload, "
            "parsed from the channel's /videos page. None if unavailable."
        ),
    )

    # Search context — which game tag caused this channel to be discovered
    source_genre_tag: str | None = Field(
        default=None,
        description="The game genre tag whose search query surfaced this channel",
    )
    source_mechanics_tag: str | None = Field(
        default=None,
        description="The game mechanics tag whose search query surfaced this channel",
    )
    source_vibe_tag: str | None = Field(
        default=None,
        description="The game vibe tag whose search query surfaced this channel",
    )

    # Images
    avatar_url: str | None = Field(
        default=None,
        description="Channel profile picture URL (highest resolution available from search results)",
    )
    recent_video_thumbnails: list[str] = Field(
        default_factory=list,
        description=(
            f"Thumbnail URLs for the {RECENT_VIDEO_THUMBNAIL_LIMIT} most recent "
            "videos, from the channel's /videos page"
        ),
    )
    recent_video_titles: list[str] = Field(
        default_factory=list,
        description=(
            f"Titles of the {RECENT_VIDEO_TITLE_LIMIT} most recent videos, "
            "from the channel's /videos page"
        ),
    )



class BlueskyActorData(BaseModel):
    """Raw data from a Bluesky actor search result + recent feed enrichment."""

    source: Literal["bluesky_search"] = "bluesky_search"

    did: str = Field(description="Bluesky DID for the actor")
    handle: str = Field(description="Bluesky handle, e.g. alice.bsky.social")
    query: str = Field(description="Search query that surfaced this account")
    followers_count: int | None = Field(
        default=None,
        description="Follower count reported by actor search",
    )
    posts_count: int | None = Field(
        default=None,
        description="Post count reported by actor search",
    )
    avatar_url: str | None = Field(
        default=None,
        description="Profile avatar URL from actor search",
    )
    source_genre_tag: str | None = Field(
        default=None,
        description="The game genre tag whose search query surfaced this account",
    )
    source_mechanics_tag: str | None = Field(
        default=None,
        description="The game mechanics tag whose search query surfaced this account",
    )
    source_vibe_tag: str | None = Field(
        default=None,
        description="The game vibe tag whose search query surfaced this account",
    )
    last_post_days_ago: int | None = Field(
        default=None,
        description="Approximate days since the most recent visible post",
    )
    recent_post_texts: list[str] = Field(
        default_factory=list,
        description=(
            f"Text from the {RECENT_TEXT_SIGNAL_LIMIT} most recent Bluesky "
            "posts used as normalized text signals"
        ),
    )


class TwitchChannelData(BaseModel):
    """Raw data from a Twitch Helix live-channel discovery result."""

    source: Literal["twitch_helix"] = "twitch_helix"

    broadcaster_id: str = Field(description="Twitch broadcaster ID")
    broadcaster_login: str = Field(description="Twitch login name")
    query: str = Field(description="Search query that surfaced this channel")
    game_id: str | None = Field(
        default=None,
        description="Twitch category/game ID for the live stream",
    )
    game_name: str | None = Field(
        default=None,
        description="Twitch category/game name for the live stream",
    )
    stream_title: str | None = Field(
        default=None,
        description="Current live stream title when available",
    )
    is_live: bool = Field(
        default=True,
        description="Whether the channel was live when discovered",
    )
    started_at: str | None = Field(
        default=None,
        description="RFC3339 timestamp of the current live stream start",
    )
    viewer_count: int | None = Field(
        default=None,
        description="Concurrent live viewer count from Get Streams",
    )
    followers_count: int | None = Field(
        default=None,
        description=(
            "Total channel followers from Get Channel Followers. This is "
            "stored separately from viewer_count because Twitch discovery "
            "scoring still uses live audience."
        ),
    )
    broadcaster_language: str | None = Field(
        default=None,
        description="Primary broadcaster language code",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Twitch stream tags returned by Helix",
    )
    avatar_url: str | None = Field(
        default=None,
        description="Broadcaster profile image URL",
    )
    recent_video_thumbnails: list[str] = Field(
        default_factory=list,
        description=(
            "Live preview thumbnails normalized into the same queue-strip field "
            "used by video-first sources"
        ),
    )
    source_genre_tag: str | None = Field(
        default=None,
        description="The game genre tag whose search query surfaced this stream",
    )
    source_mechanics_tag: str | None = Field(
        default=None,
        description="The game mechanics tag whose search query surfaced this stream",
    )
    source_vibe_tag: str | None = Field(
        default=None,
        description="The game vibe tag whose search query surfaced this stream",
    )
