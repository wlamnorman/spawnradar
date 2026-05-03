"""Adapter registry for the standalone game-import subsystem.

Adapters register themselves with a decorator so the import service can stay
small and avoid source-specific branching. The registry returns adapter
instances, not classes, so service code can work against a simple protocol.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, TypeVar

from app.game_import.models import ImportedGamePreview


class GameImportAdapter(Protocol):
    """Protocol that all import adapters must satisfy."""

    source_kind: str

    def matches_url(self, url: str) -> bool:
        """Return True when the adapter knows how to import the URL."""
        ...

    async def fetch(self, url: str) -> ImportedGamePreview:
        """Fetch, parse and normalize imported data for a matching URL."""
        ...


AdapterType = TypeVar("AdapterType", bound=type[GameImportAdapter])
_REGISTERED_ADAPTERS: list[type[GameImportAdapter]] = []


def register_adapter[AdapterType: type[GameImportAdapter]](
    adapter_cls: AdapterType,
) -> AdapterType:
    """Register an adapter class exactly once and return it unchanged."""
    if adapter_cls not in _REGISTERED_ADAPTERS:
        _REGISTERED_ADAPTERS.append(adapter_cls)
    return adapter_cls


def build_registered_adapters() -> list[GameImportAdapter]:
    """Instantiate all registered adapters in registration order."""
    return [adapter_cls() for adapter_cls in _REGISTERED_ADAPTERS]


def match_adapter(
    url: str, adapters: Sequence[GameImportAdapter]
) -> GameImportAdapter | None:
    """Return the first adapter that claims the provided URL."""
    for adapter in adapters:
        if adapter.matches_url(url):
            return adapter
    return None
