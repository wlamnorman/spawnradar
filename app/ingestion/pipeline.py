"""Ingestion pipeline: orchestrates sources → scoring → DB upsert.

The pipeline is idempotent: running it twice for the same game will not create
duplicate prospects or draft items (uses UPSERT on natural keys).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING

# Import sources package so all sources self-register with the registry
import app.ingestion.sources  # noqa: F401
from app.billing.repository import DiscoveryRunRepository
from app.database import get_connection
from app.games.models import Game
from app.games.repository import MessageTemplateRepository
from app.ingestion.base import CandidateRecord, CandidateSource, SourceRuntime
from app.ingestion.constants import YOUTUBE_DISCOVERY_LIMIT
from app.ingestion.registry import Source, get_source
from app.ingestion.sources.youtube_api import (
    QuotaExceededError,
)
from app.json_codec import dump_json, load_json_object
from app.prospects.models import Prospect
from app.scoring.engine import score_prospect
from app.scoring.llm_engine import LLMFitScores, llm_score_batch

if TYPE_CHECKING:
    from app.metrics.service import MetricsService

log = logging.getLogger(__name__)


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
) -> dict:
    """Run the full discovery → scoring → import pipeline for a game.

    Sources are determined by game.discovery_sources (default: youtube + reddit).
    Uses the YouTube Data API if an API key is configured, falling back to
    the scraping source if the key is absent or the daily quota is exhausted.
    """
    try:
        template_repo = MessageTemplateRepository(db_path)
        templates = template_repo.list_by_game(game.game_id)
        runtime = SourceRuntime(
            youtube_api_key=youtube_api_key,
            youtube_cache_dir=youtube_cache_dir,
            twitch_client_id=twitch_client_id,
            twitch_client_secret=twitch_client_secret,
        )
        run_index = _game_run_index(game.game_id, db_path)
        seen_handles_by_platform = _seen_handles_for_game(
            game.game_id, db_path
        )

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

        sources = _build_sources(game, runtime, limit_per_source)

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
                excluded_handles=seen_handles_by_platform.get(
                    source.platform or "", set()
                ),
            )
            for source, limit in sources
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        # Expected per-source discovery failures are handled inside _run_source.
        # Anything still raising here is a real pipeline failure and should mark
        # the overall run as failed.
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


def _build_sources(
    game: Game,
    runtime: SourceRuntime,
    limit_per_source: int,
) -> list[tuple[CandidateSource, int]]:
    """Build source instances for the game's configured discovery sources."""
    sources: list[tuple[CandidateSource, int]] = []

    for source_name in game.discovery_sources:
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


def _resolve_source_name(
    source_name: Source, runtime: SourceRuntime
) -> Source:
    """Resolve aliases like YouTube → YouTube API when credentials exist."""
    if source_name == Source.YOUTUBE and runtime.youtube_api_key:
        return Source.YOUTUBE_API
    return source_name


