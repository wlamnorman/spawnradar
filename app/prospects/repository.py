"""Read-only repository for prospect ranking queries.

This module owns its own SQL and does not depend on
app.creator_index.repository, so it can be developed independently.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.creator_index.matching import TagCounts, TagKey
from app.database import get_connection
from app.prospects.models import CreatorRankingProfile, RelevantGame


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
        """Build per-creator tag counts from their resolved game plays.

        Only returns creators who have at least one tag overlapping
        with the supplied customer game tags. Each distinct IGDB game
        contributes its tags once (repeated sessions don't inflate).
        """
        if not game_tags:
            return {}

        game_tags_sql, game_tags_params = _game_tags_cte(game_tags)

        sql = f"""
            WITH creator_tag_counts AS (
                SELECT
                    cgp.account_id,
                    igt.tag_type,
                    igt.tag_id,
                    COUNT(DISTINCT cgp.igdb_game_id) AS tag_count
                FROM creator_games_played cgp
                JOIN igdb_game_tags igt ON igt.igdb_id = cgp.igdb_game_id
                WHERE cgp.igdb_game_id IS NOT NULL
                GROUP BY cgp.account_id, igt.tag_type, igt.tag_id
            ),
            game_tags AS (
                {game_tags_sql}
            ),
            eligible_creators AS (
                SELECT ctc.account_id, COUNT(*) AS overlap_count
                FROM creator_tag_counts ctc
                JOIN game_tags gt ON gt.tag_type = ctc.tag_type
                                  AND gt.tag_id = ctc.tag_id
                GROUP BY ctc.account_id
                ORDER BY overlap_count DESC
                LIMIT ?
            )
            SELECT ctc.account_id, ctc.tag_type, ctc.tag_id, ctc.tag_count
            FROM creator_tag_counts ctc
            JOIN eligible_creators ec ON ec.account_id = ctc.account_id
            ORDER BY ctc.account_id
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
            JOIN game_tags gt ON gt.tag_type = igt.tag_type AND gt.tag_id = igt.tag_id
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
    ) -> dict[str, list[RelevantGame]]:
        """Fetch relevant game names + cover art for each creator."""
        if not account_ids or not game_tags:
            return {}

        game_tags_sql, game_tags_params = _game_tags_cte(game_tags)
        placeholders = ",".join("?" for _ in account_ids)

        sql = f"""
            WITH game_tags AS (
                {game_tags_sql}
            )
            SELECT cgp.account_id, ig.name, ig.cover_url,
                   COUNT(DISTINCT gt.tag_id) AS tag_overlap
            FROM creator_games_played cgp
            JOIN igdb_game_tags igt ON igt.igdb_id = cgp.igdb_game_id
            JOIN game_tags gt ON gt.tag_type = igt.tag_type AND gt.tag_id = igt.tag_id
            JOIN igdb_games ig ON ig.igdb_id = cgp.igdb_game_id
            WHERE cgp.igdb_game_id IS NOT NULL
              AND cgp.account_id IN ({placeholders})
            GROUP BY cgp.account_id, cgp.igdb_game_id
            ORDER BY cgp.account_id, tag_overlap DESC, ig.name
        """
        params: list[object] = [*game_tags_params, *account_ids]
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
