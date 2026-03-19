"""APScheduler setup — creates and configures the AsyncIOScheduler."""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = logging.getLogger(__name__)


def create_scheduler(db_path: str) -> AsyncIOScheduler:
    """Create a scheduler with daily and weekly ingestion jobs."""
    from app.scheduler.jobs import run_scheduled_ingestion

    scheduler = AsyncIOScheduler(timezone="UTC")

    # Daily: runs at 03:00 UTC every day
    scheduler.add_job(
        run_scheduled_ingestion,
        trigger="cron",
        hour=3,
        minute=0,
        id="daily_ingestion",
        kwargs={"db_path": db_path, "schedule": "daily"},
        replace_existing=True,
    )

    # Weekly: runs at 03:30 UTC every Monday
    scheduler.add_job(
        run_scheduled_ingestion,
        trigger="cron",
        day_of_week="mon",
        hour=3,
        minute=30,
        id="weekly_ingestion",
        kwargs={"db_path": db_path, "schedule": "weekly"},
        replace_existing=True,
    )

    return scheduler
