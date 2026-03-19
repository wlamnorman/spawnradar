"""Scheduled ingestion jobs.

Each job runs the discovery pipeline for all games with a matching schedule.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def run_scheduled_ingestion(db_path: str, schedule: str) -> None:
    """Run discovery for all games whose discovery_schedule matches *schedule*.

    Called by the scheduler — errors are logged, never raised, so one
    failing game doesn't block others.
    """
    from app.games.repository import GameRepository
    from app.ingestion.pipeline import run_ingestion

    repo = GameRepository(db_path)
    games = repo.list_by_schedule(schedule)
    logger.info("Scheduled ingestion (%s): %d game(s)", schedule, len(games))

    for game in games:
        try:
            summary = await run_ingestion(game, db_path)
            logger.info(
                "Game %s (%s): discovered=%d scored=%d imported=%d",
                game.name,
                game.game_id,
                summary["discovered"],
                summary["scored"],
                summary["imported"],
            )
        except Exception:
            logger.exception("Ingestion failed for game %s", game.game_id)
