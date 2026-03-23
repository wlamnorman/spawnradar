"""Discovery run application service.

This service owns the end-to-end discovery workflow:

1. resolve the configured sources for a game
2. stream candidate batches from those sources in parallel
3. persist normalized prospects
4. prefilter obvious bad fits before LLM work
5. apply heuristic and optional LLM scoring
6. upsert strong prospects into the review queue

The public pipeline wrapper in ``app.ingestion.pipeline`` exists for
compatibility, but this service is the canonical implementation.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, TypedDict

# Import sources package so all sources self-register with the registry.
import app.ingestion.sources  # noqa: F401
from app.games.models import Game, MessageTemplate
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
from app.scoring.engine import ScoreBreakdown, score_prospect
from app.scoring.llm_engine import LLMFitScores, llm_score_batch

if TYPE_CHECKING:
    from app.metrics.service import MetricsService

log = logging.getLogger("app.ingestion.service")

ScoreProspectFn = Callable[..., ScoreBreakdown]
LLMScoreBatchFn = Callable[
    [Game, list[Prospect], str], Awaitable[dict[str, LLMFitScores]]
]

_LLM_RESULT_BATCH_SIZE = 3
_MINIMUM_QUEUE_SCORE = 0.20


class DiscoveryRunSummary(TypedDict):
    """High-level counts returned after a discovery run."""

    discovered: int
    scored: int
    imported: int


class DiscoveryRunService:
    """Application service for one game's discovery and queueing workflow."""

    def __init__(
        self,
        template_repo: MessageTemplateRepository,
        *,
        db_path: str,
        metrics_service: MetricsService | None = None,
        source_runtime: SourceRuntime | None = None,
        anthropic_api_key: str = "",
        score_prospect_fn: ScoreProspectFn = score_prospect,
        llm_score_batch_fn: LLMScoreBatchFn = llm_score_batch,
    ) -> None:
        self._template_repo = template_repo
        self._db_path = db_path
        self._metrics_service = metrics_service
        self._runtime = source_runtime or SourceRuntime()
        self._anthropic_api_key = anthropic_api_key
        self._score_prospect = score_prospect_fn
        self._llm_score_batch = llm_score_batch_fn

    async def run_ingestion(
        self,
        game: Game,
        limit_per_source: int = 30,
        *,
        run_id: str | None = None,
        sources_override: list[str] | None = None,
    ) -> DiscoveryRunSummary:
        """Run the full discovery -> scoring -> queueing pipeline for a game."""
        try:
            templates = self._template_repo.list_by_game(game.game_id)
            run_index = game_run_index(game.game_id, self._db_path)
            seen_handles_by_platform = seen_handles_for_game(
                game.game_id, self._db_path
            )

            self._log_run_start(
                game=game,
                run_index=run_index,
                seen_handles_by_platform=seen_handles_by_platform,
            )

            queue_budget = RunQueueBudget(queue_cap=max(0, limit_per_source))
            sources = self._build_sources(
                game,
                limit_per_source,
                sources_override=sources_override,
            )

            tasks = [
                self._run_source(
                    source,
                    game=game,
                    limit_per_source=limit,
                    templates=templates,
                    run_id=run_id,
                    run_index=run_index,
                    queue_budget=queue_budget,
                    excluded_handles=seen_handles_by_platform.get(
                        source.platform or "", set()
                    ),
                )
                for source, limit in sources
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            task_errors = [
                result for result in results if isinstance(result, Exception)
            ]
            if task_errors:
                raise task_errors[0]

            totals = self._summarize_results(results)
            self._record_run_completed(run_id, totals)
            return totals
        except Exception as exc:
            self._record_run_failed(run_id, exc)
            raise

    @staticmethod
    def youtube_candidate_limit(limit_per_source: int) -> int:
        """Return the effective YouTube discovery cap for a run."""
        return min(limit_per_source, YOUTUBE_DISCOVERY_LIMIT)

    @staticmethod
    def resolve_source_name(
        source_name: Source, runtime: SourceRuntime
    ) -> Source:
        """Resolve aliases like YouTube -> YouTube API when credentials exist."""
        if source_name == Source.YOUTUBE and runtime.youtube_api_key:
            return Source.YOUTUBE_API
        return source_name

    def _log_run_start(
        self,
        *,
        game: Game,
        run_index: int,
        seen_handles_by_platform: dict[str, set[str]],
    ) -> None:
        log.info(
            "[%s] LLM scoring: %s",
            game.name,
            "enabled (Haiku)"
            if self._anthropic_api_key
            else "disabled (keyword fallback)",
        )
        log.info(
            "[%s] Discovery run %d starting with %d previously surfaced prospects",
            game.name,
            run_index + 1,
            sum(len(handles) for handles in seen_handles_by_platform.values()),
        )

    def _build_sources(
        self,
        game: Game,
        limit_per_source: int,
        *,
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
            effective_source_name = self.resolve_source_name(
                source_name, self._runtime
            )
            try:
                source_cls = get_source(effective_source_name)
                source = source_cls.build(self._runtime)
            except KeyError:
                log.warning(
                    "[%s] Unknown discovery source %r - skipping",
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
            self._log_selected_source(
                game.name, source_name, effective_source_name
            )
            sources.append((source, source_limit))

        return sources

    def _log_selected_source(
        self,
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
            "[%s] %s",
            game_name,
            labels.get(effective_source, effective_source),
        )

    def _summarize_results(
        self, results: Sequence[DiscoveryRunSummary | BaseException]
    ) -> DiscoveryRunSummary:
        totals: DiscoveryRunSummary = {
            "discovered": 0,
            "scored": 0,
            "imported": 0,
        }
        for result in results:
            if isinstance(result, dict):
                for key in totals:
                    totals[key] += result[key]
        return totals

    def _record_run_completed(
        self,
        run_id: str | None,
        totals: DiscoveryRunSummary,
    ) -> None:
        if run_id is None or self._metrics_service is None:
            return
        self._metrics_service.record_discovery_run_completed(
            run_id,
            completed_at=datetime.now(UTC).isoformat(),
            discovered_count=totals["discovered"],
            scored_count=totals["scored"],
            queued_count=totals["imported"],
        )

    def _record_run_failed(self, run_id: str | None, exc: Exception) -> None:
        if run_id is None or self._metrics_service is None:
            return
        self._metrics_service.record_discovery_run_failed(
            run_id,
            failed_at=datetime.now(UTC).isoformat(),
            error_message=str(exc),
        )

    async def _run_source(
        self,
        source: CandidateSource,
        *,
        game: Game,
        limit_per_source: int,
        templates: list[MessageTemplate],
        run_id: str | None,
        run_index: int,
        queue_budget: RunQueueBudget,
        excluded_handles: set[str] | None,
    ) -> DiscoveryRunSummary:
        counts: DiscoveryRunSummary = {
            "discovered": 0,
            "scored": 0,
            "imported": 0,
        }
        excluded = excluded_handles or set()

        source_platform = source.platform or ""
        page_cursors = load_cursors(
            game.game_id, source_platform, self._db_path
        )
        discovered_handles: set[str] = set()

        try:
            await self._consume_source_batches(
                source,
                game=game,
                limit_per_source=limit_per_source,
                templates=templates,
                page_cursors=page_cursors,
                run_id=run_id,
                counts=counts,
                run_index=run_index,
                queue_budget=queue_budget,
                excluded_handles=excluded,
                discovered_handles=discovered_handles,
            )
        except QuotaExceededError:
            log.warning(
                "[%s] YouTube API quota exhausted - falling back to scraper",
                game.name,
            )
            try:
                fallback_cls = get_source(Source.YOUTUBE)
                fallback_source = fallback_cls.build(self._runtime)
                await self._consume_source_batches(
                    fallback_source,
                    game=game,
                    limit_per_source=max(
                        0, limit_per_source - len(discovered_handles)
                    ),
                    templates=templates,
                    page_cursors={},
                    run_id=run_id,
                    counts=counts,
                    run_index=run_index,
                    queue_budget=queue_budget,
                    excluded_handles=excluded | discovered_handles,
                    discovered_handles=discovered_handles,
                )
            except Exception as exc:
                log.error(
                    "[%s] Scraping fallback also failed: %s", game.name, exc
                )
                return counts
        except Exception as exc:
            log.error("[%s] Discovery failed: %s", game.name, exc)
            return counts

        if (
            not queue_budget.should_stop()
            and isinstance(source, YouTubeAPISource)
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
                fallback_source = fallback_cls.build(self._runtime)
                await self._consume_source_batches(
                    fallback_source,
                    game=game,
                    limit_per_source=remaining,
                    templates=templates,
                    page_cursors={},
                    run_id=run_id,
                    counts=counts,
                    run_index=run_index,
                    queue_budget=queue_budget,
                    excluded_handles=excluded | discovered_handles,
                    discovered_handles=discovered_handles,
                )
            except Exception as exc:
                log.warning(
                    "[%s] YouTube scrape supplement failed: %s",
                    game.name,
                    exc,
                )

        log.info(
            "[%s] Done - discovered %d, scored %d, imported %d new prospects",
            game.name,
            counts["discovered"],
            counts["scored"],
            counts["imported"],
        )
        return counts

    async def _consume_source_batches(
        self,
        source: CandidateSource,
        *,
        game: Game,
        limit_per_source: int,
        templates: list[MessageTemplate],
        page_cursors: dict[str, str],
        run_id: str | None,
        counts: DiscoveryRunSummary,
        run_index: int,
        queue_budget: RunQueueBudget,
        excluded_handles: set[str],
        discovered_handles: set[str],
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
                await self._process_candidates_batch(
                    candidates,
                    game=game,
                    templates=templates,
                    run_id=run_id,
                    counts=counts,
                    queue_budget=queue_budget,
                )
                if queue_budget.should_stop():
                    break
        finally:
            if source_platform:
                save_cursors(
                    game.game_id, source_platform, page_cursors, self._db_path
                )

    async def _process_candidates_batch(
        self,
        candidates: list[CandidateRecord],
        *,
        game: Game,
        templates: list[MessageTemplate],
        run_id: str | None,
        counts: DiscoveryRunSummary,
        queue_budget: RunQueueBudget,
    ) -> None:
        prospects = [
            upsert_prospect(candidate, self._db_path)
            for candidate in candidates
        ]
        if not prospects:
            return

        base_scores = {
            prospect.prospect_id: self._score_prospect(game, prospect)
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
                "[%s] Run queue cap already satisfied; skipping batch",
                game.name,
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
            reserved_llm = 0

            if self._anthropic_api_key:
                llm_scores = load_cached_llm_scores(
                    game.game_id, prospects, self._db_path
                )
                (
                    needs_llm,
                    immediate_prospects,
                    reserved_llm,
                ) = await self._prepare_llm_work(
                    game, prospects, llm_scores, queue_budget
                )
            else:
                needs_llm = []

            await self._score_and_queue_prospects(
                immediate_prospects,
                game=game,
                templates=templates,
                llm_scores=llm_scores,
                run_id=run_id,
                counts=counts,
                queue_budget=queue_budget,
            )

            if self._anthropic_api_key and needs_llm:
                await self._score_llm_batches(
                    needs_llm,
                    game=game,
                    templates=templates,
                    llm_scores=llm_scores,
                    run_id=run_id,
                    counts=counts,
                    queue_budget=queue_budget,
                    reserved_llm=reserved_llm,
                )
            elif self._anthropic_api_key:
                await queue_budget.release_llm_slots(reserved_llm, attempted=0)
        finally:
            await queue_budget.release_evaluation_slots(reserved_evaluations)

    async def _prepare_llm_work(
        self,
        game: Game,
        prospects: list[Prospect],
        llm_scores: dict[str, LLMFitScores],
        queue_budget: RunQueueBudget,
    ) -> tuple[list[Prospect], list[Prospect], int]:
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
            needs_llm_ids = {prospect.prospect_id for prospect in needs_llm}

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
        return needs_llm, immediate_prospects, reserved_llm

    async def _score_llm_batches(
        self,
        needs_llm: list[Prospect],
        *,
        game: Game,
        templates: list[MessageTemplate],
        llm_scores: dict[str, LLMFitScores],
        run_id: str | None,
        counts: DiscoveryRunSummary,
        queue_budget: RunQueueBudget,
        reserved_llm: int,
    ) -> None:
        llm_scored_count = 0
        llm_attempted_count = 0
        for batch in self._chunked(needs_llm, _LLM_RESULT_BATCH_SIZE):
            if queue_budget.should_stop():
                break
            llm_attempted_count += len(batch)
            try:
                new_scores = await self._llm_score_batch(
                    game, batch, self._anthropic_api_key
                )
                llm_scores.update(new_scores)
                llm_scored_count += len(new_scores)
            except Exception as exc:
                log.warning(
                    "[%s] LLM batch scoring failed, using keyword fallback: %s",
                    game.name,
                    exc,
                )
            await self._score_and_queue_prospects(
                batch,
                game=game,
                templates=templates,
                llm_scores=llm_scores,
                run_id=run_id,
                counts=counts,
                queue_budget=queue_budget,
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

    async def _score_and_queue_prospects(
        self,
        prospects: list[Prospect],
        *,
        game: Game,
        templates: list[MessageTemplate],
        llm_scores: dict[str, LLMFitScores],
        run_id: str | None,
        counts: DiscoveryRunSummary,
        queue_budget: RunQueueBudget,
    ) -> None:
        for prospect in prospects:
            if queue_budget.should_stop():
                return
            llm = llm_scores.get(prospect.prospect_id)
            score = self._score_prospect(
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
                "llm" if llm else "keyword",
            )

            inserted = await self._queue_scored_prospect(
                prospect,
                game=game,
                templates=templates,
                score=score,
                llm=llm,
                run_id=run_id,
                counts=counts,
                queue_budget=queue_budget,
            )
            if inserted is None:
                continue
            if inserted:
                log.debug("[%s]   └─ queued as new prospect", game.name)
            else:
                log.debug("[%s]   └─ refreshed existing prospect", game.name)

    async def _queue_scored_prospect(
        self,
        prospect: Prospect,
        *,
        game: Game,
        templates: list[MessageTemplate],
        score: ScoreBreakdown,
        llm: LLMFitScores | None,
        run_id: str | None,
        counts: DiscoveryRunSummary,
        queue_budget: RunQueueBudget,
    ) -> bool | None:
        if score.final_score < _MINIMUM_QUEUE_SCORE:
            self._record_score_observation(
                run_id=run_id,
                game=game,
                score=score.final_score,
                queued=False,
            )
            log.debug(
                "[%s]   dropped (score %.2f < %.2f)",
                game.name,
                score.final_score,
                _MINIMUM_QUEUE_SCORE,
            )
            return None

        matched_template = find_template(templates, prospect.platform)
        subject_line, body_text = self._render_draft_content(
            template=matched_template,
            prospect=prospect,
            game=game,
            fit_reason=score.fit_summary,
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
            db_path=self._db_path,
        )
        inserted = draft_status == "inserted"
        self._record_score_observation(
            run_id=run_id,
            game=game,
            score=score.final_score,
            queued=inserted,
        )
        if inserted:
            counts["imported"] += 1
            return True
        if draft_status == "cap_reached":
            log.debug("[%s]   skipped (run queue cap reached)", game.name)
            return None
        return False

    def _record_score_observation(
        self,
        *,
        run_id: str | None,
        game: Game,
        score: float,
        queued: bool,
    ) -> None:
        if run_id is None or self._metrics_service is None:
            return
        self._metrics_service.record_prospect_score(
            run_id,
            user_id=game.user_id,
            game_id=game.game_id,
            score=score,
            queued=queued,
            occurred_at=datetime.now(UTC).isoformat(),
        )

    def _render_draft_content(
        self,
        *,
        template: MessageTemplate | None,
        prospect: Prospect,
        game: Game,
        fit_reason: str,
    ) -> tuple[str | None, str]:
        subject_line: str | None = None
        body_text = (
            f"Hi {prospect.display_name},\n\n"
            f"I'd love to share my game {game.name} with you.\n"
        )

        if template is None:
            return subject_line, body_text

        body_text = render_template(
            template.body_template,
            creator_name=prospect.display_name,
            game_name=game.name,
            fit_reason=fit_reason,
        )
        if template.subject_template:
            subject_line = render_template(
                template.subject_template,
                creator_name=prospect.display_name,
                game_name=game.name,
                fit_reason=fit_reason,
            )
        return subject_line, body_text

    @staticmethod
    def _chunked(items: list[Prospect], size: int) -> list[list[Prospect]]:
        return [items[i : i + size] for i in range(0, len(items), size)]
