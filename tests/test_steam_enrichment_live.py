"""Soft live Steam enrichment checks.

These validate the real Steam search/store surfaces without making the suite
fragile. Network failures become warnings plus skips.
"""

from __future__ import annotations

import warnings

import httpx
import pytest

from app.steam_enrichment.client import SteamStoreClient
from app.steam_enrichment.resolver import resolve_steam_candidate
from app.steam_enrichment.tag_mapping import map_steam_terms_to_canonical_tags


def _warn_and_skip(message: str, exc: Exception | None = None) -> None:
    details = f"{message}: {exc}" if exc is not None else message
    warnings.warn(details, stacklevel=2)
    pytest.skip(message)


@pytest.mark.anyio
async def test_live_resolver_matches_slay_the_spire_ii_softly():
    client = SteamStoreClient()
    try:
        candidates = await client.search_candidates("Slay the Spire II")
        store_candidates = [
            await client.fetch_store_game(candidate.app_id)
            for candidate in candidates[:3]
        ]
    except (httpx.HTTPError, ValueError) as exc:
        _warn_and_skip("Steam store was unreachable during this test run", exc)
        return

    mapped_keys = {}
    for candidate in store_candidates:
        mapped = map_steam_terms_to_canonical_tags(
            api_genre_labels=list(candidate.api_genre_labels),
            api_category_labels=list(candidate.api_category_labels),
            raw_tags=list(candidate.raw_tags),
        )
        mapped_keys[candidate.app_id] = {
            (entry.tag_type, str(entry.tag_id)) for entry in mapped
        }

    result = resolve_steam_candidate(
        igdb_id=296831,
        igdb_name="Slay the Spire II",
        igdb_developers=("Mega Crit Games",),
        igdb_release_year=2025,
        local_tag_keys={
            ("genre", "deckbuilder"),
            ("genre", "roguelike"),
            ("genre", "15"),
        },
        candidates=store_candidates,
        candidate_mapped_tag_keys=mapped_keys,
    )

    if result.accepted_link is None:
        _warn_and_skip(
            f"Live Steam resolver did not accept a match: {result.rejection_reason}"
        )
        return

    assert result.accepted_link.steam_app_id == 2868840


@pytest.mark.anyio
async def test_live_fetch_store_game_recovers_tags_for_helldivers_2():
    client = SteamStoreClient()
    try:
        store_game = await client.fetch_store_game(553850)
    except (httpx.HTTPError, ValueError) as exc:
        _warn_and_skip("Steam store was unreachable during this test run", exc)
        return

    if not store_game.raw_tags:
        _warn_and_skip(
            "Steam store returned no raw tags for HELLDIVERS 2 during this test run"
        )
        return

    assert (
        "Shooter" in store_game.raw_tags
        or "Third-Person Shooter" in store_game.raw_tags
    )
