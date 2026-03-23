"""Discovery run orchestration."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

# Import sources package so all sources self-register with the registry.
import app.ingestion.sources  # noqa: F401
from app.games.models import Game
from app.games.repository import MessageTemplateRepository
from app.ingestion.base import CandidateRecord, CandidateSource, SourceRuntime
from app.ingestion.constants import YOUTUBE_DISCOVERY_LIMIT
from app.ingestion.registry import Source, get_source
from app.ingestion.runs.budget import RunQueueBudget
from app.ingestion.runs.filters import prefilter_prospects
from app.ingestion.runs.persistence import (
    find_template,
    game_run_index,
    has_scoreable_text,
    load_cached_llm_scores,
    load_cursors,
    render_template,
    save_cursors,
    seen_handles_for_game,
    upsert_prospect,
)
from app.ingestion.sources.youtube_api import (
    QuotaExceededError,
    YouTubeAPISource,
)
from app.json_codec import dump_json
from app.prospects.models import Prospect
from app.scoring.engine import ScoreBreakdown
from app.scoring.llm_engine import LLMFitScores

if TYPE_CHECKING:
    from app.metrics.service import MetricsService

log = logging.getLogger("app.ingestion.pipeline")

ScoreProspectFn = Callable[..., ScoreBreakdown]
LLMScoreBatchFn = Callable[
    [Game, list[Prospect], str], Awaitable[dict[str, LLMFitScores]]
]

_LLM_RESULT_BATCH_SIZE = 3


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
    *,
    score_prospect_fn: ScoreProspectFn,
    llm_score_batch_fn: LLMScoreBatchFn,
) -> dict:
    """Run the full discovery → scoring → import pipeline for a game."""
    try:
        template_repo = MessageTemplateRepository(db_path)
        templates = template_repo.list_by_game(game.game_id)
        runtime = SourceRuntime(
            youtube_api_key=youtube_api_key,
            youtube_cache_dir=youtube_cache_dir,
            twitch_client_id=twitch_client_id,
            twitch_client_secret=twitch_client_secret,
        )
        run_index = game_run_index(game.game_id, db_path)
        seen_handles_by_platform = seen_handles_for_game(game.game_id, db_path)

        log.info(
            "[%s] LLM scoring: %s",
            game.name,
            "enabled (Haiku)"
            if anthropic_api_key
            else "disabled (keyword fallback)",
        )
        log.info(
            "[%s] Discovery run %d starting with %d previously surfaced prospects",
            game.name,
            run_index + 1,
            sum(len(handles) for handles in seen_handles_by_platform.values()),
        )
        queue_budget = RunQueueBudget(queue_cap=max(0, limit_per_source))

        sources = _build_sources(
            game, runtime, limit_per_source, sources_override=sources_override
        )

        tasks = [
            _run_source(
                source,
                game,
                limit,
                templates,
                db_path,
                anthropic_api_key,
                runtime,
                run_id=run_id,
                metrics_service=metrics_service,
                run_index=run_index,
                queue_budget=queue_budget,
                excluded_handles=seen_handles_by_platform.get(
                    source.platform or "", set()
                ),
                score_prospect_fn=score_prospect_fn,
                llm_score_batch_fn=llm_score_batch_fn,
            )
            for source, limit in sources
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        task_errors = [
            result for result in results if isinstance(result, Exception)
        ]
        if task_errors:
            raise task_errors[0]

        totals: dict[str, int] = {"discovered": 0, "scored": 0, "imported": 0}
        for result in results:
            if isinstance(result, dict):
                for key in totals:
                    totals[key] += result[key]

        if run_id is not None and metrics_service is not None:
            metrics_service.record_discovery_run_completed(
                run_id,
                completed_at=datetime.now(UTC).isoformat(),
                discovered_count=totals["discovered"],
                scored_count=totals["scored"],
                queued_count=totals["imported"],
            )
        return totals
    except Exception as exc:
        if run_id is not None and metrics_service is not None:
            metrics_service.record_discovery_run_failed(
                run_id,
                failed_at=datetime.now(UTC).isoformat(),
                error_message=str(exc),
            )
        raise


def youtube_candidate_limit(limit_per_source: int) -> int:
    """Return the effective YouTube discovery cap for a run."""
    return min(limit_per_source, YOUTUBE_DISCOVERY_LIMIT)


def _resolve_source_name(
    source_name: Source, runtime: SourceRuntime
) -> Source:
    """Resolve aliases like YouTube → YouTube API when credentials exist."""
    if source_name == Source.YOUTUBE and runtime.youtube_api_key:
        return Source.YOUTUBE_API
    return source_name


def _build_sources(
    game: Game,
    runtime: SourceRuntime,
    limit_per_source: int,
    sources_override: list[str] | None = None,
) -> list[tuple[CandidateSource, int]]:
    sources: list[tuple[CandidateSource, int]] = []

    if sources_override:
        source_names = []
        for source_name in sources_override:
            try:
                source_names.append(Source(source_name))
            except ValueError:
                log.warning(
                    "[%s] Ignoring unknown source override %r",
                    game.name,
                    source_name,
                )
    else:
        source_names = game.discovery_sources

    for source_name in source_names:
        effective_source_name = _resolve_source_name(source_name, runtime)
        try:
            source_cls = get_source(effective_source_name)
            source = source_cls.build(runtime)
        except KeyError:
            log.warning(
                "[%s] Unknown discovery source %r — skipping",
                game.name,
                effective_source_name,
            )
            continue
        except ValueError as exc:
            log.warning(
                "[%s] Could not initialize %s source: %s",
                game.name,
                effective_source_name.value,
                exc,
            )
            continue

        source_limit = source_cls.effective_limit(limit_per_source)
        _log_selected_source(game.name, source_name, effective_source_name)
        sources.append((source, source_limit))

    return sources


def _log_selected_source(
    game_name: str,
    requested_source: Source,
    effective_source: Source,
) -> None:
    if requested_source == Source.YOUTUBE:
        if effective_source == Source.YOUTUBE_API:
            log.info("[%s] YouTube source: Data API", game_name)
        else:
            log.info(
                "[%s] YouTube source: scraping fallback (no API key)",
                game_name,
            )
        return

    labels = {
        Source.REDDIT: "Reddit source: public JSON API",
        Source.BLUESKY: "Bluesky source: public XRPC API",
        Source.TWITCH: "Twitch source: Helix live channel discovery",
    }
    log.info(
        "[%s] %s", game_name, labels.get(effective_source, effective_source)
    )


async def _run_source(
    source: CandidateSource,
    game: Game,
    limit_per_source: int,
    templates: list,
    db_path: str,
    anthropic_api_key: str,
    runtime: SourceRuntime | None,
    run_id: str | None,
    metrics_service: MetricsService | None,
    *,
    run_index: int,
    queue_budget: RunQueueBudget,
    excluded_handles: set[str] | None,
    score_prospect_fn: ScoreProspectFn,
    llm_score_batch_fn: LLMScoreBatchFn,
) -> dict:
    counts: dict[str, int] = {"discovered": 0, "scored": 0, "imported": 0}
    excluded = excluded_handles or set()

    source_platform = source.platform or ""
    page_cursors = load_cursors(game.game_id, source_platform, db_path)
    discovered_handles: set[str] = set()

    try:
        await _consume_source_batches(
            source,
            game=game,
            limit_per_source=limit_per_source,
            templates=templates,
            db_path=db_path,
            anthropic_api_key=anthropic_api_key,
            page_cursors=page_cursors,
            run_id=run_id,
            metrics_service=metrics_service,
            counts=counts,
            run_index=run_index,
            queue_budget=queue_budget,
            excluded_handles=excluded,
            discovered_handles=discovered_handles,
            score_prospect_fn=score_prospect_fn,
            llm_score_batch_fn=llm_score_batch_fn,
        )
    except QuotaExceededError:
        log.warning(
            "[%s] YouTube API quota exhausted — falling back to scraper",
            game.name,
        )
        try:
            fallback_cls = get_source(Source.YOUTUBE)
            fallback_source = fallback_cls.build(runtime or SourceRuntime())
            await _consume_source_batches(
                fallback_source,
                game=game,
                limit_per_source=max(
                    0, limit_per_source - len(discovered_handles)
                ),
                templates=templates,
                db_path=db_path,
                anthropic_api_key=anthropic_api_key,
                page_cursors={},
                run_id=run_id,
                metrics_service=metrics_service,
                counts=counts,
                run_index=run_index,
                queue_budget=queue_budget,
                excluded_handles=excluded | discovered_handles,
                discovered_handles=discovered_handles,
                score_prospect_fn=score_prospect_fn,
                llm_score_batch_fn=llm_score_batch_fn,
            )
        except Exception as exc:
            log.error("[%s] Scraping fallback also failed: %s", game.name, exc)
            return counts
    except Exception as exc:
        log.error("[%s] Discovery failed: %s", game.name, exc)
        return counts

    if (
        not queue_budget.should_stop()
        and isinstance(source, YouTubeAPISource)
        and runtime is not None
        and len(discovered_handles) < limit_per_source
    ):
        remaining = limit_per_source - len(discovered_handles)
        log.info(
            "[%s] YouTube API returned %d/%d candidates; supplementing with scraper for %d more",
            game.name,
            len(discovered_handles),
            limit_per_source,
            remaining,
        )
        try:
            fallback_cls = get_source(Source.YOUTUBE)
            fallback_source = fallback_cls.build(runtime)
            await _consume_source_batches(
                fallback_source,
                game=game,
                limit_per_source=remaining,
                templates=templates,
                db_path=db_path,
                anthropic_api_key=anthropic_api_key,
                page_cursors={},
                run_id=run_id,
                metrics_service=metrics_service,
                counts=counts,
                run_index=run_index,
                queue_budget=queue_budget,
                excluded_handles=excluded | discovered_handles,
                discovered_handles=discovered_handles,
                score_prospect_fn=score_prospect_fn,
                llm_score_batch_fn=llm_score_batch_fn,
            )
        except Exception as exc:
            log.warning(
                "[%s] YouTube scrape supplement failed: %s",
                game.name,
                exc,
            )

    log.info(
        "[%s] Done — discovered %d, scored %d, imported %d new prospects",
        game.name,
        counts["discovered"],
        counts["scored"],
        counts["imported"],
    )
    return counts


async def _consume_source_batches(
    source: CandidateSource,
    *,
    game: Game,
    limit_per_source: int,
    templates: list,
    db_path: str,
    anthropic_api_key: str,
    page_cursors: dict[str, str],
    run_id: str | None,
    metrics_service: MetricsService | None,
    counts: dict[str, int],
    run_index: int,
    queue_budget: RunQueueBudget,
    excluded_handles: set[str],
    discovered_handles: set[str],
    score_prospect_fn: ScoreProspectFn,
    llm_score_batch_fn: LLMScoreBatchFn,
) -> None:
    if limit_per_source <= 0 or queue_budget.should_stop():
        return

    source_platform = source.platform or ""

    try:
        async for candidates in source.discover_batches(
            game,
            limit_per_source,
            run_index=run_index,
            excluded_handles=excluded_handles,
            page_cursors=page_cursors,
        ):
            if queue_budget.should_stop():
                log.info(
                    "[%s] Run queue cap reached; stopping %s batch processing",
                    game.name,
                    source_platform or source.__class__.__name__,
                )
                break
            if not candidates:
                continue
            counts["discovered"] += len(candidates)
            discovered_handles.update(
                str(candidate.handle).strip().lower()
                for candidate in candidates
            )
            log.info(
                "[%s] Discovered %d candidates in current batch (%d previously surfaced excluded)",
                game.name,
                len(candidates),
                len(excluded_handles),
            )
            await _process_candidates_batch(
                candidates,
                game=game,
                templates=templates,
                db_path=db_path,
                anthropic_api_key=anthropic_api_key,
                run_id=run_id,
                metrics_service=metrics_service,
                counts=counts,
                queue_budget=queue_budget,
                score_prospect_fn=score_prospect_fn,
                llm_score_batch_fn=llm_score_batch_fn,
            )
            if queue_budget.should_stop():
                break
    finally:
        if source_platform:
            save_cursors(game.game_id, source_platform, page_cursors, db_path)


async def _process_candidates_batch(
    candidates: list[CandidateRecord],
    *,
    game: Game,
    templates: list,
    db_path: str,
    anthropic_api_key: str,
    run_id: str | None,
    metrics_service: MetricsService | None,
    counts: dict[str, int],
    queue_budget: RunQueueBudget,
    score_prospect_fn: ScoreProspectFn,
    llm_score_batch_fn: LLMScoreBatchFn,
) -> None:
    prospects = [
        upsert_prospect(candidate, db_path) for candidate in candidates
    ]
    if not prospects:
        return

    base_scores = {
        prospect.prospect_id: score_prospect_fn(game, prospect)
        for prospect in prospects
    }
    filtered = prefilter_prospects(game, prospects, base_scores)
    if not filtered:
        return

    reserved_evaluations = await queue_budget.reserve_evaluation_slots(
        len(filtered)
    )
    if reserved_evaluations <= 0:
        log.info(
            "[%s] Run queue cap already satisfied; skipping batch", game.name
        )
        return

    prospects = sorted(
        filtered,
        key=lambda prospect: base_scores[prospect.prospect_id].final_score,
        reverse=True,
    )[:reserved_evaluations]

    try:
        llm_scores: dict[str, LLMFitScores] = {}
        immediate_prospects: list[Prospect] = prospects
        if anthropic_api_key:
            llm_scores = load_cached_llm_scores(
                game.game_id, prospects, db_path
            )
            cached_count = len(llm_scores)

            needs_llm = [
                prospect
                for prospect in prospects
                if prospect.prospect_id not in llm_scores
                and has_scoreable_text(prospect)
            ]
            needs_llm_ids = {prospect.prospect_id for prospect in needs_llm}
            skipped_count = len(prospects) - cached_count - len(needs_llm)

            reserved_llm = await queue_budget.reserve_llm_slots(len(needs_llm))
            if reserved_llm < len(needs_llm):
                needs_llm = needs_llm[:reserved_llm]
            if len(needs_llm) < len(needs_llm_ids):
                needs_llm_ids = {
                    prospect.prospect_id for prospect in needs_llm
                }

            log.info(
                "[%s] LLM scoring: %d to score, %d cached, %d skipped (no text)",
                game.name,
                len(needs_llm),
                cached_count,
                skipped_count,
            )

            immediate_prospects = [
                prospect
                for prospect in prospects
                if prospect.prospect_id in llm_scores
                or prospect.prospect_id not in needs_llm_ids
            ]
        else:
            needs_llm = []
            reserved_llm = 0

        await _score_and_queue_prospects(
            immediate_prospects,
            game=game,
            templates=templates,
            db_path=db_path,
            llm_scores=llm_scores,
            run_id=run_id,
            metrics_service=metrics_service,
            counts=counts,
            queue_budget=queue_budget,
            score_prospect_fn=score_prospect_fn,
        )

        if anthropic_api_key and needs_llm:
            llm_scored_count = 0
            llm_attempted_count = 0
            for batch in _chunked(needs_llm, _LLM_RESULT_BATCH_SIZE):
                if queue_budget.should_stop():
                    break
                llm_attempted_count += len(batch)
                try:
                    new_scores = await llm_score_batch_fn(
                        game, batch, anthropic_api_key
                    )
                    llm_scores.update(new_scores)
                    llm_scored_count += len(new_scores)
                except Exception as exc:
                    log.warning(
                        "[%s] LLM batch scoring failed, using keyword fallback: %s",
                        game.name,
                        exc,
                    )
                await _score_and_queue_prospects(
                    batch,
                    game=game,
                    templates=templates,
                    db_path=db_path,
                    llm_scores=llm_scores,
                    run_id=run_id,
                    metrics_service=metrics_service,
                    counts=counts,
                    queue_budget=queue_budget,
                    score_prospect_fn=score_prospect_fn,
                )

            await queue_budget.release_llm_slots(
                reserved_llm, attempted=llm_attempted_count
            )
            log.info(
                "[%s] LLM scored %d/%d prospects in current batch",
                game.name,
                llm_scored_count,
                len(needs_llm),
            )
        elif anthropic_api_key:
            await queue_budget.release_llm_slots(reserved_llm, attempted=0)
    finally:
        await queue_budget.release_evaluation_slots(reserved_evaluations)


async def _score_and_queue_prospects(
    prospects: list[Prospect],
    *,
    game: Game,
    templates: list,
    db_path: str,
    llm_scores: dict[str, LLMFitScores],
    run_id: str | None,
    metrics_service: MetricsService | None,
    counts: dict[str, int],
    queue_budget: RunQueueBudget,
    score_prospect_fn: ScoreProspectFn,
) -> None:
    for prospect in prospects:
        if queue_budget.should_stop():
            return
        llm = llm_scores.get(prospect.prospect_id)
        score = score_prospect_fn(
            game,
            prospect,
            genre_fit_override=llm.genre_fit if llm else None,
            vibe_fit_override=llm.vibe_fit if llm else None,
            format_fit_override=llm.format_fit if llm else None,
            platform_fit_override=llm.platform_fit if llm else None,
            fit_summary_override=llm.fit_summary if llm else None,
            why_selected_override=llm.why_selected if llm else None,
        )
        counts["scored"] += 1

        log.debug(
            "[%s] %-35s  final=%.2f  genre=%.2f  vibe=%.2f  format=%.2f  activity=%.2f  %s",
            game.name,
            prospect.display_name[:35],
            score.final_score,
            score.genre_fit,
            score.vibe_fit,
            score.format_fit,
            score.activity_score,
            "✓ llm" if llm else "· keyword",
        )

        if score.final_score < 0.20:
            if run_id is not None and metrics_service is not None:
                metrics_service.record_prospect_score(
                    run_id,
                    user_id=game.user_id,
                    game_id=game.game_id,
                    score=score.final_score,
                    queued=False,
                    occurred_at=datetime.now(UTC).isoformat(),
                )
            log.debug(
                "[%s]   └─ dropped (score %.2f < 0.20)",
                game.name,
                score.final_score,
            )
            continue

        matched_template = find_template(templates, prospect.platform)

        subject_line: str | None = None
        body_text = (
            f"Hi {prospect.display_name},\n\n"
            f"I'd love to share my game {game.name} with you.\n"
        )

        if matched_template is not None:
            fit_reason = score.fit_summary
            body_text = render_template(
                matched_template.body_template,
                creator_name=prospect.display_name,
                game_name=game.name,
                fit_reason=fit_reason,
            )
            if matched_template.subject_template:
                subject_line = render_template(
                    matched_template.subject_template,
                    creator_name=prospect.display_name,
                    game_name=game.name,
                    fit_reason=fit_reason,
                )

        score_breakdown_json = dump_json(
            {
                "genre_fit": score.genre_fit,
                "vibe_fit": score.vibe_fit,
                "format_fit": score.format_fit,
                "activity_score": score.activity_score,
                "platform_fit": score.platform_fit,
                "contactability": score.contactability,
                "audience_size_score": score.audience_size_score,
                "final_score": score.final_score,
                "reasons": score.reasons,
                "why_selected": score.why_selected,
                "llm_scored": llm is not None,
            }
        )

        draft_status = await queue_budget.upsert_draft_item(
            game_id=game.game_id,
            prospect_id=prospect.prospect_id,
            template_id=matched_template.template_id
            if matched_template
            else None,
            subject_line=subject_line,
            body_text=body_text,
            priority_score=score.final_score,
            fit_summary=score.fit_summary,
            score_breakdown=score_breakdown_json,
            db_path=db_path,
        )
        inserted = draft_status == "inserted"
        if run_id is not None and metrics_service is not None:
            metrics_service.record_prospect_score(
                run_id,
                user_id=game.user_id,
                game_id=game.game_id,
                score=score.final_score,
                queued=inserted,
                occurred_at=datetime.now(UTC).isoformat(),
            )
        if inserted:
            counts["imported"] += 1
            log.debug("[%s]   └─ queued as new prospect", game.name)
        elif draft_status == "cap_reached":
            log.debug("[%s]   └─ skipped (run queue cap reached)", game.name)
            return
        else:
            log.debug("[%s]   └─ refreshed existing prospect", game.name)


def _chunked(items: list[Prospect], size: int) -> list[list[Prospect]]:
    return [items[i : i + size] for i in range(0, len(items), size)]
