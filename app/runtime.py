"""Shared runtime configuration for platform API adapters."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceRuntime:
    """Runtime config passed to source constructors."""

    youtube_api_key: str = ""
    youtube_cache_dir: str = ""
    twitch_client_id: str = ""
    twitch_client_secret: str = ""
