"""Headless scheduled jobs.

A module-level semaphore limits concurrent discovery runs to 2, preventing
Twitch API rate-limit exhaustion when multiple games are created at once.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from app.creator_index.service import CreatorIndexService
from app.games.repository import CustomerGameRepository
from app.runtime import SourceRuntime
from app.steam_enrichment.service import SteamTagEnrichmentService

logger = logging.getLogger(__name__)


def _record_discovery_run(
    db_path: str, customer_game_id: str, creators_found: int
) -> None:
    """Best-effort metric recording for a completed discovery run."""
    try:
        from app.billing.repository import SubscriptionRepository
        from app.metrics.repository import MetricsRepository
        from app.metrics.service import MetricsService

        metrics = MetricsService(
            MetricsRepository(db_path),
            SubscriptionRepository(db_path),
        )
        metrics.record_discovery_run_completed(
            customer_game_id=customer_game_id,
            creators_found=creators_found,
        )
    except Exception:
        logger.debug("Failed to record discovery metric", exc_info=True)


# On-demand and background discovery share a single slot.
# Only 1 discovery run at a time to avoid starving the web server
# on a single-CPU machine.
_discovery_semaphore = asyncio.Semaphore(1)


async def run_scheduled_creator_index_sync(
    db_path: str,
    source_runtime: SourceRuntime,
) -> None:
    """Refresh the reusable creator index in the background.

    This job is intentionally separate from any customer-facing workflow state.
    It discovers creators for all active customer games using the v2 pipeline.
    """
    async with _discovery_semaphore:
        # Fill in missing LLM suggestions before crawling
        from app.config import Settings

        settings = Settings.from_env()
        if settings.llm_game_suggestions_enabled:
            repo = CustomerGameRepository(db_path)
            for game in repo.list_active():
                if not game.llm_similar_game_names:
                    from app.llm.game_suggestions import (
                        generate_game_suggestions,
                    )

                    try:
                        tight, broad = await generate_game_suggestions(
                            game,
                            api_key=settings.anthropic_api_key,
                        )
                        if tight or broad:
                            repo.set_llm_game_suggestions(
                                game.customer_game_id,
                                tight,
                                broad,
                            )
                    except Exception:
                        logger.exception(
                            "LLM backfill failed for game %s",
                            game.customer_game_id,
                        )
        service = CreatorIndexService(
            db_path=db_path,
            source_runtime=source_runtime,
        )
        try:
            summary = await service.sync_active_customer_games()
            logger.info(
                "Creator index sync: games=%d accounts=%d samples=%d contacts=%d",
                summary.games_seen,
                summary.accounts_synced,
                summary.content_samples_synced,
                summary.contact_points_synced,
            )
            # Record per-game summaries if available
            for gs in summary.game_summaries:
                _record_discovery_run(
                    db_path,
                    gs.customer_game_id,
                    gs.accounts_synced,
                )
        except Exception:
            logger.exception("Background creator-index sync failed")


async def run_top_categories_crawl(
    db_path: str,
    source_runtime: SourceRuntime,
) -> None:
    """Scheduled job: crawl top Twitch categories for pre-population."""
    async with _discovery_semaphore:
        service = CreatorIndexService(
            db_path=db_path,
            source_runtime=source_runtime,
        )
        try:
            count = await service.run_top_categories_crawl()
            logger.info("Top categories crawl: %d creators discovered", count)
        except Exception:
            logger.exception("Top categories crawl job failed")


async def run_catalog_discovery(
    db_path: str,
    source_runtime: SourceRuntime,
    catalog_dir: str,
) -> None:
    """Scheduled job: run discovery against catalog definitions."""
    async with _discovery_semaphore:
        service = CreatorIndexService(
            db_path=db_path,
            source_runtime=source_runtime,
        )
        try:
            results = await service.run_catalog_discovery(Path(catalog_dir))
            total = sum(results.values())
            logger.info(
                "Catalog discovery: %d creators across %d definitions",
                total,
                len(results),
            )
        except Exception:
            logger.exception("Catalog discovery job failed")


async def run_game_discovery(
    db_path: str,
    source_runtime: SourceRuntime,
    customer_game_id: str,
) -> None:
    """On-demand job: triggered when a customer creates/updates a game."""
    from app.config import Settings

    repo = CustomerGameRepository(db_path)
    customer_game = repo.get_by_id(customer_game_id)
    if customer_game is None:
        logger.warning(
            "On-demand discovery: game %s not found",
            customer_game_id,
        )
        return

    # Generate LLM game suggestions if API key available and not yet generated
    settings = Settings.from_env()
    if (
        settings.llm_game_suggestions_enabled
        and not customer_game.llm_similar_game_names
    ):
        from app.llm.game_suggestions import generate_game_suggestions

        try:
            tight, broad = await generate_game_suggestions(
                customer_game,
                api_key=settings.anthropic_api_key,
            )
            if tight or broad:
                repo.set_llm_game_suggestions(customer_game_id, tight, broad)
                refreshed = repo.get_by_id(customer_game_id)
                if refreshed is None:
                    return
                customer_game = refreshed
        except Exception:
            logger.exception(
                "LLM suggestion generation failed for game %s",
                customer_game_id,
            )

    async with _discovery_semaphore:
        service = CreatorIndexService(
            db_path=db_path,
            source_runtime=source_runtime,
        )
        try:
            summary = await service.sync_customer_game(customer_game)
            logger.info(
                "On-demand discovery for '%s': accounts=%d",
                customer_game.name,
                summary.accounts_synced,
            )
            _record_discovery_run(
                db_path,
                customer_game_id,
                summary.accounts_synced,
            )
        except Exception:
            logger.exception(
                "On-demand discovery failed for game %s",
                customer_game_id,
            )


async def run_steam_tag_backfill(
    db_path: str,
    *,
    limit: int = 25,
) -> None:
    """Scheduled job: backfill Steam links/tags for cached IGDB games."""

    service = SteamTagEnrichmentService(db_path=db_path)
    try:
        summary = await service.backfill(limit=limit)
        logger.info(
            "Steam tag backfill: attempted=%d linked=%d no_match=%d errored=%d",
            summary.attempted,
            summary.linked,
            summary.no_match,
            summary.errored,
        )
    except Exception:
        logger.exception("Steam tag backfill job failed")
