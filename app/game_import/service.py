"""Service layer for the standalone game-import subsystem.

The service is the only object callers should need. It loads built-in adapters,
selects the right adapter for a URL, and returns a reviewable import preview.
No persistence and no setup-flow integration happen here.
"""

from __future__ import annotations

from functools import lru_cache

from app.game_import.models import ImportedGamePreview
from app.game_import.registry import build_registered_adapters, match_adapter


@lru_cache(maxsize=1)
def _load_builtin_adapters() -> None:
    """Import built-in adapter modules exactly once so they self-register."""
    from app.game_import import steam  # noqa: F401


class GameImportService:
    """Selects an adapter for a URL and returns a normalized import preview."""

    async def import_url(self, url: str) -> ImportedGamePreview:
        normalized_url = url.strip()
        if not normalized_url:
            raise ValueError("Import URL is required.")

        _load_builtin_adapters()
        adapters = build_registered_adapters()
        adapter = match_adapter(normalized_url, adapters)
        if adapter is None:
            raise ValueError(
                f"No game import adapter supports URL: {normalized_url}"
            )
        return await adapter.fetch(normalized_url)
