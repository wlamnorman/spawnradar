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
    CreatorRankingFilterProfile,
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
        limit: int = 200,
    ) -> dict[str, TagCounts]:
        """Return per-creator counts for the customer game's target tags only."""
        if not game_tags:
            return {}

        game_tags_sql, game_tags_params = _game_tags_cte(game_tags)

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
                ORDER BY overlap_count DESC
                LIMIT ?
            )
            SELECT cttc.account_id, cttc.tag_type, cttc.tag_id, cttc.tag_count
            FROM creator_target_tag_counts cttc
            JOIN eligible_creators ec ON ec.account_id = cttc.account_id
            ORDER BY cttc.account_id
        """

        params: list[object] = [*game_tags_params, limit]
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

    def count_creators_with_overlap(
        self,
        *,
        game_tags: Sequence[TagKey],
        min_reach: int = 0,
    ) -> int:
        """Count creators with at least one overlapping game tag."""
        if not game_tags:
            return 0

        game_tags_sql, game_tags_params = _game_tags_cte(game_tags)
        sql = f"""
            WITH game_tags AS (
                {game_tags_sql}
            ),
            overlapping_accounts AS (
                SELECT DISTINCT cgp.account_id
                FROM creator_games_played cgp
                JOIN igdb_game_tags igt ON igt.igdb_id = cgp.igdb_game_id
                JOIN game_tags gt ON gt.tag_type = igt.tag_type
                                  AND gt.tag_id = igt.tag_id
                WHERE cgp.igdb_game_id IS NOT NULL
            )
            SELECT COUNT(*) AS creator_count
            FROM (
                SELECT
                    oa.account_id,
                    COALESCE(tp.followers_count, yc.subscriber_count, 0) AS reach
                FROM overlapping_accounts oa
                JOIN source_accounts sa ON sa.account_id = oa.account_id
                LEFT JOIN twitch_profiles_latest tp
                    ON tp.account_id = sa.account_id AND sa.platform = 'twitch'
                LEFT JOIN youtube_channels_latest yc
                    ON yc.account_id = sa.account_id AND sa.platform = 'youtube'
            ) ranked_accounts
            WHERE ranked_accounts.reach >= ?
        """
        with get_connection(self._db_path) as conn:
            row = conn.execute(sql, [*game_tags_params, min_reach]).fetchone()
        return int(row["creator_count"] or 0) if row is not None else 0

    def max_reach_with_overlap(
        self,
        *,
        game_tags: Sequence[TagKey],
        min_reach: int = 0,
    ) -> int:
        """Return the maximum reach among creators overlapping the game tags."""
        if not game_tags:
            return 0

        game_tags_sql, game_tags_params = _game_tags_cte(game_tags)
        sql = f"""
            WITH game_tags AS (
                {game_tags_sql}
            ),
            overlapping_accounts AS (
                SELECT DISTINCT cgp.account_id
                FROM creator_games_played cgp
                JOIN igdb_game_tags igt ON igt.igdb_id = cgp.igdb_game_id
                JOIN game_tags gt ON gt.tag_type = igt.tag_type
                                  AND gt.tag_id = igt.tag_id
                WHERE cgp.igdb_game_id IS NOT NULL
            )
            SELECT MAX(
                COALESCE(tp.followers_count, yc.subscriber_count, 0)
            ) AS max_reach
            FROM overlapping_accounts oa
            JOIN source_accounts sa ON sa.account_id = oa.account_id
            LEFT JOIN twitch_profiles_latest tp
                ON tp.account_id = sa.account_id AND sa.platform = 'twitch'
            LEFT JOIN youtube_channels_latest yc
                ON yc.account_id = sa.account_id AND sa.platform = 'youtube'
            WHERE COALESCE(tp.followers_count, yc.subscriber_count, 0) >= ?
        """
        with get_connection(self._db_path) as conn:
            row = conn.execute(sql, [*game_tags_params, min_reach]).fetchone()
        return int(row["max_reach"] or 0) if row is not None else 0

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

    def max_relevant_games_with_overlap(
        self,
        *,
        game_tags: Sequence[TagKey],
        min_reach: int = 0,
    ) -> int:
        """Return the maximum relevant-game count among overlapping creators."""
        if not game_tags:
            return 0

        game_tags_sql, game_tags_params = _game_tags_cte(game_tags)
        sql = f"""
            WITH game_tags AS (
                {game_tags_sql}
            ),
            creator_relevant_games AS (
                SELECT
                    cgp.account_id,
                    COUNT(DISTINCT cgp.igdb_game_id) AS game_count
                FROM creator_games_played cgp
                JOIN igdb_game_tags igt ON igt.igdb_id = cgp.igdb_game_id
                JOIN game_tags gt ON gt.tag_type = igt.tag_type
                                  AND gt.tag_id = igt.tag_id
                WHERE cgp.igdb_game_id IS NOT NULL
                GROUP BY cgp.account_id
            )
            SELECT MAX(crg.game_count) AS max_game_count
            FROM creator_relevant_games crg
            JOIN source_accounts sa ON sa.account_id = crg.account_id
            LEFT JOIN twitch_profiles_latest tp
                ON tp.account_id = sa.account_id AND sa.platform = 'twitch'
            LEFT JOIN youtube_channels_latest yc
                ON yc.account_id = sa.account_id AND sa.platform = 'youtube'
            WHERE COALESCE(tp.followers_count, yc.subscriber_count, 0) >= ?
        """
        with get_connection(self._db_path) as conn:
            row = conn.execute(sql, [*game_tags_params, min_reach]).fetchone()
        return int(row["max_game_count"] or 0) if row is not None else 0

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

    def get_creator_filter_profiles(
        self,
        account_ids: list[str],
        *,
        include_contacts: bool = False,
    ) -> dict[str, CreatorRankingFilterProfile]:
        """Fetch lightweight profile data for ranking/filtering."""
        if not account_ids:
            return {}

        placeholders = ",".join("?" for _ in account_ids)
        sql = f"""
            SELECT
                sa.account_id,
                sa.platform,
                sa.canonical_url,
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
            WHERE sa.account_id IN ({placeholders})
        """

        emails_by_account: dict[str, list[str]] = {}
        discord_by_account: dict[str, list[str]] = {}
        socials_by_account: dict[str, list[str]] = {}
        with get_connection(self._db_path) as conn:
            rows = conn.execute(sql, account_ids).fetchall()
            if include_contacts:
                contact_sql = f"""
                    SELECT account_id, contact_type, contact_value
                    FROM contact_points
                    WHERE account_id IN ({placeholders})
                      AND contact_type IN ('email', 'discord', 'social_link')
                      AND is_public = 1
                """
                contact_rows = conn.execute(
                    contact_sql, account_ids
                ).fetchall()
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

        result: dict[str, CreatorRankingFilterProfile] = {}
        for row in rows:
            account_id = str(row["account_id"])
            result[account_id] = CreatorRankingFilterProfile(
                account_id=account_id,
                platform=str(row["platform"]),
                canonical_url=row["canonical_url"],
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
