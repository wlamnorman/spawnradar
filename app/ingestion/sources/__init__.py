"""Ingestion source implementations.

Each module registers its source(s) with the registry on import via @register.
Import all source modules here so the registry is populated when pipeline runs.
"""

from app.ingestion.sources import bluesky, reddit, twitch, youtube, youtube_api

__all__ = ["bluesky", "reddit", "twitch", "youtube", "youtube_api"]
