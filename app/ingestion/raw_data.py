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
    source_audience_tag: str | None = Field(
        default=None,
        description="The game audience tag whose search query surfaced this channel",
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


class RedditSubredditData(BaseModel):
    """Raw data from a Reddit subreddit search result."""

    source: Literal["reddit_search"] = "reddit_search"

    subreddit_name: str = Field(
        description="Subreddit name without the r/ prefix"
    )
    title: str = Field(description="Human-readable subreddit title")
    over18: bool = Field(
        default=False, description="Whether the subreddit is NSFW"
    )


class RedditThreadData(BaseModel):
    """Raw data from a Reddit post/thread search result."""

    source: Literal["reddit_search"] = "reddit_search"

    post_id: str = Field(description="Reddit post ID (base-36 string)")
    subreddit: str = Field(
        description="Subreddit the post lives in, without r/"
    )
    author: str = Field(description="Reddit username of the post author")
    score: int = Field(description="Net upvote score of the post")
    num_comments: int = Field(description="Number of comments on the post")
    permalink: str = Field(
        description="Relative Reddit permalink, e.g. /r/foo/comments/…"
    )