def _log_selected_source(
    game_name: str,
    requested_source: Source,
    effective_source: Source,
) -> None:
    """Emit a concise log line for the source variant used this run."""
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
    anthropic_api_key: str = "",
    runtime: SourceRuntime | None = None,
    run_id: str | None = None,
    metrics_service: MetricsService | None = None,
    *,
    run_index: int = 0,
    excluded_handles: set[str] | None = None,
) -> dict:
    """Discover, score, and import prospects for a single source.

    Step 1: Discover candidates.
    Step 2: Upsert all prospects into the DB.
    Step 3: LLM-score all prospects concurrently (if key configured).
    Step 4: Compute final scores and upsert draft items.
    """
    counts: dict[str, int] = {"discovered": 0, "scored": 0, "imported": 0}
    excluded = excluded_handles or set()

    # Load per-query page cursors so this run resumes where the last one ended
    source_platform = source.platform or ""
    page_cursors = _load_cursors(game.game_id, source_platform, db_path)

    try:
        candidates: list[CandidateRecord] = await source.discover(
            game,
            limit_per_source,
            run_index=run_index,
            excluded_handles=excluded,
            page_cursors=page_cursors,
        )
    except QuotaExceededError:
        log.warning(
            "[%s] YouTube API quota exhausted — falling back to scraper",
            game.name,
        )
        try:
            fallback_cls = get_source(Source.YOUTUBE)
            fallback_source = fallback_cls.build(runtime or SourceRuntime())
            candidates = await fallback_source.discover(
                game,
                limit_per_source,
                run_index=run_index,
                excluded_handles=excluded,
            )
        except Exception as e:
            log.error("[%s] Scraping fallback also failed: %s", game.name, e)
            return counts
    except Exception as e:
        log.error("[%s] Discovery failed: %s", game.name, e)
        return counts

    counts["discovered"] = len(candidates)
    log.info(
        "[%s] Discovered %d candidates (%d previously surfaced excluded)",
        game.name,
        len(candidates),
        len(excluded),
    )

    # Persist updated cursors so the next run continues from where we left off
    if source_platform and page_cursors:
        _save_cursors(game.game_id, source_platform, page_cursors, db_path)

    # Upsert all prospects first so we have IDs for batch scoring
    prospects = [_upsert_prospect(c, db_path) for c in candidates]

    # LLM batch scoring — only for prospects that need it
    llm_scores: dict[str, LLMFitScores] = {}
    if anthropic_api_key:
        llm_scores = _load_cached_llm_scores(game.game_id, prospects, db_path)
        cached_count = len(llm_scores)

        needs_llm = [
            p
            for p in prospects
            if p.prospect_id not in llm_scores and _has_scoreable_text(p)
        ]
        skipped_count = len(prospects) - cached_count - len(needs_llm)

        log.info(
            "[%s] LLM scoring: %d to score, %d cached, %d skipped (no text)",
            game.name,
            len(needs_llm),
            cached_count,
            skipped_count,
        )

        if needs_llm:
            try:
                new_scores = await llm_score_batch(
                    game, needs_llm, anthropic_api_key
                )
                llm_scores.update(new_scores)
                log.info(
                    "[%s] LLM scored %d/%d prospects",
                    game.name,
                    len(new_scores),
                    len(needs_llm),
                )
            except Exception as e:
                log.warning(
                    "[%s] LLM batch scoring failed, using keyword fallback: %s",
                    game.name,
                    e,
                )

    for prospect in prospects:
        llm = llm_scores.get(prospect.prospect_id)
        score = score_prospect(
            game,
            prospect,
            genre_fit_override=llm.genre_fit if llm else None,
            audience_fit_override=llm.audience_fit if llm else None,
            format_fit_override=llm.format_fit if llm else None,
            platform_fit_override=llm.platform_fit if llm else None,
            fit_summary_override=llm.fit_summary if llm else None,
            why_selected_override=llm.why_selected if llm else None,
        )
        counts["scored"] += 1

        log.debug(
            "[%s] %-35s  final=%.2f  genre=%.2f  audience=%.2f  format=%.2f  activity=%.2f  %s",
            game.name,
            prospect.display_name[:35],
            score.final_score,
            score.genre_fit,
            score.audience_fit,
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

        matched_template = _find_template(templates, prospect.platform)

        subject_line: str | None = None
        body_text = (
            f"Hi {prospect.display_name},\n\n"
            f"I'd love to share my game {game.name} with you.\n"
        )

        if matched_template is not None:
            fit_reason = score.fit_summary
            body_text = _render_template(
                matched_template.body_template,
                creator_name=prospect.display_name,
                game_name=game.name,
                fit_reason=fit_reason,
            )
            if matched_template.subject_template:
                subject_line = _render_template(
                    matched_template.subject_template,
                    creator_name=prospect.display_name,
                    game_name=game.name,
                    fit_reason=fit_reason,
                )

        llm = llm_scores.get(prospect.prospect_id)
        score_breakdown_json = dump_json(
            {
                "genre_fit": score.genre_fit,
                "audience_fit": score.audience_fit,
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

        inserted = _upsert_draft_item(
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
        else:
            log.debug("[%s]   └─ refreshed existing prospect", game.name)

    log.info(
        "[%s] Done — discovered %d, scored %d, imported %d new prospects",
        game.name,
        counts["discovered"],
        counts["scored"],
        counts["imported"],
    )
    return counts


def _upsert_prospect(candidate: CandidateRecord, db_path: str) -> Prospect:
    """Insert or update a prospect, returning the persisted record."""
    now = datetime.now(UTC).isoformat()

    raw = dict(candidate.raw_data)
    raw["last_active_days"] = candidate.last_active_days
    raw["text_signals"] = candidate.text_signals
    raw["prospect_type"] = candidate.prospect_type
    raw_json = dump_json(raw)

    with get_connection(db_path) as conn:
        existing = conn.execute(
            "SELECT prospect_id FROM prospects WHERE platform = ? AND handle = ?",
            (candidate.platform, candidate.handle),
        ).fetchone()

        if existing is not None:
            prospect_id = existing["prospect_id"]
            conn.execute(
                """
                UPDATE prospects
                SET display_name = ?, profile_url = ?, contact_channel = ?,
                    contact_value = ?, audience_size = ?, engagement_rate = ?,
                    description = ?, raw_data = ?, updated_at = ?
                WHERE prospect_id = ?
                """,
                (
                    candidate.display_name,
                    candidate.profile_url,
                    candidate.contact_channel,
                    candidate.contact_value,
                    candidate.audience_size,
                    candidate.engagement_rate,
                    candidate.description,
                    raw_json,
                    now,
                    prospect_id,
                ),
            )
        else:
            prospect_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO prospects
                    (prospect_id, platform, handle, display_name, profile_url,
                     contact_channel, contact_value, audience_size, engagement_rate,
                     description, raw_data, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    prospect_id,
                    candidate.platform,
                    candidate.handle,
                    candidate.display_name,
                    candidate.profile_url,
                    candidate.contact_channel,
                    candidate.contact_value,
                    candidate.audience_size,
                    candidate.engagement_rate,
                    candidate.description,
                    raw_json,
                    now,
                    now,
                ),
            )

        row = conn.execute(
            "SELECT * FROM prospects WHERE prospect_id = ?", (prospect_id,)
        ).fetchone()

    return Prospect(
        prospect_id=row["prospect_id"],
        platform=row["platform"],
        handle=row["handle"],
        display_name=row["display_name"],
        profile_url=row["profile_url"],
        contact_channel=row["contact_channel"],
        contact_value=row["contact_value"],
        audience_size=row["audience_size"],
        engagement_rate=row["engagement_rate"],
        description=row["description"],
        raw_data=load_json_object(row["raw_data"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _upsert_draft_item(
    *,
    game_id: str,
    prospect_id: str,
    template_id: str | None,
    subject_line: str | None,
    body_text: str,
    priority_score: float,
    fit_summary: str,
    score_breakdown: str,
    db_path: str,
) -> bool:
    """Insert or update a draft item for this game + prospect pair.

    Returns True when a new queue item was inserted, False when an existing one
    was refreshed in place.
    """
    now = datetime.now(UTC).isoformat()

    with get_connection(db_path) as conn:
        existing = conn.execute(
            "SELECT draft_item_id, status FROM draft_items WHERE game_id = ? AND prospect_id = ?",
            (game_id, prospect_id),
        ).fetchone()

        if existing is not None:
            conn.execute(
                """
                UPDATE draft_items
                SET priority_score = ?, fit_summary = ?, score_breakdown = ?,
                    updated_at = ?
                WHERE draft_item_id = ?
                """,
                (
                    priority_score,
                    fit_summary,
                    score_breakdown,
                    now,
                    existing["draft_item_id"],
                ),
            )
            return False

        draft_item_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO draft_items
                (draft_item_id, game_id, prospect_id, template_id, subject_line,
                 body_text, status, priority_score, fit_summary,
                 score_breakdown, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?)
            """,
            (
                draft_item_id,
                game_id,
                prospect_id,
                template_id,
                subject_line,
                body_text,
                priority_score,
                fit_summary,
                score_breakdown,
                now,
                now,
            ),
        )
        return True


def _has_scoreable_text(prospect: Prospect) -> bool:
    """True if the prospect has enough text for the LLM to make a meaningful judgment."""
    has_description = bool(
        prospect.description and len(prospect.description.strip()) > 20
    )
    has_signals = bool(prospect.raw_data.get("text_signals"))
    return has_description or has_signals


def _load_cached_llm_scores(
    game_id: str, prospects: list[Prospect], db_path: str
) -> dict[str, LLMFitScores]:
    """Read any LLM scores already stored in draft_items from previous runs."""
    if not prospects:
        return {}

    prospect_ids = [p.prospect_id for p in prospects]
    placeholders = ",".join("?" * len(prospect_ids))

    cached: dict[str, LLMFitScores] = {}
    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT prospect_id, score_breakdown, fit_summary
            FROM draft_items
            WHERE game_id = ? AND prospect_id IN ({placeholders})
            """,
            [game_id, *prospect_ids],
        ).fetchall()

    for row in rows:
        breakdown = load_json_object(row["score_breakdown"])
        if not breakdown.get("llm_scored"):
            continue
        cached[row["prospect_id"]] = LLMFitScores(
            genre_fit=float(breakdown.get("genre_fit", 0.0)),
            audience_fit=float(breakdown.get("audience_fit", 0.0)),
            format_fit=float(breakdown.get("format_fit", 0.5)),
            platform_fit=float(breakdown.get("platform_fit", 0.5)),
            fit_summary=row["fit_summary"] or "",
            why_selected=breakdown.get("why_selected", ""),
        )

    return cached


def _find_template(templates: list, platform: str):
    """Find the best-matching template for a prospect's platform."""
    channel_map = {
        "youtube": "youtube_dm",
        "reddit": "reddit_dm",
        "twitch": "twitch_dm",
    }
    preferred_channel = channel_map.get(platform, "email")

    for tpl in templates:
        if tpl.channel == preferred_channel:
            return tpl
    return templates[0] if templates else None


def _render_template(
    template: str, *, creator_name: str, game_name: str, fit_reason: str
) -> str:
    """Render a template string by substituting {{placeholder}} variables."""
    return (
        template.replace("{{creator_name}}", creator_name)
        .replace("{{game_name}}", game_name)
        .replace("{{fit_reason}}", fit_reason)
    )


def _load_cursors(game_id: str, source: str, db_path: str) -> dict[str, str]:
    """Return the stored page-cursor dict for this game + source."""
    if not source:
        return {}
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT cursors FROM game_search_cursors WHERE game_id = ? AND source = ?",
            (game_id, source),
        ).fetchone()
    if row is None:
        return {}
    return load_json_object(row["cursors"])


def _save_cursors(
    game_id: str, source: str, cursors: dict[str, str], db_path: str
) -> None:
    """Persist the updated page-cursor dict for this game + source."""
    now = datetime.now(UTC).isoformat()
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO game_search_cursors (game_id, source, cursors, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(game_id, source) DO UPDATE
                SET cursors = excluded.cursors, updated_at = excluded.updated_at
            """,
            (game_id, source, dump_json(cursors), now),
        )


def _game_run_index(game_id: str, db_path: str) -> int:
    repo = DiscoveryRunRepository(db_path)
    run_count = repo.count_for_game(game_id)
    return max(0, run_count - 1)


def _seen_handles_for_game(game_id: str, db_path: str) -> dict[str, set[str]]:
    seen: dict[str, set[str]] = defaultdict(set)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT p.platform, p.handle
            FROM draft_items d
            JOIN prospects p ON d.prospect_id = p.prospect_id
            WHERE d.game_id = ?
            """,
            (game_id,),
        ).fetchall()

    for row in rows:
        platform = str(row["platform"] or "").strip()
        handle = str(row["handle"] or "").strip().lower()
        if platform and handle:
            seen[platform].add(handle)

    return dict(seen)
