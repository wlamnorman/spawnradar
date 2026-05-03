"""Creator state tracking and enrichment helpers.

Extracted from ``discovery.py`` — see that module's docstring for the full
pipeline overview.
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PROFILE_TTL_DAYS = 7
DEEPEN_MAX_GAMES = 5  # only deepen creators with fewer than this many games


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class _CreatorState:
    """Cached state for a known broadcaster — enrichment + contacts in one query."""

    account_id: str
    recently_enriched: bool
    has_contacts: bool
    clip_cursor: str | None
    clips_exhausted: bool
    games_played_count: int


# ---------------------------------------------------------------------------
# Functions
# ---------------------------------------------------------------------------


def update_clip_state(
    db_path: str,
    account_id: str,
    cursor: str | None,
    exhausted: bool,
) -> None:
    """Persist updated clip cursor + exhaustion flag."""
    from app.database import get_connection

    with get_connection(db_path) as conn:
        conn.execute(
            """
            UPDATE twitch_profiles_latest
            SET clip_cursor = ?, clips_exhausted = ?
            WHERE account_id = ?
            """,
            (cursor, int(exhausted), account_id),
        )


def is_recently_enriched(db_path: str, external_id: str) -> bool:
    """Return True if this broadcaster was enriched within the TTL window.

    Used to skip re-enrichment on repeat crawl runs, freeing API budget
    for discovering new creators instead.
    """
    from app.database import get_connection

    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT tp.fetched_at FROM twitch_profiles_latest tp
            JOIN source_accounts sa ON tp.account_id = sa.account_id
            WHERE sa.external_id = ? AND sa.platform = 'twitch'
            LIMIT 1
            """,
            (external_id,),
        ).fetchone()
    if row is None:
        return False
    from datetime import UTC, datetime, timedelta

    try:
        fetched = datetime.fromisoformat(row[0])
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=UTC)
        return (datetime.now(UTC) - fetched) < timedelta(
            days=_PROFILE_TTL_DAYS
        )
    except (ValueError, TypeError):
        return False


def get_creator_state(db_path: str, external_id: str) -> _CreatorState | None:
    """Fetch all needed enrichment state in one DB query.

    Returns ``None`` if the broadcaster is not in the DB at all.
    """
    from app.database import get_connection

    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT
                sa.account_id,
                tp.fetched_at,
                tp.clip_cursor,
                tp.clips_exhausted,
                (SELECT COUNT(*) FROM creator_games_played cgp
                 WHERE cgp.account_id = sa.account_id) AS games_count,
                (SELECT 1 FROM contact_points cp
                 WHERE cp.account_id = sa.account_id LIMIT 1) AS has_contact
            FROM source_accounts sa
            LEFT JOIN twitch_profiles_latest tp ON tp.account_id = sa.account_id
            WHERE sa.external_id = ? AND sa.platform = 'twitch'
            LIMIT 1
            """,
            (external_id,),
        ).fetchone()
    if row is None or row["account_id"] is None:
        return None

    # Check TTL
    recently_enriched = False
    fetched_at = row["fetched_at"]
    if fetched_at:
        from datetime import UTC, datetime, timedelta

        try:
            fetched = datetime.fromisoformat(fetched_at)
            if fetched.tzinfo is None:
                fetched = fetched.replace(tzinfo=UTC)
            recently_enriched = (datetime.now(UTC) - fetched) < timedelta(
                days=_PROFILE_TTL_DAYS
            )
        except (ValueError, TypeError):
            pass

    return _CreatorState(
        account_id=row["account_id"],
        recently_enriched=recently_enriched,
        has_contacts=row["has_contact"] is not None,
        clip_cursor=row["clip_cursor"],
        clips_exhausted=bool(row["clips_exhausted"]),
        games_played_count=row["games_count"],
    )
