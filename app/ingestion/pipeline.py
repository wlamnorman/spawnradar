"""Ingestion pipeline: orchestrates sources → scoring → DB upsert.

The pipeline is idempotent: running it twice for the same game will not create
duplicate prospects or draft items (uses UPSERT on natural keys).
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime

from app.games.models import Game
from app.games.repository import MessageTemplateRepository
from app.ingestion.base import CandidateRecord
from app.ingestion.constants import YOUTUBE_DISCOVERY_LIMIT
from app.ingestion.youtube import YouTubeSource
from app.ingestion.youtube_api import QuotaExceededError, YouTubeAPISource
from app.prospects.models import Prospect
from app.scoring.engine import score_prospect
from app.scoring.llm_engine import LLMFitScores, llm_score_batch

log = logging.getLogger(__name__)


async def run_ingestion(
    game: Game,
    db_path: str,
    limit_per_source: int = 30,
    youtube_api_key: str = "",
    anthropic_api_key: str = "",
    youtube_cache_dir: str = "",
) -> dict:
    """Run the full discovery → scoring → import pipeline for a game.

    Uses the YouTube Data API if an API key is configured, falling back to
    the scraping source if the key is absent or the daily quota is exhausted.
    """
    template_repo = MessageTemplateRepository(db_path)
    templates = template_repo.list_by_game(game.game_id)
    youtube_limit = youtube_candidate_limit(limit_per_source)

    if youtube_api_key:
        log.info("[%s] Discovery source: YouTube Data API", game.name)
        youtube: YouTubeAPISource | YouTubeSource = YouTubeAPISource(
            youtube_api_key, cache_dir=youtube_cache_dir or None
        )
    else:
        log.info(
            "[%s] Discovery source: scraping fallback (no API key)", game.name
        )
        youtube = YouTubeSource()

    log.info(
        "[%s] LLM scoring: %s",
        game.name,
        "enabled (Haiku)"
        if anthropic_api_key
        else "disabled (keyword fallback)",
    )

    results = await asyncio.gather(
        _run_source(
            youtube,
            game,
            youtube_limit,
            templates,
            db_path,
            anthropic_api_key,
        ),
        return_exceptions=True,
    )

    totals: dict[str, int] = {"discovered": 0, "scored": 0, "imported": 0}
    for r in results:
        if isinstance(r, dict):
            for k in totals:
                totals[k] += r[k]

    return totals


def youtube_candidate_limit(limit_per_source: int) -> int:
    """Return the effective YouTube discovery cap for a run."""
    return min(limit_per_source, YOUTUBE_DISCOVERY_LIMIT)


async def _run_source(
    source,
    game: Game,
    limit_per_source: int,
    templates: list,
    db_path: str,
    anthropic_api_key: str = "",
) -> dict:
    """Discover, score, and import prospects for a single source.

    Step 1: Discover candidates.
    Step 2: Upsert all prospects into the DB.
    Step 3: LLM-score all prospects concurrently (if key configured).
    Step 4: Compute final scores and upsert draft items.
    """
    counts: dict[str, int] = {"discovered": 0, "scored": 0, "imported": 0}

    try:
        candidates: list[CandidateRecord] = await source.discover(
            game, limit_per_source
        )
    except QuotaExceededError:
        log.warning(
            "[%s] YouTube API quota exhausted — falling back to scraper",
            game.name,
        )
        try:
            candidates = await YouTubeSource().discover(game, limit_per_source)
        except Exception as e:
            log.error("[%s] Scraping fallback also failed: %s", game.name, e)
            return counts
    except Exception as e:
        log.error("[%s] Discovery failed: %s", game.name, e)
        return counts

    counts["discovered"] = len(candidates)
    log.info("[%s] Discovered %d candidates", game.name, len(candidates))

    # Upsert all prospects first so we have IDs for batch scoring
    prospects = [_upsert_prospect(c, db_path) for c in candidates]

    # LLM batch scoring — only for prospects that need it
    llm_scores: dict[str, LLMFitScores] = {}
    if anthropic_api_key:
        # 1. Reuse any scores already stored from a previous run
        llm_scores = _load_cached_llm_scores(game.game_id, prospects, db_path)
        cached_count = len(llm_scores)

        # 2. Only call the LLM for prospects we haven't scored yet AND that
        #    have enough text data for the model to work with
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
                    "[%s] LLM scored %d/%d channels",
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
        # -----------------------------------------------------------------------
        # Score the prospect (LLM overrides where available, keywords elsewhere)
        # -----------------------------------------------------------------------
        llm = llm_scores.get(prospect.prospect_id)
        score = score_prospect(
            game,
            prospect,
            genre_fit_override=llm.genre_fit if llm else None,
            audience_fit_override=llm.audience_fit if llm else None,
            format_fit_override=llm.format_fit if llm else None,
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
            log.debug(
                "[%s]   └─ dropped (score %.2f < 0.20)",
                game.name,
                score.final_score,
            )
            continue

        # -----------------------------------------------------------------------
        # 3. Determine suggested action
        # -----------------------------------------------------------------------
        if score.final_score >= 0.65:
            suggested_action = "Approve"
        elif score.final_score >= 0.45:
            suggested_action = "Review"
        else:
            suggested_action = "Backlog"

        # -----------------------------------------------------------------------
        # 4. Find best-matching template
        # -----------------------------------------------------------------------
        matched_template = _find_template(templates, prospect.platform)

        subject_line: str | None = None
        body_text = f"Hi {prospect.display_name},\n\nI'd love to share my game {game.name} with you.\n"

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

        # -----------------------------------------------------------------------
        # 5. Upsert draft item
        # -----------------------------------------------------------------------
        llm = llm_scores.get(prospect.prospect_id)
        score_breakdown_json = json.dumps(
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

        _upsert_draft_item(
            game_id=game.game_id,
            prospect_id=prospect.prospect_id,
            template_id=matched_template.template_id
            if matched_template
            else None,
            subject_line=subject_line,
            body_text=body_text,
            priority_score=score.final_score,
            suggested_action=suggested_action,
            fit_summary=score.fit_summary,
            score_breakdown=score_breakdown_json,
            db_path=db_path,
        )
        counts["imported"] += 1
        log.debug("[%s]   └─ imported (%s)", game.name, suggested_action)

    log.info(
        "[%s] Done — discovered %d, scored %d, imported %d",
        game.name,
        counts["discovered"],
        counts["scored"],
        counts["imported"],
    )
    return counts


def _upsert_prospect(candidate: CandidateRecord, db_path: str) -> Prospect:
    """Insert or update a prospect, returning the persisted record."""
    from app.database import get_connection

    now = datetime.now(UTC).isoformat()
    raw_json = json.dumps(candidate.raw_data)

    with get_connection(db_path) as conn:
        # Check if prospect already exists by platform + handle
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
        raw_data=json.loads(row["raw_data"] or "{}"),
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
    suggested_action: str,
    fit_summary: str,
    score_breakdown: str,
    db_path: str,
) -> None:
    """Insert or update a draft item for this game + prospect pair."""
    from app.database import get_connection

    now = datetime.now(UTC).isoformat()

    with get_connection(db_path) as conn:
        existing = conn.execute(
            "SELECT draft_item_id, status FROM draft_items WHERE game_id = ? AND prospect_id = ?",
            (game_id, prospect_id),
        ).fetchone()

        if existing is not None:
            # Only update metadata; preserve any user edits to body/status
            conn.execute(
                """
                UPDATE draft_items
                SET priority_score = ?, suggested_action = ?, fit_summary = ?,
                    score_breakdown = ?, updated_at = ?
                WHERE draft_item_id = ?
                """,
                (
                    priority_score,
                    suggested_action,
                    fit_summary,
                    score_breakdown,
                    now,
                    existing["draft_item_id"],
                ),
            )
        else:
            draft_item_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO draft_items
                    (draft_item_id, game_id, prospect_id, template_id, subject_line,
                     body_text, status, priority_score, suggested_action, fit_summary,
                     score_breakdown, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?)
                """,
                (
                    draft_item_id,
                    game_id,
                    prospect_id,
                    template_id,
                    subject_line,
                    body_text,
                    priority_score,
                    suggested_action,
                    fit_summary,
                    score_breakdown,
                    now,
                    now,
                ),
            )


