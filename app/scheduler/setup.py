"""APScheduler setup for headless background creator-index jobs."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.runtime import SourceRuntime
from app.scheduler.jobs import (
    run_catalog_discovery,
    run_game_discovery,
    run_scheduled_creator_index_sync,
    run_steam_tag_backfill,
    run_top_categories_crawl,
)

log = logging.getLogger(__name__)


def create_scheduler(
    db_path: str,
    source_runtime: SourceRuntime,
    *,
    catalog_dir: str | None = None,
) -> AsyncIOScheduler:
    """Create a scheduler with the active creator-index jobs."""

    scheduler = AsyncIOScheduler(timezone="UTC")

    # -- Startup: immediate one-shot sync of active customer games
    scheduler.add_job(
        run_scheduled_creator_index_sync,
        trigger="date",
        run_date=datetime.now(UTC) + timedelta(seconds=1),
        id="creator_index_startup_sync",
        kwargs={
            "db_path": db_path,
            "source_runtime": source_runtime,
        },
        replace_existing=True,
    )

    # -- Startup: immediate one-shot Steam tag backfill
    scheduler.add_job(
        run_steam_tag_backfill,
        trigger="date",
        run_date=datetime.now(UTC) + timedelta(seconds=1),
        id="steam_tag_startup_backfill",
        kwargs={
            "db_path": db_path,
            "limit": 25,
        },
        replace_existing=True,
    )

    # -- Customer game sweep: every 10 minutes
    scheduler.add_job(
        run_scheduled_creator_index_sync,
        trigger="interval",
        id="creator_index_twitch_sync",
        kwargs={
            "db_path": db_path,
            "source_runtime": source_runtime,
        },
        jitter=60,
        coalesce=True,
        max_instances=1,
        replace_existing=True,
        minutes=10,
    )

    # -- Top categories crawl: every 30 minutes
    scheduler.add_job(
        run_top_categories_crawl,
        trigger="interval",
        id="top_categories_crawl",
        kwargs={
            "db_path": db_path,
            "source_runtime": source_runtime,
        },
        jitter=60,
        coalesce=True,
        max_instances=1,
        replace_existing=True,
        minutes=30,
    )

    # -- Catalog discovery: every 6 hours (if a catalog dir is configured)
    if catalog_dir:
        scheduler.add_job(
            run_catalog_discovery,
            trigger="interval",
            id="catalog_discovery",
            kwargs={
                "db_path": db_path,
                "source_runtime": source_runtime,
                "catalog_dir": catalog_dir,
            },
            jitter=300,
            coalesce=True,
            max_instances=1,
            replace_existing=True,
            hours=6,
        )

    # -- Steam tag backfill: every 15 minutes
    scheduler.add_job(
        run_steam_tag_backfill,
        trigger="interval",
        id="steam_tag_backfill",
        kwargs={
            "db_path": db_path,
            "limit": 25,
        },
        jitter=60,
        coalesce=True,
        max_instances=1,
        replace_existing=True,
        minutes=15,
    )

    return scheduler


def schedule_game_discovery(
    scheduler: AsyncIOScheduler,
    db_path: str,
    source_runtime: SourceRuntime,
    customer_game_id: str,
) -> None:
    """Schedule an on-demand discovery job for a specific customer game.

    The job runs once, shortly after being scheduled.  It is non-blocking
    for the caller.
    """

    job_id = f"on_demand_discovery_{customer_game_id}"
    scheduler.add_job(
        run_game_discovery,
        trigger="date",
        run_date=datetime.now(UTC) + timedelta(seconds=5),
        id=job_id,
        kwargs={
            "db_path": db_path,
            "source_runtime": source_runtime,
            "customer_game_id": customer_game_id,
        },
        replace_existing=True,
    )
    log.info(
        "Scheduled on-demand discovery for game %s",
        customer_game_id,
    )
