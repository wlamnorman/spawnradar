"""Backward-compatible wrapper around shared Steam tag mapping rules."""

from __future__ import annotations

from app.steam_enrichment.tag_mapping import (
    SteamSetupFieldMapping as SteamTagMappingResult,
)
from app.steam_enrichment.tag_mapping import (
    map_steam_tags_to_setup_fields,
)

__all__ = ["SteamTagMappingResult", "map_steam_tags_to_setup_fields"]