def _has_scoreable_text(prospect: Prospect) -> bool:
    """True if the channel has enough text for the LLM to make a meaningful judgment."""
    has_description = bool(
        prospect.description and len(prospect.description.strip()) > 20
    )
    has_titles = bool(prospect.raw_data.get("recent_video_titles"))
    return has_description or has_titles


def _load_cached_llm_scores(
    game_id: str, prospects: list[Prospect], db_path: str
) -> dict[str, LLMFitScores]:
    """Read any LLM scores already stored in draft_items from previous runs."""
    from app.database import get_connection

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
        breakdown = json.loads(row["score_breakdown"] or "{}")
        if not breakdown.get("llm_scored"):
            continue
        cached[row["prospect_id"]] = LLMFitScores(
            genre_fit=float(breakdown.get("genre_fit", 0.0)),
            audience_fit=float(breakdown.get("audience_fit", 0.0)),
            format_fit=float(breakdown.get("format_fit", 0.5)),
            fit_summary=row["fit_summary"] or "",
            why_selected=breakdown.get("why_selected", ""),
        )

    return cached


def _find_template(templates: list, platform: str):
    """Find the best-matching template for a prospect's platform."""
    # Map platform to channel type
    channel_map = {
        "youtube": "youtube_dm",
        "reddit": "reddit_dm",
    }
    preferred_channel = channel_map.get(platform, "email")

    for tpl in templates:
        if tpl.channel == preferred_channel:
            return tpl
    # Fall back to any template
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
