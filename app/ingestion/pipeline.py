"""Public discovery pipeline facade.

The canonical implementation now lives in `app.ingestion.service`.
Keep this module as the stable import surface for routes, jobs and tests.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.games.models import Game
from app.games.repository import MessageTemplateRepository
from app.ingestion.base import SourceRuntime
from app.ingestion.service import DiscoveryRunService, DiscoveryRunSummary
from app.scoring.engine import score_prospect
from app.scoring.llm_engine import llm_score_batch

if TYPE_CHECKING:
    from app.metrics.service import MetricsService


async def run_ingestion(
    game: Game,
    db_path: str,
    limit_per_source: int = 30,
    youtube_api_key: str = "",
    anthropic_api_key: str = "",
    youtube_cache_dir: str = "",
    twitch_client_id: str = "",
    twitch_client_secret: str = "",
    run_id: str | None = None,
    metrics_service: MetricsService | None = None,
    sources_override: list[str] | None = None,
) -> DiscoveryRunSummary:
    """Run the full discovery → scoring → import pipeline for a game."""
    service = DiscoveryRunService(
        MessageTemplateRepository(db_path),
        db_path=db_path,
        metrics_service=metrics_service,
        source_runtime=SourceRuntime(
            youtube_api_key=youtube_api_key,
            youtube_cache_dir=youtube_cache_dir,
            twitch_client_id=twitch_client_id,
            twitch_client_secret=twitch_client_secret,
        ),
        anthropic_api_key=anthropic_api_key,
        score_prospect_fn=score_prospect,
        llm_score_batch_fn=llm_score_batch,
    )
    return await service.run_ingestion(
        game,
        limit_per_source=limit_per_source,
        run_id=run_id,
        sources_override=sources_override,
    )


def _resolve_source_name(source_name, runtime: SourceRuntime):
    """Resolve aliases like YouTube → YouTube API when credentials exist."""
    return DiscoveryRunService.resolve_source_name(source_name, runtime)


def youtube_candidate_limit(limit_per_source: int) -> int:
    """Return the effective YouTube discovery cap for a run."""
    return DiscoveryRunService.youtube_candidate_limit(limit_per_source)


__all__ = [
    "run_ingestion",
    "youtube_candidate_limit",
    "_resolve_source_name",
    "score_prospect",
    "llm_score_batch",
]
