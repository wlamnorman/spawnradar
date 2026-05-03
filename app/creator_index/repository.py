"""Raw-SQL repository for the background creator index."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime, timedelta

from app.creator_index.adapters.base import (
    ContactPointSeed,
    ContentSampleSeed,
    SourceAccountSeed,
    TwitchProfileSeed,
    YouTubeChannelSeed,
)
from app.creator_index.adapters.common import mean_int, median_int
from app.creator_index.facets import CreatorProfileFacetSeed
from app.creator_index.models import (
    ContactPoint,
    CrawlCursor,
    CrawlJob,
    CrawlSeed,
    CreatorGamePlayed,
    SourceAccount,
    TwitchCategoryRecord,
)
from app.database import get_connection
from app.json_codec import dump_json, load_json_object


class CreatorIndexRepository:
    """Persistence layer for indexed platform account data."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def upsert_source_account(
        self, platform: str, seed: SourceAccountSeed
    ) -> SourceAccount:
        now = datetime.now(UTC).isoformat()
        with get_connection(self._db_path) as conn:
            existing = conn.execute(
                """
                SELECT account_id, first_seen_at, created_at
                FROM source_accounts
                WHERE platform = ? AND external_id = ?
                """,
                (platform, seed.external_id),
            ).fetchone()

            if existing is None:
                account_id = str(uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO source_accounts (
                        account_id, platform, external_id, handle_current,
                        display_name_current, canonical_url, account_type,
                        status, first_seen_at, last_seen_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        account_id,
                        platform,
                        seed.external_id,
                        seed.handle_current,
                        seed.display_name_current,
                        seed.canonical_url,
                        seed.account_type,
                        seed.status,
                        now,
                        now,
                        now,
                        now,
                    ),
                )
            else:
                account_id = existing["account_id"]
                conn.execute(
                    """
                    UPDATE source_accounts
                    SET handle_current = ?, display_name_current = ?,
                        canonical_url = ?, account_type = ?, status = ?,
                        last_seen_at = ?, updated_at = ?
                    WHERE account_id = ?
                    """,
                    (
                        seed.handle_current,
                        seed.display_name_current,
                        seed.canonical_url,
                        seed.account_type,
                        seed.status,
                        now,
                        now,
                        account_id,
                    ),
                )

            row = conn.execute(
                "SELECT * FROM source_accounts WHERE account_id = ?",
                (account_id,),
            ).fetchone()
        return _row_to_source_account(row)

    def upsert_twitch_profile_latest(
        self, account_id: str, seed: TwitchProfileSeed
    ) -> None:
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO twitch_profiles_latest (
                    account_id, broadcaster_id, login, display_name, description,
                    followers_count, viewer_count,
                    recent_avg_live_viewers, recent_median_live_viewers,
                    recent_avg_vod_views, recent_median_vod_views,
                    streams_last_30d,
                    language, avatar_url,
                    last_live_at, fetched_at, expires_at,
                    clip_cursor, clips_exhausted
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id) DO UPDATE SET
                    broadcaster_id = excluded.broadcaster_id,
                    login = excluded.login,
                    display_name = excluded.display_name,
                    description = excluded.description,
                    followers_count = excluded.followers_count,
                    viewer_count = excluded.viewer_count,
                    recent_avg_live_viewers = excluded.recent_avg_live_viewers,
                    recent_median_live_viewers = excluded.recent_median_live_viewers,
                    recent_avg_vod_views = excluded.recent_avg_vod_views,
                    recent_median_vod_views = excluded.recent_median_vod_views,
                    streams_last_30d = excluded.streams_last_30d,
                    language = excluded.language,
                    avatar_url = excluded.avatar_url,
                    last_live_at = excluded.last_live_at,
                    fetched_at = excluded.fetched_at,
                    expires_at = excluded.expires_at,
                    clip_cursor = excluded.clip_cursor,
                    clips_exhausted = excluded.clips_exhausted
                """,
                (
                    account_id,
                    seed.broadcaster_id,
                    seed.login,
                    seed.display_name,
                    seed.description,
                    seed.followers_count,
                    seed.viewer_count,
                    seed.recent_avg_live_viewers,
                    seed.recent_median_live_viewers,
                    seed.recent_avg_vod_views,
                    seed.recent_median_vod_views,
                    seed.streams_last_30d,
                    seed.language,
                    seed.avatar_url,
                    seed.last_live_at,
                    seed.fetched_at,
                    seed.expires_at,
                    seed.clip_cursor,
                    int(seed.clips_exhausted),
                ),
            )

    def update_twitch_live_viewer_stats(
        self,
        account_id: str,
        *,
        recent_avg_live_viewers: int | None,
        recent_median_live_viewers: int | None,
    ) -> None:
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                UPDATE twitch_profiles_latest
                SET recent_avg_live_viewers = ?,
                    recent_median_live_viewers = ?
                WHERE account_id = ?
                """,
                (
                    recent_avg_live_viewers,
                    recent_median_live_viewers,
                    account_id,
                ),
            )

    def upsert_youtube_channel_latest(
        self, account_id: str, seed: YouTubeChannelSeed
    ) -> None:
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO youtube_channels_latest (
                    account_id, channel_id, handle, display_name, description,
                    subscriber_count, video_count,
                    recent_avg_views, recent_median_views, uploads_last_30d,
                    default_language, country, channel_created_at,
                    avatar_url,
                    uploads_playlist_id, last_upload_at,
                    fetched_at, expires_at, raw_payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id) DO UPDATE SET
                    channel_id = excluded.channel_id,
                    handle = excluded.handle,
                    display_name = excluded.display_name,
                    description = excluded.description,
                    subscriber_count = excluded.subscriber_count,
                    video_count = excluded.video_count,
                    recent_avg_views = excluded.recent_avg_views,
                    recent_median_views = excluded.recent_median_views,
                    uploads_last_30d = excluded.uploads_last_30d,
                    default_language = excluded.default_language,
                    country = excluded.country,
                    channel_created_at = excluded.channel_created_at,
                    avatar_url = excluded.avatar_url,
                    uploads_playlist_id = excluded.uploads_playlist_id,
                    last_upload_at = excluded.last_upload_at,
                    fetched_at = excluded.fetched_at,
                    expires_at = excluded.expires_at,
                    raw_payload_json = excluded.raw_payload_json
                """,
                (
                    account_id,
                    seed.channel_id,
                    seed.handle,
                    seed.display_name,
                    seed.description,
                    seed.subscriber_count,
                    seed.video_count,
                    seed.recent_avg_views,
                    seed.recent_median_views,
                    seed.uploads_last_30d,
                    seed.default_language,
                    seed.country,
                    seed.channel_created_at,
                    seed.avatar_url,
                    seed.uploads_playlist_id,
                    seed.last_upload_at,
                    seed.fetched_at,
                    seed.expires_at,
                    dump_json(seed.raw_payload_json or {}),
                ),
            )

    def replace_content_samples(
        self,
        account_id: str,
        platform: str,
        seeds: tuple[ContentSampleSeed, ...],
    ) -> int:
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                DELETE FROM content_samples_latest
                WHERE account_id = ? AND platform = ?
                """,
                (account_id, platform),
            )
            for seed in seeds:
                conn.execute(
                    """
                    INSERT INTO content_samples_latest (
                        sample_id, account_id, platform, external_content_id,
                        content_type, title_or_text, body_text, url,
                        thumbnail_url, published_at, engagement_count, language,
                        position_rank, fetched_at, expires_at, raw_payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        account_id,
                        platform,
                        seed.external_content_id,
                        seed.content_type,
                        seed.title_or_text,
                        seed.body_text,
                        seed.url,
                        seed.thumbnail_url,
                        seed.published_at,
                        seed.engagement_count,
                        seed.language,
                        seed.position_rank,
                        seed.fetched_at,
                        seed.expires_at,
                        dump_json(seed.raw_payload_json or {}),
                    ),
                )
        return len(seeds)

    def upsert_contact_points(
        self, account_id: str, seeds: tuple[ContactPointSeed, ...]
    ) -> int:
        if not seeds:
            return 0
        now = datetime.now(UTC).isoformat()
        with get_connection(self._db_path) as conn:
            for seed in seeds:
                existing = conn.execute(
                    """
                    SELECT contact_point_id, first_seen_at
                    FROM contact_points
                    WHERE account_id = ? AND contact_type = ? AND contact_value = ?
                    """,
                    (account_id, seed.contact_type, seed.contact_value),
                ).fetchone()
                if existing is None:
                    conn.execute(
                        """
                        INSERT INTO contact_points (
                            contact_point_id, account_id, contact_type,
                            contact_value, source_kind, source_url,
                            is_public, first_seen_at, last_seen_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(uuid.uuid4()),
                            account_id,
                            seed.contact_type,
                            seed.contact_value,
                            seed.source_kind,
                            seed.source_url,
                            1 if seed.is_public else 0,
                            now,
                            now,
                            now,
                        ),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE contact_points
                        SET source_kind = ?, source_url = ?,
                            is_public = ?, last_seen_at = ?, updated_at = ?
                        WHERE contact_point_id = ?
                        """,
                        (
                            seed.source_kind,
                            seed.source_url,
                            1 if seed.is_public else 0,
                            now,
                            now,
                            existing["contact_point_id"],
                        ),
                    )
        return len(seeds)

    def upsert_creator_profile_facets_latest(
        self,
        account_id: str,
        platform: str,
        seed: CreatorProfileFacetSeed,
    ) -> None:
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO creator_profile_facets_latest (
                    account_id, platform, summary_text, genre_tags_json,
                    interest_tags_json, language, last_activity_at, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id) DO UPDATE SET
                    platform = excluded.platform,
                    summary_text = excluded.summary_text,
                    genre_tags_json = excluded.genre_tags_json,
                    interest_tags_json = excluded.interest_tags_json,
                    language = excluded.language,
                    last_activity_at = excluded.last_activity_at,
                    fetched_at = excluded.fetched_at
                """,
                (
                    account_id,
                    platform,
                    seed.summary_text,
                    dump_json(list(seed.genre_tags)),
                    dump_json(list(seed.interest_tags)),
                    seed.language,
                    seed.last_activity_at,
                    datetime.now(UTC).isoformat(),
                ),
            )

    def upsert_creator_games_played(
        self,
        account_id: str,
        platform: str,
        game_names: tuple[str, ...],
    ) -> int:
        """Record game names observed for a creator; returns count of names processed."""
        if not game_names:
            return 0
        now = datetime.now(UTC).isoformat()
        with get_connection(self._db_path) as conn:
            for game_name in game_names:
                game_name_key = game_name.strip().lower()
                if not game_name_key:
                    continue
                conn.execute(
                    """
                    INSERT INTO creator_games_played (
                        account_id, game_name_raw, game_name_key, platform,
                        first_seen_at, last_seen_at, observation_count
                    ) VALUES (?, ?, ?, ?, ?, ?, 1)
                    ON CONFLICT(account_id, game_name_key) DO UPDATE SET
                        last_seen_at = excluded.last_seen_at,
                        observation_count = observation_count + 1
                    """,
                    (
                        account_id,
                        game_name.strip(),
                        game_name_key,
                        platform,
                        now,
                        now,
                    ),
                )
        return len(game_names)

    def insert_metric_sample(
        self,
        *,
        account_id: str,
        platform: str,
        metric_key: str,
        metric_value: float,
        observed_at: str,
    ) -> None:
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO account_metric_samples (
                    sample_id, account_id, platform, metric_key, metric_value,
                    observed_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    account_id,
                    platform,
                    metric_key,
                    metric_value,
                    observed_at,
                ),
            )

    def recent_metric_stats(
        self,
        *,
        account_id: str,
        platform: str,
        metric_key: str,
        days: int = 30,
    ) -> tuple[int | None, int | None]:
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT metric_value
                FROM account_metric_samples
                WHERE account_id = ? AND platform = ? AND metric_key = ?
                  AND observed_at >= ?
                ORDER BY observed_at DESC
                """,
                (account_id, platform, metric_key, cutoff),
            ).fetchall()
        values = [int(round(float(row["metric_value"]))) for row in rows]
        return mean_int(values), median_int(values)

    def start_crawl_job(
        self, platform: str, job_type: str, seed_key: str, args_json: dict
    ) -> str:
        job_id = str(uuid.uuid4())
        started_at = datetime.now(UTC).isoformat()
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO crawl_jobs (
                    job_id, platform, job_type, seed_key, status, attempt,
                    started_at, finished_at, error_message, args_json
                ) VALUES (?, ?, ?, ?, 'running', 1, ?, NULL, NULL, ?)
                """,
                (
                    job_id,
                    platform,
                    job_type,
                    seed_key,
                    started_at,
                    dump_json(args_json),
                ),
            )
        return job_id

    def finish_crawl_job(
        self, job_id: str, status: str, error_message: str | None = None
    ) -> None:
        finished_at = datetime.now(UTC).isoformat()
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                UPDATE crawl_jobs
                SET status = ?, finished_at = ?, error_message = ?
                WHERE job_id = ?
                """,
                (status, finished_at, error_message, job_id),
            )

    def load_cursors(self, platform: str, cursor_scope: str) -> dict[str, str]:
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT cursor_key, cursor_value
                FROM crawl_cursors
                WHERE platform = ? AND cursor_scope = ?
                """,
                (platform, cursor_scope),
            ).fetchall()
        return {
            str(row["cursor_key"]): str(row["cursor_value"])
            for row in rows
            if row["cursor_key"] and row["cursor_value"]
        }

    def save_cursors(
        self, platform: str, cursor_scope: str, cursors: dict[str, str]
    ) -> None:
        now = datetime.now(UTC).isoformat()
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                DELETE FROM crawl_cursors
                WHERE platform = ? AND cursor_scope = ?
                """,
                (platform, cursor_scope),
            )
            for cursor_key, cursor_value in sorted(cursors.items()):
                if not cursor_value:
                    continue
                conn.execute(
                    """
                    INSERT INTO crawl_cursors (
                        platform, cursor_scope, cursor_key, cursor_value, updated_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (platform, cursor_scope, cursor_key, cursor_value, now),
                )

    def list_active_crawl_seeds(
        self, platforms: tuple[str, ...]
    ) -> list[CrawlSeed]:
        if not platforms:
            return []
        placeholders = ",".join("?" * len(platforms))
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM crawl_seeds
                WHERE status = 'active' AND platform IN ({placeholders})
                ORDER BY platform ASC, weight DESC, query_text ASC
                """,
                list(platforms),
            ).fetchall()
        return [_row_to_crawl_seed(row) for row in rows]

    def mark_crawl_seed_synced(self, seed_id: str) -> None:
        now = datetime.now(UTC).isoformat()
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                UPDATE crawl_seeds
                SET last_synced_at = ?, updated_at = ?
                WHERE seed_id = ?
                """,
                (now, now, seed_id),
            )

    def get_fresh_external_ids(self, platform: str) -> set[str]:
        """Return external IDs whose enrichment data has not yet expired."""
        now = datetime.now(UTC).isoformat()
        table = (
            "youtube_channels_latest"
            if platform == "youtube"
            else "twitch_profiles_latest"
        )
        id_col = "channel_id" if platform == "youtube" else "broadcaster_id"
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                f"""
                SELECT p.{id_col}
                FROM {table} p
                WHERE p.expires_at > ?
                """,
                (now,),
            ).fetchall()
        return {row[0] for row in rows}

    def list_source_accounts(self) -> list[SourceAccount]:
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM source_accounts ORDER BY created_at ASC"
            ).fetchall()
        return [_row_to_source_account(row) for row in rows]

    def list_contact_points(self) -> list[ContactPoint]:
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM contact_points ORDER BY first_seen_at ASC"
            ).fetchall()
        return [_row_to_contact_point(row) for row in rows]

    def list_crawl_jobs(self) -> list[CrawlJob]:
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM crawl_jobs ORDER BY started_at ASC"
            ).fetchall()
        return [_row_to_crawl_job(row) for row in rows]

    def list_crawl_cursors(self) -> list[CrawlCursor]:
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM crawl_cursors ORDER BY updated_at ASC"
            ).fetchall()
        return [_row_to_crawl_cursor(row) for row in rows]

    def list_crawl_seeds(self) -> list[CrawlSeed]:
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM crawl_seeds ORDER BY platform, weight DESC, query_text"
            ).fetchall()
        return [_row_to_crawl_seed(row) for row in rows]

    def list_creator_games_played(
        self, account_id: str
    ) -> list[CreatorGamePlayed]:
        """Return all game-play observations for one account, most-observed first."""
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT * FROM creator_games_played
                WHERE account_id = ?
                ORDER BY observation_count DESC, game_name_key ASC
                """,
                (account_id,),
            ).fetchall()
        return [_row_to_creator_game_played(row) for row in rows]

    def tag_games_played_with_igdb_id(
        self, external_ids: list[str], *, igdb_game_id: int
    ) -> None:
        """Link creator_games_played rows to an IGDB game ID."""
        if not external_ids:
            return
        with get_connection(self._db_path) as conn:
            conn.executemany(
                """UPDATE creator_games_played SET igdb_game_id = ?
                   WHERE account_id IN (
                       SELECT account_id FROM source_accounts
                       WHERE external_id = ?
                   ) AND igdb_game_id IS NULL""",
                [(igdb_game_id, ext_id) for ext_id in external_ids],
            )

    def tag_account_games_played_with_igdb_ids(
        self,
        account_id: str,
        *,
        game_name_to_igdb_id: dict[str, int],
    ) -> None:
        """Link one account's observed game names to IGDB games."""
        if not game_name_to_igdb_id:
            return
        with get_connection(self._db_path) as conn:
            conn.executemany(
                """
                UPDATE creator_games_played
                SET igdb_game_id = ?
                WHERE account_id = ?
                  AND game_name_key = ?
                  AND (igdb_game_id IS NULL OR igdb_game_id = ?)
                """,
                [
                    (
                        igdb_game_id,
                        account_id,
                        game_name.strip().lower(),
                        igdb_game_id,
                    )
                    for game_name, igdb_game_id in game_name_to_igdb_id.items()
                    if game_name.strip()
                ],
            )

    def get_twitch_category_for_igdb_game(
        self, igdb_game_id: int
    ) -> TwitchCategoryRecord | None:
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                """
                SELECT * FROM twitch_categories
                WHERE igdb_game_id = ?
                """,
                (igdb_game_id,),
            ).fetchone()
        if row is None:
            return None
        return _row_to_twitch_category_record(row)

    def upsert_twitch_category(
        self,
        *,
        twitch_category_id: str,
        name: str,
        box_art_url: str | None,
        igdb_game_id: int | None,
    ) -> TwitchCategoryRecord:
        now = datetime.now(UTC).isoformat()
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO twitch_categories (
                    twitch_category_id,
                    name,
                    box_art_url,
                    igdb_game_id,
                    last_synced_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(twitch_category_id) DO UPDATE SET
                    name = excluded.name,
                    box_art_url = excluded.box_art_url,
                    igdb_game_id = excluded.igdb_game_id,
                    last_synced_at = excluded.last_synced_at
                """,
                (
                    twitch_category_id,
                    name,
                    box_art_url,
                    igdb_game_id,
                    now,
                ),
            )
            row = conn.execute(
                """
                SELECT * FROM twitch_categories
                WHERE twitch_category_id = ?
                """,
                (twitch_category_id,),
            ).fetchone()
        if row is None:
            raise ValueError("Failed to read back saved Twitch category.")
        return _row_to_twitch_category_record(row)


def _row_to_source_account(row: sqlite3.Row) -> SourceAccount:
    return SourceAccount(
        account_id=row["account_id"],
        platform=row["platform"],
        external_id=row["external_id"],
        handle_current=row["handle_current"],
        display_name_current=row["display_name_current"],
        canonical_url=row["canonical_url"],
        account_type=row["account_type"],
        status=row["status"],
        first_seen_at=row["first_seen_at"],
        last_seen_at=row["last_seen_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_contact_point(row: sqlite3.Row) -> ContactPoint:
    return ContactPoint(
        contact_point_id=row["contact_point_id"],
        account_id=row["account_id"],
        contact_type=row["contact_type"],
        contact_value=row["contact_value"],
        source_kind=row["source_kind"],
        source_url=row["source_url"],
        is_public=bool(row["is_public"]),
        first_seen_at=row["first_seen_at"],
        last_seen_at=row["last_seen_at"],
        updated_at=row["updated_at"],
    )


def _row_to_crawl_job(row: sqlite3.Row) -> CrawlJob:
    return CrawlJob(
        job_id=row["job_id"],
        platform=row["platform"],
        job_type=row["job_type"],
        seed_key=row["seed_key"],
        status=row["status"],
        attempt=row["attempt"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        error_message=row["error_message"],
        args_json=load_json_object(row["args_json"]),
    )


def _row_to_crawl_cursor(row: sqlite3.Row) -> CrawlCursor:
    return CrawlCursor(
        platform=row["platform"],
        cursor_scope=row["cursor_scope"],
        cursor_key=row["cursor_key"],
        cursor_value=row["cursor_value"],
        updated_at=row["updated_at"],
    )


def _row_to_twitch_category_record(
    row: sqlite3.Row,
) -> TwitchCategoryRecord:
    return TwitchCategoryRecord(
        twitch_category_id=row["twitch_category_id"],
        name=row["name"],
        box_art_url=row["box_art_url"],
        igdb_game_id=row["igdb_game_id"],
        last_synced_at=row["last_synced_at"],
    )


def _row_to_crawl_seed(row: sqlite3.Row) -> CrawlSeed:
    return CrawlSeed(
        seed_id=row["seed_id"],
        platform=row["platform"],
        query_text=row["query_text"],
        seed_kind=row["seed_kind"],
        status=row["status"],
        weight=float(row["weight"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        last_synced_at=row["last_synced_at"],
    )


def _row_to_creator_game_played(row: sqlite3.Row) -> CreatorGamePlayed:
    return CreatorGamePlayed(
        account_id=row["account_id"],
        game_name_raw=row["game_name_raw"],
        game_name_key=row["game_name_key"],
        platform=row["platform"],
        first_seen_at=row["first_seen_at"],
        last_seen_at=row["last_seen_at"],
        observation_count=int(row["observation_count"]),
        igdb_game_id=row["igdb_game_id"],
    )
