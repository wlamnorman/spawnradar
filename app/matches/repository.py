"""Read-only repository for match ranking queries.

This module owns its own SQL and does not depend on
app.creator_index.repository, so it can be developed independently.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from contextlib import nullcontext
from dataclasses import dataclass

from app.creator_index.matching import TagCounts, TagKey
from app.database import get_connection
from app.matches.models import (
    MATCH_DEFAULT_STATUS,
    MATCH_WORKFLOW_STATUS_ORDER,
    CreatorRankingProfile,
    MatchWorkflowState,
    MatchWorkflowStatus,
    RelevantGame,
)

SIMILAR_GAME_PLAY_BONUS_PER_GAME = 0.05
_LEGACY_WORKFLOW_STATUS_MAP = {
    "new": "suggested",
    "access_shared": "to_cover",
}


@dataclass(frozen=True)
class RankedSnapshotRow:
    """One ranked creator row before page slicing and hydration."""

    account_id: str
    coverage_score: float
    reach: int
    relevant_game_count: int
    workflow_status: MatchWorkflowStatus


def _game_tags_cte(
    game_tags: Sequence[TagKey],
) -> tuple[str, list[object]]:
    """Build a ``game_tags`` CTE from unified customer-game tag keys.

    Returns (sql_fragment, params) where ``sql_fragment`` is a
    ``SELECT ... UNION ALL SELECT ...`` block and ``params`` are the
    bind values.
    """
    parts: list[str] = []
    params: list[object] = []
    for tag_type, tag_id in game_tags:
        parts.append("SELECT ? AS tag_type, ? AS tag_id")
        params.extend((tag_type, tag_id))
    return " UNION ALL ".join(parts), params


def _int_values_cte(
    values: Sequence[int],
    *,
    column_name: str,
) -> tuple[str, list[object]]:
    """Build a one-column integer CTE or an empty one when no values exist."""
    normalized_values: list[int] = []
    seen: set[int] = set()
    for value in values:
        normalized = int(value)
        if normalized in seen:
            continue
        seen.add(normalized)
        normalized_values.append(normalized)

    if not normalized_values:
        return f"SELECT NULL AS {column_name} WHERE 0", []

    parts = [f"SELECT ? AS {column_name}" for _ in normalized_values]
    return " UNION ALL ".join(parts), [*normalized_values]


def _matches_status_included(
    workflow_status: MatchWorkflowStatus,
    status_filter: str,
) -> bool:
    """Return whether a cached row belongs in the requested status view."""
    if status_filter == "all":
        return workflow_status != "not_pursuing"
    if status_filter in MATCH_WORKFLOW_STATUS_ORDER:
        return workflow_status == status_filter
    return True


def _status_counts_for_rank_rows(
    rows: Sequence[RankedSnapshotRow],
) -> dict[MatchWorkflowStatus, int]:
    """Count workflow statuses across cached ranked rows."""
    counts: dict[MatchWorkflowStatus, int] = dict.fromkeys(
        MATCH_WORKFLOW_STATUS_ORDER, 0
    )
    for row in rows:
        counts[row.workflow_status] += 1
    return counts


class MatchRepository:
    """Query layer for ranked match data."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def connection(self):
        """Open a repository SQLite connection for batched read operations."""
        return get_connection(self._db_path)

    def _connection(self, conn: sqlite3.Connection | None):
        return nullcontext(conn) if conn is not None else self.connection()

    def resolve_similar_game_ids(
        self,
        similar_game_names: Sequence[str],
        *,
        conn: sqlite3.Connection | None = None,
    ) -> tuple[int, ...]:
        """Resolve one exact cached IGDB match per selected similar game."""
        normalized_names: list[str] = []
        seen: set[str] = set()
        for name in similar_game_names:
            normalized = name.strip().lower()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            normalized_names.append(normalized)

        if not normalized_names:
            return ()

        placeholders = ",".join("?" for _ in normalized_names)
        sql = f"""
            WITH ranked_matches AS (
                SELECT
                    LOWER(g.name) AS name_lower,
                    -- Resolve to parent (base) game when available
                    COALESCE(parent.igdb_id, g.igdb_id) AS igdb_id,
                    ROW_NUMBER() OVER (
                        PARTITION BY LOWER(g.name)
                        ORDER BY
                            g.first_release_date IS NULL,
                            g.first_release_date DESC,
                            g.last_synced_at DESC,
                            g.igdb_id DESC
                    ) AS match_rank
                FROM igdb_games g
                LEFT JOIN igdb_games parent
                    ON g.parent_game_id = parent.igdb_id
                WHERE LOWER(g.name) IN ({placeholders})
            )
            SELECT DISTINCT igdb_id
            FROM ranked_matches
            WHERE match_rank = 1
            ORDER BY igdb_id
        """
        with self._connection(conn) as db_conn:
            rows = db_conn.execute(sql, normalized_names).fetchall()
        return tuple(int(row["igdb_id"]) for row in rows)

    def query_creator_tag_counts(
        self,
        *,
        game_tags: Sequence[TagKey],
        account_ids: list[str] | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, TagCounts]:
        """Return per-creator counts for the customer game's target tags only.

        When *account_ids* is provided, only those creators are queried
        (used for page-level hydration).  Otherwise all creators with
        ``overlap_count >= 2`` are returned.
        """
        if not game_tags:
            return {}

        game_tags_sql, game_tags_params = _game_tags_cte(game_tags)

        if account_ids is not None:
            if not account_ids:
                return {}
            placeholders = ",".join("?" for _ in account_ids)
            sql = f"""
                WITH game_tags AS (
                    {game_tags_sql}
                )
                SELECT
                    cgp.account_id,
                    igt.tag_type,
                    igt.tag_id,
                    COUNT(*) AS tag_count
                FROM creator_games_played cgp
                JOIN igdb_game_tags igt ON igt.igdb_id = cgp.igdb_game_id
                JOIN game_tags gt ON gt.tag_type = igt.tag_type
                                  AND gt.tag_id = igt.tag_id
                WHERE cgp.igdb_game_id IS NOT NULL
                  AND cgp.account_id IN ({placeholders})
                GROUP BY cgp.account_id, igt.tag_type, igt.tag_id
                ORDER BY cgp.account_id
            """
            params: list[object] = [*game_tags_params, *account_ids]
        else:
            sql = f"""
                WITH game_tags AS (
                    {game_tags_sql}
                ),
                creator_target_tag_counts AS (
                    SELECT
                        cgp.account_id,
                        igt.tag_type,
                        igt.tag_id,
                        COUNT(*) AS tag_count
                    FROM creator_games_played cgp
                    JOIN igdb_game_tags igt ON igt.igdb_id = cgp.igdb_game_id
                    JOIN game_tags gt ON gt.tag_type = igt.tag_type
                                      AND gt.tag_id = igt.tag_id
                    WHERE cgp.igdb_game_id IS NOT NULL
                    GROUP BY cgp.account_id, igt.tag_type, igt.tag_id
                ),
                eligible_creators AS (
                    SELECT cttc.account_id, COUNT(*) AS overlap_count
                    FROM creator_target_tag_counts cttc
                    GROUP BY cttc.account_id
                    HAVING overlap_count >= 2
                )
                SELECT cttc.account_id, cttc.tag_type, cttc.tag_id, cttc.tag_count
                FROM creator_target_tag_counts cttc
                JOIN eligible_creators ec ON ec.account_id = cttc.account_id
                ORDER BY cttc.account_id
            """
            params = [*game_tags_params]

        with self._connection(conn) as db_conn:
            rows = db_conn.execute(sql, params).fetchall()

        result: dict[str, TagCounts] = {}
        for row in rows:
            account_id = str(row["account_id"])
            if account_id not in result:
                result[account_id] = {}
            raw_tag_id = row["tag_id"]
            tag_id = (
                int(raw_tag_id)
                if isinstance(raw_tag_id, int)
                else str(raw_tag_id)
            )
            result[account_id][(str(row["tag_type"]), tag_id)] = int(
                row["tag_count"]
            )
        return result

    def rank_scored_page(
        self,
        *,
        game_tags: Sequence[TagKey],
        total_weight: float,
        customer_game_id: str,
        similar_game_ids: Sequence[int] = (),
        min_coverage: float = 0.65,
        min_reach: int = 0,
        max_reach: int | None = None,
        min_relevant_games: int = 0,
        max_relevant_games: int | None = None,
        contact_methods: tuple[str, ...] = (),
        status_filter: str = "all",
        limit: int = 20,
        offset: int = 0,
        conn: sqlite3.Connection | None = None,
    ) -> tuple[
        list[tuple[str, float, int]],  # (account_id, coverage_score, reach)
        int,  # total_count
        int,  # reach_filter_max
        int,  # games_filter_max
        dict[MatchWorkflowStatus, int],  # status_counts
    ]:
        """Return a filtered page from the cached-ranked snapshot rows."""
        rows, reach_filter_max = self.rank_scored_snapshot(
            game_tags=game_tags,
            total_weight=total_weight,
            customer_game_id=customer_game_id,
            similar_game_ids=similar_game_ids,
            min_coverage=min_coverage,
            min_reach=min_reach,
            max_reach=max_reach,
            contact_methods=contact_methods,
            conn=conn,
        )
        status_counts = _status_counts_for_rank_rows(rows)
        status_rows = [
            row
            for row in rows
            if _matches_status_included(row.workflow_status, status_filter)
        ]
        games_filter_max = max(
            (row.relevant_game_count for row in status_rows),
            default=0,
        )
        filtered_rows = [
            row
            for row in status_rows
            if row.relevant_game_count >= min_relevant_games
            and (
                max_relevant_games is None
                or row.relevant_game_count <= max_relevant_games
            )
        ]
        total_count = len(filtered_rows)
        page_rows = [
            (row.account_id, row.coverage_score, row.reach)
            for row in filtered_rows[offset : offset + limit]
        ]
        return (
            page_rows,
            total_count,
            reach_filter_max,
            games_filter_max,
            status_counts,
        )

    def rank_scored_snapshot(
        self,
        *,
        game_tags: Sequence[TagKey],
        total_weight: float,
        customer_game_id: str,
        similar_game_ids: Sequence[int] = (),
        min_coverage: float = 0.65,
        min_reach: int = 0,
        max_reach: int | None = None,
        contact_methods: tuple[str, ...] = (),
        conn: sqlite3.Connection | None = None,
    ) -> tuple[
        list[RankedSnapshotRow],
        int,  # reach_filter_max
    ]:
        """Score and cache-ready hydrate ranked rows without page/status slicing."""
        if not game_tags or total_weight <= 0:
            return [], 0

        game_tags_sql, game_tags_params = _game_tags_cte(game_tags)
        similar_games_sql, similar_games_params = _int_values_cte(
            similar_game_ids,
            column_name="igdb_id",
        )
        max_possible_similar_bonus = (
            len({int(game_id) for game_id in similar_game_ids})
            * SIMILAR_GAME_PLAY_BONUS_PER_GAME
        )

        # --- Dynamic filter clauses ------------------------------------
        extra_where: list[str] = []
        extra_params: list[object] = []

        # Contact methods filter
        if contact_methods:
            contact_conditions: list[str] = []
            contact_params: list[object] = []
            for method in contact_methods:
                if method == "email":
                    contact_conditions.append(
                        "EXISTS (SELECT 1 FROM contact_points cp"
                        " WHERE cp.account_id = rf.account_id"
                        " AND cp.contact_type = 'email' AND cp.is_public = 1)"
                    )
                elif method == "discord":
                    contact_conditions.append(
                        "EXISTS (SELECT 1 FROM contact_points cp"
                        " WHERE cp.account_id = rf.account_id"
                        " AND cp.contact_type = 'discord' AND cp.is_public = 1)"
                    )
                elif method in ("twitch", "youtube"):
                    # Match by platform OR by social link containing
                    # the platform domain.
                    platform = method
                    if platform == "twitch":
                        domains = ("twitch.tv",)
                    else:
                        domains = ("youtube.com", "youtu.be")
                    domain_clauses = " OR ".join(
                        "cp.contact_value LIKE '%' || ? || '%'"
                        for _ in domains
                    )
                    contact_conditions.append(
                        f"(EXISTS (SELECT 1 FROM source_accounts sa_rf"
                        f" WHERE sa_rf.account_id = rf.account_id"
                        f" AND sa_rf.platform = '{platform}'"
                        f" AND sa_rf.canonical_url IS NOT NULL)"
                        f" OR EXISTS (SELECT 1 FROM contact_points cp"
                        f" WHERE cp.account_id = rf.account_id"
                        f" AND cp.contact_type = 'social_link'"
                        f" AND cp.is_public = 1"
                        f" AND ({domain_clauses})))"
                    )
                    contact_params.extend(domains)
                else:
                    # Social link platforms (x, instagram, tiktok, bluesky)
                    domain_map = {
                        "x": ("x.com", "twitter.com"),
                        "instagram": ("instagram.com",),
                        "tiktok": ("tiktok.com",),
                        "bluesky": ("bsky.app",),
                    }
                    domains = domain_map.get(method, ())
                    if domains:
                        domain_clauses = " OR ".join(
                            "cp.contact_value LIKE '%' || ? || '%'"
                            for _ in domains
                        )
                        contact_conditions.append(
                            "EXISTS (SELECT 1 FROM contact_points cp"
                            f" WHERE cp.account_id = rf.account_id"
                            f" AND cp.contact_type = 'social_link'"
                            f" AND cp.is_public = 1"
                            f" AND ({domain_clauses}))"
                        )
                        contact_params.extend(domains)
            if contact_conditions:
                extra_where.append(
                    "AND (" + " OR ".join(contact_conditions) + ")"
                )
                extra_params.extend(contact_params)

        extra_where_sql = "\n                  ".join(extra_where)

        scored_with_reach_sql = f"""
            WITH game_tags AS (
                {game_tags_sql}
            ),
            similar_games AS (
                {similar_games_sql}
            ),
            creator_tag_evidence AS (
                SELECT
                    cgp.account_id,
                    gt.tag_type,
                    gt.tag_id,
                    CASE
                        WHEN COUNT(DISTINCT cgp.igdb_game_id) = 1 THEN 0.93
                        WHEN COUNT(DISTINCT cgp.igdb_game_id) = 2 THEN 0.967
                        ELSE 1.0
                    END AS evidence
                FROM creator_games_played cgp
                JOIN igdb_game_tags igt ON igt.igdb_id = cgp.igdb_game_id
                JOIN game_tags gt ON gt.tag_type = igt.tag_type
                                  AND gt.tag_id = igt.tag_id
                WHERE cgp.igdb_game_id IS NOT NULL
                GROUP BY cgp.account_id, gt.tag_type, gt.tag_id
            ),
            creator_base_scores AS (
                SELECT
                    cte.account_id,
                    SUM(
                        CASE WHEN cte.tag_type = 'genre' THEN 3.0 ELSE 1.0 END
                        * cte.evidence
                    ) / ? AS base_coverage_score,
                    COUNT(*) AS overlap_count
                FROM creator_tag_evidence cte
                GROUP BY cte.account_id
            ),
            creator_similar_game_counts AS (
                SELECT
                    cbs.account_id,
                    COUNT(DISTINCT cgp.igdb_game_id) AS similar_game_count
                FROM creator_base_scores cbs
                JOIN creator_games_played cgp
                    ON cgp.account_id = cbs.account_id
                JOIN similar_games sg ON sg.igdb_id = cgp.igdb_game_id
                WHERE cbs.overlap_count >= 2
                  AND cbs.base_coverage_score + ? > ?
                  AND cgp.igdb_game_id IS NOT NULL
                GROUP BY cbs.account_id
            ),
            creator_scores AS (
                SELECT
                    cbs.account_id,
                    MIN(
                        1.0,
                        cbs.base_coverage_score
                        + (
                            COALESCE(csgc.similar_game_count, 0)
                            * {SIMILAR_GAME_PLAY_BONUS_PER_GAME}
                        )
                    ) AS coverage_score,
                    cbs.overlap_count
                FROM creator_base_scores cbs
                LEFT JOIN creator_similar_game_counts csgc
                    ON csgc.account_id = cbs.account_id
                WHERE cbs.overlap_count >= 2
                  AND cbs.base_coverage_score + ? > ?
            ),
            scored_with_reach AS (
                SELECT
                    cs.account_id,
                    cs.coverage_score,
                    COALESCE(tp.followers_count, yc.subscriber_count, 0) AS reach
                FROM creator_scores cs
                JOIN source_accounts sa ON sa.account_id = cs.account_id
                LEFT JOIN twitch_profiles_latest tp
                    ON tp.account_id = sa.account_id AND sa.platform = 'twitch'
                LEFT JOIN youtube_channels_latest yc
                    ON yc.account_id = sa.account_id AND sa.platform = 'youtube'
                WHERE COALESCE(tp.followers_count, yc.subscriber_count, 0) >= ?
                  AND cs.coverage_score > ?
            )
            SELECT account_id, coverage_score, reach
            FROM scored_with_reach
        """
        max_reach_param = max_reach if max_reach is not None else -1
        scored_with_reach_params: list[object] = [
            *game_tags_params,
            *similar_games_params,
            total_weight,
            max_possible_similar_bonus,
            min_coverage,
            max_possible_similar_bonus,
            min_coverage,
            min_reach,
            min_coverage,
        ]

        with_status_sql = f"""
            WITH game_tags AS (
                {game_tags_sql}
            ),
            similar_games AS (
                {similar_games_sql}
            ),
            scored_accounts AS (
                SELECT account_id
                FROM temp.match_scored_with_reach
            ),
            creator_relevant_games AS (
                SELECT DISTINCT cgp2.account_id, cgp2.igdb_game_id
                FROM scored_accounts sa2
                JOIN creator_games_played cgp2
                    ON cgp2.account_id = sa2.account_id
                JOIN igdb_game_tags igt2
                    ON igt2.igdb_id = cgp2.igdb_game_id
                JOIN game_tags gt2 ON gt2.tag_type = igt2.tag_type
                                   AND gt2.tag_id = igt2.tag_id
                WHERE cgp2.igdb_game_id IS NOT NULL
                UNION
                SELECT DISTINCT cgp2.account_id, cgp2.igdb_game_id
                FROM scored_accounts sa2
                JOIN creator_games_played cgp2
                    ON cgp2.account_id = sa2.account_id
                JOIN similar_games sg ON sg.igdb_id = cgp2.igdb_game_id
                WHERE cgp2.igdb_game_id IS NOT NULL
            ),
            creator_relevant_game_counts AS (
                SELECT
                    crg.account_id,
                    COUNT(*) AS relevant_game_count
                FROM creator_relevant_games crg
                GROUP BY crg.account_id
            )
            SELECT
                rf.account_id,
                rf.coverage_score,
                rf.reach,
                COALESCE(crgc.relevant_game_count, 0) AS relevant_game_count,
                COALESCE(ps.status, 'suggested') AS workflow_status
            FROM temp.match_scored_with_reach rf
            LEFT JOIN creator_relevant_game_counts crgc
                ON crgc.account_id = rf.account_id
            LEFT JOIN match_statuses ps
                ON ps.account_id = rf.account_id
               AND ps.customer_game_id = ?
            WHERE (? = -1 OR rf.reach <= ?)
              {extra_where_sql}
        """
        with_status_params: list[object] = [
            *game_tags_params,
            *similar_games_params,
            customer_game_id,
            max_reach_param,
            max_reach_param,
            *extra_params,
        ]

        with self._connection(conn) as db_conn:
            db_conn.execute(
                "DROP TABLE IF EXISTS temp.match_scored_with_reach"
            )
            db_conn.execute(
                "CREATE TEMP TABLE temp.match_scored_with_reach AS "
                + scored_with_reach_sql,
                scored_with_reach_params,
            )
            db_conn.execute(
                "CREATE INDEX temp.idx_match_scored_with_reach_account "
                "ON match_scored_with_reach(account_id)"
            )

            db_conn.execute("DROP TABLE IF EXISTS temp.match_with_status")
            db_conn.execute(
                "CREATE TEMP TABLE temp.match_with_status AS "
                + with_status_sql,
                with_status_params,
            )
            db_conn.execute(
                "CREATE INDEX temp.idx_match_with_status_account "
                "ON match_with_status(account_id)"
            )
            db_conn.execute(
                "CREATE INDEX temp.idx_match_with_status_status "
                "ON match_with_status(workflow_status)"
            )

            reach_filter_max = int(
                db_conn.execute(
                    "SELECT MAX(reach) AS reach_filter_max "
                    "FROM temp.match_scored_with_reach"
                ).fetchone()["reach_filter_max"]
                or 0
            )
            rows = db_conn.execute(
                """
                SELECT
                    account_id,
                    coverage_score,
                    reach,
                    relevant_game_count,
                    workflow_status
                FROM temp.match_with_status
                ORDER BY coverage_score DESC, reach DESC, account_id DESC
                """
            ).fetchall()
            db_conn.execute("DROP TABLE IF EXISTS temp.match_with_status")
            db_conn.execute(
                "DROP TABLE IF EXISTS temp.match_scored_with_reach"
            )

        if not rows:
            return [], reach_filter_max

        snapshot_rows: list[RankedSnapshotRow] = []
        for row in rows:
            snapshot_rows.append(
                RankedSnapshotRow(
                    account_id=str(row["account_id"]),
                    coverage_score=float(row["coverage_score"]),
                    reach=int(row["reach"]),
                    relevant_game_count=int(row["relevant_game_count"]),
                    workflow_status=self._workflow_status_from_row(
                        row["workflow_status"]
                    ),
                )
            )
        return snapshot_rows, reach_filter_max

    def count_relevant_games(
        self,
        account_ids: list[str],
        game_tags: Sequence[TagKey],
        similar_game_ids: Sequence[int] = (),
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, int]:
        """Count surfaced played games per creator for the match row."""
        if not account_ids or not game_tags:
            return {}

        game_tags_sql, game_tags_params = _game_tags_cte(game_tags)
        similar_games_sql, similar_games_params = _int_values_cte(
            similar_game_ids,
            column_name="igdb_id",
        )
        placeholders = ",".join("?" for _ in account_ids)

        sql = f"""
            WITH game_tags AS (
                {game_tags_sql}
            ),
            similar_games AS (
                {similar_games_sql}
            ),
            relevant_games AS (
                SELECT DISTINCT cgp.account_id, cgp.igdb_game_id
                FROM creator_games_played cgp
                JOIN igdb_game_tags igt ON igt.igdb_id = cgp.igdb_game_id
                JOIN game_tags gt ON gt.tag_type = igt.tag_type
                                  AND gt.tag_id = igt.tag_id
                WHERE cgp.igdb_game_id IS NOT NULL
                  AND cgp.account_id IN ({placeholders})
                UNION
                SELECT DISTINCT cgp.account_id, cgp.igdb_game_id
                FROM creator_games_played cgp
                JOIN similar_games sg ON sg.igdb_id = cgp.igdb_game_id
                WHERE cgp.igdb_game_id IS NOT NULL
                  AND cgp.account_id IN ({placeholders})
            )
            SELECT
                rg.account_id,
                COUNT(*) AS game_count
            FROM relevant_games rg
            GROUP BY rg.account_id
        """
        params: list[object] = [
            *game_tags_params,
            *similar_games_params,
            *account_ids,
            *account_ids,
        ]
        with self._connection(conn) as db_conn:
            rows = db_conn.execute(sql, params).fetchall()
        return {str(row["account_id"]): int(row["game_count"]) for row in rows}

    def get_relevant_games(
        self,
        account_ids: list[str],
        game_tags: Sequence[TagKey],
        similar_game_ids: Sequence[int] = (),
        *,
        per_account_limit: int = 10,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, list[RelevantGame]]:
        """Fetch surfaced game names + cover art for each creator."""
        if not account_ids or not game_tags or per_account_limit <= 0:
            return {}

        game_tags_sql, game_tags_params = _game_tags_cte(game_tags)
        similar_games_sql, similar_games_params = _int_values_cte(
            similar_game_ids,
            column_name="igdb_id",
        )
        placeholders = ",".join("?" for _ in account_ids)

        sql = f"""
            WITH game_tags AS (
                {game_tags_sql}
            ),
            similar_games AS (
                {similar_games_sql}
            ),
            candidate_games AS (
                SELECT
                    cgp.account_id,
                    ig.name,
                    ig.cover_url,
                    MAX(
                        CASE
                            WHEN sg.igdb_id IS NOT NULL THEN 1
                            ELSE 0
                        END
                    ) AS is_similar,
                    COUNT(
                        DISTINCT CASE
                            WHEN gt.tag_type IS NOT NULL
                            THEN igt.tag_type || ':' || CAST(igt.tag_id AS TEXT)
                        END
                    ) AS tag_overlap
                FROM creator_games_played cgp
                JOIN igdb_games ig ON ig.igdb_id = cgp.igdb_game_id
                LEFT JOIN igdb_game_tags igt ON igt.igdb_id = cgp.igdb_game_id
                LEFT JOIN game_tags gt ON gt.tag_type = igt.tag_type
                                      AND gt.tag_id = igt.tag_id
                LEFT JOIN similar_games sg ON sg.igdb_id = cgp.igdb_game_id
                WHERE cgp.igdb_game_id IS NOT NULL
                  AND cgp.account_id IN ({placeholders})
                GROUP BY cgp.account_id, cgp.igdb_game_id
                HAVING
                    MAX(
                        CASE
                            WHEN sg.igdb_id IS NOT NULL THEN 1
                            ELSE 0
                        END
                    ) = 1
                    OR COUNT(
                        DISTINCT CASE
                            WHEN gt.tag_type IS NOT NULL
                            THEN igt.tag_type || ':' || CAST(igt.tag_id AS TEXT)
                        END
                    ) > 0
            ),
            ranked_games AS (
                SELECT
                    account_id,
                    name,
                    cover_url,
                    is_similar,
                    ROW_NUMBER() OVER (
                        PARTITION BY account_id
                        ORDER BY is_similar DESC, tag_overlap DESC, name
                    ) AS rank_in_account
                FROM candidate_games
            )
            SELECT account_id, name, cover_url, is_similar
            FROM ranked_games
            WHERE rank_in_account <= ?
            ORDER BY account_id, rank_in_account
        """
        params: list[object] = [
            *game_tags_params,
            *similar_games_params,
            *account_ids,
            per_account_limit,
        ]
        with self._connection(conn) as db_conn:
            rows = db_conn.execute(sql, params).fetchall()

        result: dict[str, list[RelevantGame]] = {}
        for row in rows:
            aid = str(row["account_id"])
            cover = row["cover_url"]
            # Use thumbnail size for icons
            if cover and "/t_cover_big/" in cover:
                cover = cover.replace("/t_cover_big/", "/t_thumb/")
            result.setdefault(aid, []).append(
                RelevantGame(
                    name=row["name"],
                    cover_url=cover,
                    is_similar=bool(row["is_similar"]),
                )
            )
        return result

    def get_creator_profiles(
        self,
        account_ids: list[str],
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, CreatorRankingProfile]:
        """Fetch display-ready profile data for a set of account IDs."""
        if not account_ids:
            return {}

        placeholders = ",".join("?" for _ in account_ids)
        sql = f"""
            SELECT
                sa.account_id,
                sa.platform,
                COALESCE(sa.display_name_current, tp.display_name, yc.display_name) AS display_name,
                sa.handle_current AS handle,
                sa.canonical_url,
                COALESCE(tp.avatar_url, yc.avatar_url) AS avatar_url,
                cpf.summary_text,
                COALESCE(
                    tp.recent_avg_live_viewers,
                    tp.viewer_count,
                    tp.recent_avg_vod_views,
                    yc.recent_avg_views,
                    0
                ) AS recent_audience,
                COALESCE(tp.followers_count, yc.subscriber_count, 0) AS reach
            FROM source_accounts sa
            LEFT JOIN twitch_profiles_latest tp
                ON tp.account_id = sa.account_id AND sa.platform = 'twitch'
            LEFT JOIN youtube_channels_latest yc
                ON yc.account_id = sa.account_id AND sa.platform = 'youtube'
            LEFT JOIN creator_profile_facets_latest cpf
                ON cpf.account_id = sa.account_id
            WHERE sa.account_id IN ({placeholders})
        """
        contact_sql = f"""
            SELECT account_id, contact_type, contact_value
            FROM contact_points
            WHERE account_id IN ({placeholders})
              AND contact_type IN ('email', 'discord', 'social_link')
              AND is_public = 1
        """
        with self._connection(conn) as db_conn:
            rows = db_conn.execute(sql, account_ids).fetchall()
            contact_rows = db_conn.execute(contact_sql, account_ids).fetchall()

        emails_by_account: dict[str, list[str]] = {}
        discord_by_account: dict[str, list[str]] = {}
        socials_by_account: dict[str, list[str]] = {}
        for row in contact_rows:
            aid = str(row["account_id"])
            ctype = str(row["contact_type"])
            cval = str(row["contact_value"])
            if ctype == "email":
                emails_by_account.setdefault(aid, []).append(cval)
            elif ctype == "discord":
                discord_by_account.setdefault(aid, []).append(cval)
            elif ctype == "social_link":
                socials_by_account.setdefault(aid, []).append(cval)

        result: dict[str, CreatorRankingProfile] = {}
        for row in rows:
            account_id = str(row["account_id"])
            result[account_id] = CreatorRankingProfile(
                account_id=account_id,
                platform=str(row["platform"]),
                display_name=str(row["display_name"] or "Unknown"),
                handle=row["handle"],
                canonical_url=row["canonical_url"],
                avatar_url=row["avatar_url"],
                summary_text=row["summary_text"],
                recent_audience=int(row["recent_audience"] or 0),
                reach=int(row["reach"] or 0),
                contact_emails=tuple(emails_by_account.get(account_id, [])),
                contact_discord_urls=tuple(
                    discord_by_account.get(account_id, [])
                ),
                contact_social_links=tuple(
                    socials_by_account.get(account_id, [])
                ),
            )
        return result

    def get_match_workflow_states(
        self,
        *,
        customer_game_id: str,
        account_ids: Sequence[str],
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, MatchWorkflowState]:
        """Return saved workflow state for a set of matches."""
        if not account_ids:
            return {}

        placeholders = ",".join("?" for _ in account_ids)
        sql = f"""
            SELECT account_id, status, notes, updated_at
            FROM match_statuses
            WHERE customer_game_id = ?
              AND account_id IN ({placeholders})
        """
        params: list[object] = [customer_game_id, *account_ids]
        with self._connection(conn) as db_conn:
            rows = db_conn.execute(sql, params).fetchall()

        return {
            str(row["account_id"]): MatchWorkflowState(
                status=self._workflow_status_from_row(row["status"]),
                notes=str(row["notes"] or ""),
                updated_at=(
                    str(row["updated_at"]) if row["updated_at"] else None
                ),
            )
            for row in rows
        }

    def upsert_match_workflow_state(
        self,
        *,
        customer_game_id: str,
        account_id: str,
        status: MatchWorkflowStatus,
        notes: str,
    ) -> MatchWorkflowState:
        """Create or update sparse workflow state for one match."""
        clean_notes = notes.strip()
        with get_connection(self._db_path) as conn:
            if status == MATCH_DEFAULT_STATUS and not clean_notes:
                conn.execute(
                    """
                    DELETE FROM match_statuses
                    WHERE customer_game_id = ? AND account_id = ?
                    """,
                    (customer_game_id, account_id),
                )
                return MatchWorkflowState()

            conn.execute(
                """
                INSERT INTO match_statuses (
                    customer_game_id,
                    account_id,
                    status,
                    notes,
                    updated_at
                ) VALUES (?, ?, ?, ?, datetime('now'))
                ON CONFLICT(customer_game_id, account_id) DO UPDATE SET
                    status = excluded.status,
                    notes = excluded.notes,
                    updated_at = datetime('now')
                """,
                (customer_game_id, account_id, status, clean_notes),
            )
            row = conn.execute(
                """
                SELECT status, notes, updated_at
                FROM match_statuses
                WHERE customer_game_id = ? AND account_id = ?
                """,
                (customer_game_id, account_id),
            ).fetchone()

        if row is None:
            return MatchWorkflowState()
        return MatchWorkflowState(
            status=self._workflow_status_from_row(row["status"]),
            notes=str(row["notes"] or ""),
            updated_at=str(row["updated_at"]) if row["updated_at"] else None,
        )

    def count_workflow_statuses(
        self,
        *,
        customer_game_id: str,
        account_ids: Sequence[str],
    ) -> dict[MatchWorkflowStatus, int]:
        """Count saved statuses for the supplied match account ids."""
        counts = dict.fromkeys(MATCH_WORKFLOW_STATUS_ORDER, 0)
        if not account_ids:
            return counts

        states = self.get_match_workflow_states(
            customer_game_id=customer_game_id,
            account_ids=account_ids,
        )
        for account_id in account_ids:
            status = states.get(account_id, MatchWorkflowState()).status
            counts[status] += 1
        return counts

    @staticmethod
    def _workflow_status_from_row(value: object) -> MatchWorkflowStatus:
        """Normalize persisted workflow status values from SQLite rows."""
        raw = str(value)
        normalized = _LEGACY_WORKFLOW_STATUS_MAP.get(raw, raw)
        if normalized in MATCH_WORKFLOW_STATUS_ORDER:
            return normalized
        return MATCH_DEFAULT_STATUS
