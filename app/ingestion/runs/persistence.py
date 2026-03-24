"""Persistence and reuse helpers for discovery runs."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime

from app.billing.repository import DiscoveryRunRepository
from app.database import get_connection
from app.ingestion.base import CandidateRecord
from app.json_codec import dump_json, load_json_object
from app.prospects.models import Prospect
from app.scoring.llm_engine import LLMFitScores


def upsert_prospect(candidate: CandidateRecord, db_path: str) -> Prospect:
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


def has_scoreable_text(prospect: Prospect) -> bool:
    """True if the prospect has enough text for the LLM to make a judgment."""
    has_description = bool(
        prospect.description and len(prospect.description.strip()) > 20
    )
    has_signals = bool(prospect.raw_data.get("text_signals"))
    return has_description or has_signals


def load_cached_llm_scores(
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
            vibe_fit=float(
                breakdown.get("vibe_fit", breakdown.get("audience_fit", 0.0))
            ),
            format_fit=float(breakdown.get("format_fit", 0.5)),
            platform_fit=float(breakdown.get("platform_fit", 0.5)),
            fit_summary=row["fit_summary"] or "",
            why_selected=breakdown.get("why_selected", ""),
        )

    return cached


def find_template(templates: list, platform: str):
    """Find the best-matching template for a prospect's platform."""
    channel_map = {
        "youtube": "youtube_dm",
        "twitch": "twitch_dm",
    }
    preferred_channel = channel_map.get(platform, "email")

    for template in templates:
        if template.channel == preferred_channel:
            return template
    return templates[0] if templates else None


def render_template(
    template: str, *, creator_name: str, game_name: str, fit_reason: str
) -> str:
    """Render a template string by substituting {{placeholder}} variables."""
    return (
        template.replace("{{creator_name}}", creator_name)
        .replace("{{game_name}}", game_name)
        .replace("{{fit_reason}}", fit_reason)
    )


def load_cursors(game_id: str, source: str, db_path: str) -> dict[str, str]:
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


def save_cursors(
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


def game_run_index(game_id: str, db_path: str) -> int:
    """Return zero-based count of prior discovery runs for this game."""
    repo = DiscoveryRunRepository(db_path)
    run_count = repo.count_for_game(game_id)
    return max(0, run_count - 1)


def seen_handles_for_game(game_id: str, db_path: str) -> dict[str, set[str]]:
    """Return previously queued handles by platform for exclusion."""
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
