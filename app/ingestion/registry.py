"""Source registry: maps source names to CandidateSource implementations.

New sources self-register by decorating their class with @register(Source.NAME):

    from app.ingestion.registry import Source, register

    @register(Source.BLUESKY)
    class BlueskySource(CandidateSource):
        ...

Add a new member to Source at the same time so callers get a typed constant
instead of a bare string. Because Source inherits from str, values serialize
to/from JSON and SQLite transparently.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from app.ingestion.base import CandidateSource

_T = TypeVar("_T", bound="CandidateSource")


class Source(StrEnum):
    """Canonical names for all supported ingestion sources."""

    YOUTUBE_API = "youtube_api"  # YouTube Data API v3 (quota-limited)
    YOUTUBE = "youtube"  # YouTube scraping fallback
    REDDIT = "reddit"  # Reddit public JSON API
    BLUESKY = "bluesky"  # Bluesky public API


DEFAULT_DISCOVERY_SOURCES = [
    Source.YOUTUBE,
    Source.REDDIT,
    Source.BLUESKY,
]


_SOURCES: dict[Source, type[CandidateSource]] = {}


def register(name: Source):
    """Class decorator that registers a CandidateSource under *name*."""

    def decorator(cls: type[_T]) -> type[_T]:
        _SOURCES[name] = cls
        return cls

    return decorator


def get_source(name: Source) -> type[CandidateSource]:
    """Return the CandidateSource class registered under *name*.

    Raises KeyError with a helpful message if the name is unknown.
    """
    if name not in _SOURCES:
        raise KeyError(
            f"Unknown ingestion source: {name!r}. "
            f"Available: {sorted(_SOURCES)}"
        )
    return _SOURCES[name]


def available_sources() -> list[Source]:
    """Return all registered source names."""
    return sorted(_SOURCES)
