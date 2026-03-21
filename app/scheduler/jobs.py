"""Scheduled ingestion jobs.

Each job runs the discovery pipeline for all games with a matching schedule.
"""

from __future__ import annotations

import logging

from app.billing.repository import (
    DiscoveryRunRepository,
    SubscriptionRepository,
)
from app.billing.service import BillingService
from app.games.repository import GameRepository
from app.ingestion.pipeline import run_ingestion

logger = logging.getLogger(__name__)


async def run_scheduled_ingestion(db_path: str, schedule: str) -> None:
    """Run discovery for all games whose discovery_schedule matches *schedule*.

    Called by the scheduler — errors are logged, never raised, so one
    failing game doesn't block others.
    """

    game_repo = GameRepository(db_path)
    sub_repo = SubscriptionRepository(db_path)
    discovery_run_repo = DiscoveryRunRepository(db_path)
    billing = BillingService(sub_repo, game_repo, discovery_run_repo)

    games = game_repo.list_by_schedule(schedule)
    logger.info("Scheduled ingestion (%s): %d game(s)", schedule, len(games))

    for game in games:
        try:
            billing.record_discovery_run(game.user_id, game.game_id)
        except ValueError:
            logger.info(
                "Skipping scheduled ingestion for game %s: monthly limit reached",
                game.game_id,
            )
            continue

        try:
            summary = await run_ingestion(
                game,
                db_path,
                billing.get_prospects_limit(game.user_id),
            )
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
