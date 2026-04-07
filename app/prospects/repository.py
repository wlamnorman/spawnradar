"""Read-only repository for prospect ranking queries.

This module owns its own SQL and does not depend on
app.creator_index.repository, so it can be developed independently.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.creator_index.matching import TagCounts, TagKey
from app.database import get_connection
from app.prospects.models import (
    PROSPECT_DEFAULT_STATUS,
    PROSPECT_WORKFLOW_STATUS_ORDER,
    CreatorRankingProfile,
    ProspectWorkflowState,
    ProspectWorkflowStatus,
    RelevantGame,
)


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


class ProspectRepository:
    """Query layer for ranked prospect data."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def query_creator_tag_counts(
        self,
        *,
        game_tags: Sequence[TagKey],
        account_ids: list[str] | None = None,
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

        with get_connection(self._db_path) as conn:
            rows = conn.execute(sql, params).fetchall()

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
        min_coverage: float = 0.65,
        min_reach: int = 0,
        max_reach: int | None = None,
        min_relevant_games: int = 0,
        max_relevant_games: int | None = None,
        contact_methods: tuple[str, ...] = (),
        status_filter: str = "all",
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[
        list[tuple[str, float, int]],  # (account_id, coverage_score, reach)
        int,  # total_count
        int,  # reach_filter_max
        int,  # games_filter_max
        dict[ProspectWorkflowStatus, int],  # status_counts
    ]:
        """Score, filter, sort, and paginate prospects entirely in SQL.

        Returns ``(page_rows, total_count, reach_filter_max, games_filter_max,
        status_counts)``.
        """
        if not game_tags or total_weight <= 0:
            return (
                [],
                0,
                0,
                0,
                dict.fromkeys(PROSPECT_WORKFLOW_STATUS_ORDER, 0),
            )

        game_tags_sql, game_tags_params = _game_tags_cte(game_tags)

        # --- Dynamic filter clauses ------------------------------------
        extra_joins: list[str] = []
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

        # Status filter clause
        if status_filter == "all":
            status_where = "AND workflow_status != 'not_pursuing'"
        elif status_filter in PROSPECT_WORKFLOW_STATUS_ORDER:
            status_where = "AND workflow_status = ?"
        else:
            status_where = ""

        # De-duplicate extra_joins
        extra_joins_sql = "\n                ".join(
            dict.fromkeys(extra_joins).keys()
        )
        extra_where_sql = "\n                  ".join(extra_where)

        scored_with_reach_sql = f"""
            WITH game_tags AS (
                {game_tags_sql}
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
            creator_scores AS (
                SELECT
                    cte.account_id,
                    SUM(
                        CASE WHEN cte.tag_type = 'genre' THEN 3.0 ELSE 1.0 END
                        * cte.evidence
                    ) / ? AS coverage_score,
                    COUNT(*) AS overlap_count
                FROM creator_tag_evidence cte
                GROUP BY cte.account_id
                HAVING coverage_score > ? AND overlap_count >= 2
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
            )
            SELECT account_id, coverage_score, reach
            FROM scored_with_reach
        """
        max_reach_param = max_reach if max_reach is not None else -1
        scored_with_reach_params: list[object] = [
            *game_tags_params,
            total_weight,
            min_coverage,
            min_reach,
        ]

        with_status_sql = f"""
            WITH game_tags AS (
                {game_tags_sql}
            ),
            creator_relevant_game_counts AS (
                SELECT
                    cgp2.account_id,
                    COUNT(DISTINCT cgp2.igdb_game_id) AS relevant_game_count
                FROM creator_games_played cgp2
                JOIN igdb_game_tags igt2 ON igt2.igdb_id = cgp2.igdb_game_id
                JOIN game_tags gt2 ON gt2.tag_type = igt2.tag_type
                                   AND gt2.tag_id = igt2.tag_id
                WHERE cgp2.igdb_game_id IS NOT NULL
                GROUP BY cgp2.account_id
            )
            SELECT
                rf.account_id,
                rf.coverage_score,
                rf.reach,
                COALESCE(crgc.relevant_game_count, 0) AS relevant_game_count,
                COALESCE(ps.status, 'new') AS workflow_status
            FROM temp.prospect_scored_with_reach rf
            {extra_joins_sql}
            LEFT JOIN creator_relevant_game_counts crgc
                ON crgc.account_id = rf.account_id
            LEFT JOIN prospect_statuses ps
                ON ps.account_id = rf.account_id
               AND ps.customer_game_id = ?
            WHERE (? = -1 OR rf.reach <= ?)
              {extra_where_sql}
        """
        with_status_params: list[object] = [
            *game_tags_params,
            customer_game_id,
            max_reach_param,
            max_reach_param,
            *extra_params,
        ]

        filter_clauses: list[str] = []
        bound_params: list[object] = []
        if status_where:
            filter_clauses.append(status_where.removeprefix("AND ").strip())
            if (
                status_filter not in ("all", "")
                and status_filter in PROSPECT_WORKFLOW_STATUS_ORDER
            ):
                bound_params.append(status_filter)
        if min_relevant_games > 0:
            filter_clauses.append("relevant_game_count >= ?")
            bound_params.append(min_relevant_games)
        if max_relevant_games is not None:
            filter_clauses.append("relevant_game_count <= ?")
            bound_params.append(max_relevant_games)
        page_where = (
            "WHERE " + " AND ".join(filter_clauses) if filter_clauses else ""
        )
        status_only_where = (
            "WHERE " + status_where.removeprefix("AND ").strip()
            if status_where
            else ""
        )
        page_sql = f"""
            SELECT account_id, coverage_score, reach
            FROM temp.prospect_with_status
            {page_where}
            ORDER BY coverage_score DESC, reach DESC, account_id DESC
            LIMIT ? OFFSET ?
        """
        count_sql = f"""
            SELECT COUNT(*) AS total_count
            FROM temp.prospect_with_status
            {page_where}
        """
        games_max_sql = f"""
            SELECT MAX(relevant_game_count) AS games_filter_max
            FROM temp.prospect_with_status
            {status_only_where}
        """
        page_params: list[object] = [*bound_params]
        count_params = [*bound_params]
        page_params.extend([limit, offset])
        games_max_params = []
        if (
            status_filter not in ("all", "")
            and status_filter in PROSPECT_WORKFLOW_STATUS_ORDER
        ):
            games_max_params.append(status_filter)

        with get_connection(self._db_path) as conn:
            conn.execute("DROP TABLE IF EXISTS temp.prospect_scored_with_reach")
            conn.execute(
                "CREATE TEMP TABLE temp.prospect_scored_with_reach AS "
                + scored_with_reach_sql,
                scored_with_reach_params,
            )
            conn.execute(
                "CREATE INDEX temp.idx_prospect_scored_with_reach_account "
                "ON prospect_scored_with_reach(account_id)"
            )

            conn.execute("DROP TABLE IF EXISTS temp.prospect_with_status")
            conn.execute(
                "CREATE TEMP TABLE temp.prospect_with_status AS "
                + with_status_sql,
                with_status_params,
            )
            conn.execute(
                "CREATE INDEX temp.idx_prospect_with_status_account "
                "ON prospect_with_status(account_id)"
            )
            conn.execute(
                "CREATE INDEX temp.idx_prospect_with_status_status "
                "ON prospect_with_status(workflow_status)"
            )

            reach_filter_max = int(
                conn.execute(
                    "SELECT MAX(reach) AS reach_filter_max "
                    "FROM temp.prospect_scored_with_reach"
                ).fetchone()["reach_filter_max"]
                or 0
            )
            status_rows = conn.execute(
                """
                SELECT workflow_status, COUNT(*) AS cnt
                FROM temp.prospect_with_status
                GROUP BY workflow_status
                """
            ).fetchall()
            total_count = int(
                conn.execute(count_sql, count_params).fetchone()["total_count"]
            )
            games_filter_max = int(
                conn.execute(games_max_sql, games_max_params).fetchone()[
                    "games_filter_max"
                ]
                or 0
            )
            rows = conn.execute(page_sql, page_params).fetchall()
            conn.execute("DROP TABLE IF EXISTS temp.prospect_with_status")
            conn.execute("DROP TABLE IF EXISTS temp.prospect_scored_with_reach")

        status_counts: dict[ProspectWorkflowStatus, int] = dict.fromkeys(
            PROSPECT_WORKFLOW_STATUS_ORDER, 0
        )
        for sr in status_rows:
            raw_status = str(sr["workflow_status"])
            if raw_status in PROSPECT_WORKFLOW_STATUS_ORDER:
                status_counts[raw_status] += int(sr["cnt"])
            else:
                status_counts["new"] += int(sr["cnt"])

        if not rows:
            return (
                [],
                total_count,
                reach_filter_max,
                games_filter_max,
                status_counts,
            )

        page_rows = [
            (str(r["account_id"]), float(r["coverage_score"]), int(r["reach"]))
            for r in rows
        ]
        return (
            page_rows,
            total_count,
            reach_filter_max,
            games_filter_max,
            status_counts,
        )

    def count_relevant_games(
        self,
        account_ids: list[str],
        game_tags: Sequence[TagKey],
    ) -> dict[str, int]:
        """Count distinct IGDB games per creator that carry an overlapping tag."""
        if not account_ids or not game_tags:
            return {}

        game_tags_sql, game_tags_params = _game_tags_cte(game_tags)
        placeholders = ",".join("?" for _ in account_ids)

        sql = f"""
            WITH game_tags AS (
                {game_tags_sql}
            )
            SELECT cgp.account_id, COUNT(DISTINCT cgp.igdb_game_id) AS game_count
            FROM creator_games_played cgp
            JOIN igdb_game_tags igt ON igt.igdb_id = cgp.igdb_game_id
            JOIN game_tags gt ON gt.tag_type = igt.tag_type
                              AND gt.tag_id = igt.tag_id
            WHERE cgp.igdb_game_id IS NOT NULL
              AND cgp.account_id IN ({placeholders})
            GROUP BY cgp.account_id
        """
        params: list[object] = [*game_tags_params, *account_ids]
        with get_connection(self._db_path) as conn:
            rows = conn.execute(sql, params).fetchall()
        return {str(row["account_id"]): int(row["game_count"]) for row in rows}

    def get_relevant_games(
        self,
        account_ids: list[str],
        game_tags: Sequence[TagKey],
        *,
        per_account_limit: int = 10,
    ) -> dict[str, list[RelevantGame]]:
        """Fetch relevant game names + cover art for each creator."""
        if not account_ids or not game_tags or per_account_limit <= 0:
            return {}

        game_tags_sql, game_tags_params = _game_tags_cte(game_tags)
        placeholders = ",".join("?" for _ in account_ids)

        sql = f"""
            WITH game_tags AS (
                {game_tags_sql}
            ),
            ranked_games AS (
                SELECT
                    cgp.account_id,
                    ig.name,
                    ig.cover_url,
                    COUNT(DISTINCT igt.tag_type || ':' || CAST(igt.tag_id AS TEXT)) AS tag_overlap,
                    ROW_NUMBER() OVER (
                        PARTITION BY cgp.account_id
                        ORDER BY COUNT(DISTINCT igt.tag_type || ':' || CAST(igt.tag_id AS TEXT)) DESC, ig.name
                    ) AS rank_in_account
                FROM creator_games_played cgp
                JOIN igdb_game_tags igt ON igt.igdb_id = cgp.igdb_game_id
                JOIN game_tags gt ON gt.tag_type = igt.tag_type
                                  AND gt.tag_id = igt.tag_id
                JOIN igdb_games ig ON ig.igdb_id = cgp.igdb_game_id
                WHERE cgp.igdb_game_id IS NOT NULL
                  AND cgp.account_id IN ({placeholders})
                GROUP BY cgp.account_id, cgp.igdb_game_id
            )
            SELECT account_id, name, cover_url
            FROM ranked_games
            WHERE rank_in_account <= ?
            ORDER BY account_id, rank_in_account
        """
        params: list[object] = [
            *game_tags_params,
            *account_ids,
            per_account_limit,
        ]
        with get_connection(self._db_path) as conn:
            rows = conn.execute(sql, params).fetchall()

        result: dict[str, list[RelevantGame]] = {}
        for row in rows:
            aid = str(row["account_id"])
            cover = row["cover_url"]
            # Use thumbnail size for icons
            if cover and "/t_cover_big/" in cover:
                cover = cover.replace("/t_cover_big/", "/t_thumb/")
            result.setdefault(aid, []).append(
                RelevantGame(name=row["name"], cover_url=cover)
            )
        return result

    def get_creator_profiles(
        self, account_ids: list[str]
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
        with get_connection(self._db_path) as conn:
            rows = conn.execute(sql, account_ids).fetchall()
            contact_rows = conn.execute(contact_sql, account_ids).fetchall()

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

    def get_prospect_workflow_states(
        self,
        *,
        customer_game_id: str,
        account_ids: Sequence[str],
    ) -> dict[str, ProspectWorkflowState]:
        """Return saved workflow state for a set of prospects."""
        if not account_ids:
            return {}

        placeholders = ",".join("?" for _ in account_ids)
        sql = f"""
            SELECT account_id, status, notes, updated_at
            FROM prospect_statuses
            WHERE customer_game_id = ?
              AND account_id IN ({placeholders})
        """
        params: list[object] = [customer_game_id, *account_ids]
        with get_connection(self._db_path) as conn:
            rows = conn.execute(sql, params).fetchall()

        return {
            str(row["account_id"]): ProspectWorkflowState(
                status=self._workflow_status_from_row(row["status"]),
                notes=str(row["notes"] or ""),
                updated_at=(
                    str(row["updated_at"]) if row["updated_at"] else None
                ),
            )
            for row in rows
        }

    def upsert_prospect_workflow_state(
        self,
        *,
        customer_game_id: str,
        account_id: str,
        status: ProspectWorkflowStatus,
        notes: str,
    ) -> ProspectWorkflowState:
        """Create or update sparse workflow state for one prospect."""
        clean_notes = notes.strip()
        with get_connection(self._db_path) as conn:
            if status == PROSPECT_DEFAULT_STATUS and not clean_notes:
                conn.execute(
                    """
                    DELETE FROM prospect_statuses
                    WHERE customer_game_id = ? AND account_id = ?
                    """,
                    (customer_game_id, account_id),
                )
                return ProspectWorkflowState()

            conn.execute(
                """
                INSERT INTO prospect_statuses (
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
                FROM prospect_statuses
                WHERE customer_game_id = ? AND account_id = ?
                """,
                (customer_game_id, account_id),
            ).fetchone()

        if row is None:
            return ProspectWorkflowState()
        return ProspectWorkflowState(
            status=self._workflow_status_from_row(row["status"]),
            notes=str(row["notes"] or ""),
            updated_at=str(row["updated_at"]) if row["updated_at"] else None,
        )

    def count_workflow_statuses(
        self,
        *,
        customer_game_id: str,
        account_ids: Sequence[str],
    ) -> dict[ProspectWorkflowStatus, int]:
        """Count saved statuses for the supplied prospect account ids."""
        counts = dict.fromkeys(PROSPECT_WORKFLOW_STATUS_ORDER, 0)
        if not account_ids:
            return counts

        states = self.get_prospect_workflow_states(
            customer_game_id=customer_game_id,
            account_ids=account_ids,
        )
        for account_id in account_ids:
            status = states.get(account_id, ProspectWorkflowState()).status
            counts[status] += 1
        return counts

    @staticmethod
    def _workflow_status_from_row(value: object) -> ProspectWorkflowStatus:
        """Normalize persisted workflow status values from SQLite rows."""
        raw = str(value)
        if raw in PROSPECT_WORKFLOW_STATUS_ORDER:
            return raw
        return PROSPECT_DEFAULT_STATUS
