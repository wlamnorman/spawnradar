"""Demand-driven creator discovery pipeline.

Builds a priority-tiered reference game set (tight anchors → IGDB keywords →
broad anchors → two-hop expansion), bridges to Twitch categories, crawls
streams + clips per category and enriches each creator at discovery time.

The main entry point is :func:`discover_creators`, an async generator that
yields :class:`EnrichedCreator` instances as they are found.  The caller is
responsible for persistence.

Key features:
- Category rotation across runs (offset-based)
- Time-shifted clip windows for tight anchors
- Skip-recently-enriched with incremental clip deepening
- Two-hop expansion from top creators' game libraries (zero API calls)

See ``docs/DISCOVERY_PIPELINE.md`` for the full strategy documentation.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass

import httpx

from app.creator_index.adapters.base import AccountSeedBundle

# Re-export enrichment helpers (used by orchestrator)
from app.creator_index.discovery_enrichment import (
    DEEPEN_MAX_GAMES,
    get_creator_state,
    update_clip_state,
)

# Re-export stages (public + test-imported symbols)
from app.creator_index.discovery_stages import (  # noqa: F401
    CrawlHit,
    ReferenceGame,
    bridge_to_twitch,
    build_reference_games,
    crawl_category,
    fetch_twitch_auth_headers,
    resolve_similar_games,
    run_keyword_queries,
)
from app.creator_index.enrichment import TwitchEnrichment
from app.creator_index.stream_discovery import TwitchStreamClient
from app.creator_index.twitch_http import twitch_request_json
from app.games.models import CustomerGame
from app.igdb.client import IGDBClient
from app.igdb.repository import IGDBRepository

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EnrichedCreator:
    """A fully enriched creator yielded by the discovery pipeline."""

    bundle: AccountSeedBundle
    source_game_name: str
    source_igdb_game_id: int | None


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


_DEFAULT_DEADLINE_SECONDS = 900  # 15 minutes max per game


async def discover_creators(
    customer_game: CustomerGame,
    *,
    igdb_client: IGDBClient,
    twitch_client: TwitchStreamClient,
    enrichment: TwitchEnrichment,
    igdb_repo: IGDBRepository,
    db_path: str | None = None,
    max_categories: int = 20,
    category_offset: int = 0,
    deadline_seconds: float = _DEFAULT_DEADLINE_SECONDS,
) -> AsyncGenerator[EnrichedCreator, None]:
    """Discover and enrich content creators for a customer game.

    Yields :class:`EnrichedCreator` instances as they are found.  The
    caller is responsible for persisting each yielded creator.

    Similar games (customer-provided and LLM-suggested) are crawled first
    for fastest initial results.

    *max_categories* caps how many Twitch categories to crawl per run.
    *category_offset* rotates which slice of categories to crawl.
    Pass an incrementing offset across runs to explore different games
    each time (e.g. run 1: offset=0, run 2: offset=20, run 3: offset=40).

    *deadline_seconds* caps the total wall-clock time.  The pipeline
    stops after the current category when the deadline is exceeded.
    """
    t0 = time.monotonic()
    deadline = t0 + deadline_seconds

    # Stage A: build reference games
    log.debug("[%s] Stage A: building reference games...", customer_game.name)
    ref_games = await build_reference_games(
        customer_game,
        igdb_client,
        igdb_repo,
        db_path=db_path,
    )
    if not ref_games:
        log.warning("[%s] No reference games found", customer_game.name)
        return
    log.debug(
        "[%s] Stage A done: %d reference games (%.1fs)",
        customer_game.name,
        len(ref_games),
        time.monotonic() - t0,
    )

    # Stage B: bridge to Twitch
    t1 = time.monotonic()
    log.debug("[%s] Stage B: bridging to Twitch...", customer_game.name)
    bridged = await bridge_to_twitch(ref_games, twitch_client)
    if not bridged:
        log.warning("[%s] No Twitch categories found", customer_game.name)
        return
    log.debug(
        "[%s] Stage B done: %d categories (%.1fs)",
        customer_game.name,
        len(bridged),
        time.monotonic() - t1,
    )

    # Split into tiers:
    #   priority 0 = tight anchors (customer + LLM tight) — always crawled
    #   priority 1 = IGDB keyword games — rotated
    #   priority 2 = LLM broad anchors — rotated after keywords
    #   priority 3 = two-hop expansion games — rotated last
    always = [r for r in bridged if r.priority == 0]
    rotated = [r for r in bridged if r.priority >= 1]

    # Rotate keyword/broad/expansion categories using the offset
    if rotated and category_offset > 0:
        effective_offset = category_offset % len(rotated)
        rotated = rotated[effective_offset:] + rotated[:effective_offset]

    # Cap so total doesn't exceed max_categories
    budget = max(0, max_categories - len(always))
    rotated = rotated[:budget]

    bridged = always + rotated
    tier_counts = {
        p: sum(1 for r in bridged if r.priority == p) for p in range(4)
    }
    log.info(
        "[%s] Crawling %d categories (%d tight + %d keyword + %d broad + %d expansion, offset=%d)",
        customer_game.name,
        len(bridged),
        tier_counts.get(0, 0),
        tier_counts.get(1, 0),
        tier_counts.get(2, 0),
        tier_counts.get(3, 0),
        category_offset,
    )

    # Get a shared auth token for category crawling and refresh it on 401.
    async with httpx.AsyncClient(timeout=20) as http:
        auth_headers = await fetch_twitch_auth_headers(http, twitch_client)

        async def refresh_headers() -> dict[str, str]:
            nonlocal auth_headers
            auth_headers = await fetch_twitch_auth_headers(http, twitch_client)
            return auth_headers

        # Compute time-shifted clip window for tight anchors.
        # Each run (identified by category_offset) shifts to a different
        # 30-day window so repeat crawls of the same categories surface
        # different creators.
        from datetime import UTC, datetime, timedelta

        _CLIP_WINDOW_DAYS = 30
        window_index = (category_offset // 20) % 12  # 12 windows = ~1 year
        now = datetime.now(UTC)
        window_end = now - timedelta(days=window_index * _CLIP_WINDOW_DAYS)
        window_start = window_end - timedelta(days=_CLIP_WINDOW_DAYS)
        tight_clip_started = window_start.strftime("%Y-%m-%dT%H:%M:%SZ")
        tight_clip_ended = window_end.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Stage C: crawl + enrich + yield
        seen_broadcasters: set[str] = set()
        creators_yielded = 0

        for cat_idx, ref_game in enumerate(bridged, 1):
            if time.monotonic() > deadline:
                log.warning(
                    "[%s] Deadline exceeded after %d/%d categories (%.0fs)",
                    customer_game.name,
                    cat_idx - 1,
                    len(bridged),
                    time.monotonic() - t0,
                )
                break

            assert ref_game.twitch_category_id is not None
            cat_name = ref_game.twitch_category_name or ref_game.igdb_game.name
            log.debug(
                "[%s] Crawling category %d/%d: %s",
                customer_game.name,
                cat_idx,
                len(bridged),
                cat_name,
            )

            # Tight anchors get time-shifted clips; others get all-time
            clip_start = tight_clip_started if ref_game.priority == 0 else None
            clip_end = tight_clip_ended if ref_game.priority == 0 else None

            hits = await crawl_category(
                ref_game.twitch_category_id,
                cat_name,
                ref_game.igdb_game.igdb_id,
                http=http,
                auth_headers=auth_headers,
                refresh_headers=refresh_headers,
                max_stream_pages=1,
                max_clips=20,
                clip_started_at=clip_start,
                clip_ended_at=clip_end,
            )

            new_hits = [
                h for h in hits if h.broadcaster_id not in seen_broadcasters
            ]
            enriched_count = 0
            skipped_recent = 0
            for hit_idx, hit in enumerate(new_hits, 1):
                seen_broadcasters.add(hit.broadcaster_id)

                # Single query: get all state we need for this creator
                state = (
                    get_creator_state(db_path, hit.broadcaster_id)
                    if db_path
                    else None
                )

                # Skip recently enriched — but try clip deepening if eligible
                if state and state.recently_enriched:
                    if (
                        not state.clips_exhausted
                        and state.games_played_count < DEEPEN_MAX_GAMES
                    ):
                        (
                            new_games,
                            next_cursor,
                            exhausted,
                        ) = await enrichment.deepen_broadcaster_clips(
                            hit.broadcaster_id,
                            cursor=state.clip_cursor,
                        )
                        if new_games:
                            from app.creator_index.repository import (
                                CreatorIndexRepository,
                            )

                            assert db_path is not None
                            repo = CreatorIndexRepository(db_path)
                            game_names = tuple(g.game_name for g in new_games)
                            repo.upsert_creator_games_played(
                                state.account_id,
                                "twitch",
                                game_names,
                            )
                        assert db_path is not None
                        update_clip_state(
                            db_path,
                            state.account_id,
                            next_cursor,
                            exhausted,
                        )
                    skipped_recent += 1
                    continue

                skip_contacts = state.has_contacts if state else False
                t_enrich = time.monotonic()
                bundle = await enrichment.enrich_broadcaster(
                    hit.broadcaster_id,
                    skip_contacts=skip_contacts,
                )
                enrich_ms = (time.monotonic() - t_enrich) * 1000
                if bundle is None:
                    log.debug(
                        "[%s]   enrichment %d/%d (broadcaster %s) → skip (%.0fms)",
                        customer_game.name,
                        hit_idx,
                        len(new_hits),
                        hit.broadcaster_id,
                        enrich_ms,
                    )
                    continue

                enriched_count += 1
                creators_yielded += 1
                log.debug(
                    "[%s]   enriched %d/%d %s (%.0fms, contacts=%s)",
                    customer_game.name,
                    hit_idx,
                    len(new_hits),
                    bundle.account.display_name_current
                    or bundle.account.handle_current,
                    enrich_ms,
                    "skipped" if skip_contacts else "fetched",
                )
                yield EnrichedCreator(
                    bundle=bundle,
                    source_game_name=hit.source_game_name,
                    source_igdb_game_id=hit.source_igdb_game_id,
                )

            if enriched_count > 0:
                log.info(
                    "[%s] %d/%d %s: +%d creators (%d total, %.0fs)",
                    customer_game.name,
                    cat_idx,
                    len(bridged),
                    cat_name,
                    enriched_count,
                    creators_yielded,
                    time.monotonic() - t0,
                )
            else:
                log.debug(
                    "[%s] %d/%d %s: 0 new (crawled %d, skipped %d recent)",
                    customer_game.name,
                    cat_idx,
                    len(bridged),
                    cat_name,
                    len(new_hits),
                    skipped_recent,
                )

    log.info(
        "[%s] Discovery complete: %d creators from %d categories in %.1fs",
        customer_game.name,
        creators_yielded,
        len(bridged),
        time.monotonic() - t0,
    )


# ---------------------------------------------------------------------------
# Pre-population: top Twitch categories
# ---------------------------------------------------------------------------


async def crawl_top_categories(
    twitch_client: TwitchStreamClient,
    enrichment: TwitchEnrichment,
    igdb_repo: IGDBRepository,
    *,
    max_categories: int = 20,
    db_path: str | None = None,
    deadline_seconds: float = _DEFAULT_DEADLINE_SECONDS,
) -> AsyncGenerator[EnrichedCreator, None]:
    """Crawl top Twitch categories for pre-population.

    This is genre-agnostic — it discovers creators from whatever is
    popular on Twitch right now.  No CustomerGame needed.
    """
    t0 = time.monotonic()
    deadline = t0 + deadline_seconds

    async with httpx.AsyncClient(timeout=20) as http:
        auth_headers = await fetch_twitch_auth_headers(http, twitch_client)

        async def refresh_headers() -> dict[str, str]:
            nonlocal auth_headers
            auth_headers = await fetch_twitch_auth_headers(http, twitch_client)
            return auth_headers

        body = await twitch_request_json(
            http,
            "GET",
            "https://api.twitch.tv/helix/games/top",
            headers=auth_headers,
            params=[("first", str(min(max_categories, 100)))],
            refresh_headers=refresh_headers,
        )

        top_games = body.get("data", []) if isinstance(body, dict) else []
        log.info(
            "[top-categories] Starting crawl of %d categories", len(top_games)
        )

        seen_broadcasters: set[str] = set()
        creators_yielded = 0

        for cat_idx, game_data in enumerate(top_games, 1):
            if time.monotonic() > deadline:
                log.warning(
                    "[top-categories] Deadline exceeded after %d/%d categories (%.0fs)",
                    cat_idx - 1,
                    len(top_games),
                    time.monotonic() - t0,
                )
                break

            cat_id = game_data.get("id")
            cat_name = game_data.get("name", "Unknown")
            if not cat_id:
                continue

            igdb_id: int | None = None
            try:
                page = await twitch_client.get_games(twitch_game_ids=(cat_id,))
                if page.data and page.data[0].igdb_game_id:
                    igdb_id = int(page.data[0].igdb_game_id)
            except (ValueError, TypeError):
                pass

            hits = await crawl_category(
                cat_id,
                cat_name,
                igdb_id,
                http=http,
                auth_headers=auth_headers,
                refresh_headers=refresh_headers,
                max_stream_pages=1,
                max_clips=20,
            )

            new_hits = [
                h for h in hits if h.broadcaster_id not in seen_broadcasters
            ]
            for hit in new_hits:
                seen_broadcasters.add(hit.broadcaster_id)

                # Skip recently enriched (same logic as discover_creators)
                state = (
                    get_creator_state(db_path, hit.broadcaster_id)
                    if db_path
                    else None
                )
                if state and state.recently_enriched:
                    continue

                skip_contacts = state.has_contacts if state else False
                bundle = await enrichment.enrich_broadcaster(
                    hit.broadcaster_id,
                    skip_contacts=skip_contacts,
                )
                if bundle is None:
                    continue

                creators_yielded += 1
                yield EnrichedCreator(
                    bundle=bundle,
                    source_game_name=hit.source_game_name,
                    source_igdb_game_id=hit.source_igdb_game_id,
                )

            if new_hits:
                log.info(
                    "[top-categories] %d/%d %s: +%d creators (%d total, %.0fs)",
                    cat_idx,
                    len(top_games),
                    cat_name,
                    len(new_hits),
                    creators_yielded,
                    time.monotonic() - t0,
                )

    log.info(
        "[top-categories] Complete: %d creators from %d categories in %.1fs",
        creators_yielded,
        len(top_games),
        time.monotonic() - t0,
    )
