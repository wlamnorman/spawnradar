"""Abstract base class and shared constants for prospect candidate sources."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.games.models import Game


@dataclass(frozen=True)
class CandidateRecord:
    """A raw discovered prospect before it's persisted to the database."""

    platform: str  # youtube | reddit
    handle: str  # unique identifier on the platform
    display_name: str
    profile_url: str | None
    contact_channel: str | None
    contact_value: str | None  # e.g. email address if found in description
    audience_size: int | None
    engagement_rate: float | None
    description: str | None
    raw_data: dict  # all scraped fields for future use


@dataclass(frozen=True)
class YouTubeConfig:
    """Hard-filter thresholds applied during YouTube channel discovery."""

    min_subscribers: int = 500  # ghost channels with no audience
    max_subscribers: int = (
        500_000  # mega channels won't respond to indie pitches
    )
    min_video_count: int = 10  # stub/abandoned channels
    max_inactive_days: int = 90  # channels with no upload in the last 3 months


DEFAULT_YOUTUBE_CONFIG = YouTubeConfig()


class CandidateSource(ABC):
    """Abstract source that discovers prospect candidates for a game."""

    @abstractmethod
    async def discover(self, game: Game, limit: int) -> list[CandidateRecord]:
        """Discover and return up to *limit* candidates relevant to *game*."""
        ...
