"""Test fixtures for the reports query layer.

Seeds a minimal creator index in an isolated SQLite DB:
- 3 IGDB games with tags
- 3 Twitch creators with profiles and game plays
- Contact points for two of the creators
"""

from __future__ import annotations

import pytest

from app.database import initialize_database, get_connection
from app.reports.query import ReportQueryService


# ---------------------------------------------------------------------------
# IGDB game IDs and tag IDs used in fixtures
# ---------------------------------------------------------------------------
# Games
IGDB_SLAY_THE_SPIRE = 101
IGDB_HADES = 102
IGDB_STARDEW_VALLEY = 103

# Tag IDs (genre/theme numeric IDs as they appear in igdb_game_tags)
TAG_STRATEGY = 15
TAG_INDIE = 32
TAG_FANTASY = 31
TAG_COMEDY = 27

# Creator account IDs
ACCOUNT_A = "twitch:streamer_a"
ACCOUNT_B = "twitch:streamer_b"
ACCOUNT_C = "twitch:streamer_c"


@pytest.fixture
def db_path(tmp_path):
    """Isolated SQLite DB seeded with minimal creator index data."""
    path = str(tmp_path / "test.sqlite3")
    initialize_database(path)

    with get_connection(path) as conn:
        now = "2026-03-30T00:00:00"
        expires = "2099-01-01T00:00:00"

        # ── IGDB games ────────────────────────────────────────────────────
        conn.execute(
            """
            INSERT INTO igdb_games (igdb_id, name, slug, last_synced_at)
            VALUES (?, ?, ?, ?)
            """,
            (IGDB_SLAY_THE_SPIRE, "Slay the Spire", "slay-the-spire", now),
        )
        conn.execute(
            """
            INSERT INTO igdb_games (igdb_id, name, slug, last_synced_at)
            VALUES (?, ?, ?, ?)
            """,
            (IGDB_HADES, "Hades", "hades", now),
        )
        conn.execute(
            """
            INSERT INTO igdb_games (igdb_id, name, slug, last_synced_at)
            VALUES (?, ?, ?, ?)
            """,
            (IGDB_STARDEW_VALLEY, "Stardew Valley", "stardew-valley", now),
        )

        # ── IGDB game tags ────────────────────────────────────────────────
        # Slay the Spire: Strategy + Indie + Fantasy
        for tag_type, tag_name, tag_id in [
            ("genre", "Strategy", TAG_STRATEGY),
            ("genre", "Indie", TAG_INDIE),
            ("theme", "Fantasy", TAG_FANTASY),
        ]:
            conn.execute(
                "INSERT INTO igdb_game_tags (igdb_id, tag_type, tag_name, tag_id) VALUES (?, ?, ?, ?)",
                (IGDB_SLAY_THE_SPIRE, tag_type, tag_name, tag_id),
            )
        # Hades: Indie + Fantasy
        for tag_type, tag_name, tag_id in [
            ("genre", "Indie", TAG_INDIE),
            ("theme", "Fantasy", TAG_FANTASY),
        ]:
            conn.execute(
                "INSERT INTO igdb_game_tags (igdb_id, tag_type, tag_name, tag_id) VALUES (?, ?, ?, ?)",
                (IGDB_HADES, tag_type, tag_name, tag_id),
            )
        # Stardew Valley: Indie + Comedy
        for tag_type, tag_name, tag_id in [
            ("genre", "Indie", TAG_INDIE),
            ("theme", "Comedy", TAG_COMEDY),
        ]:
            conn.execute(
                "INSERT INTO igdb_game_tags (igdb_id, tag_type, tag_name, tag_id) VALUES (?, ?, ?, ?)",
                (IGDB_STARDEW_VALLEY, tag_type, tag_name, tag_id),
            )

        # ── Source accounts ───────────────────────────────────────────────
        for account_id, external_id, handle, display_name in [
            (ACCOUNT_A, "111", "streamer_a", "StreamerA"),
            (ACCOUNT_B, "222", "streamer_b", "StreamerB"),
            (ACCOUNT_C, "333", "streamer_c", "StreamerC"),
        ]:
            conn.execute(
                """
                INSERT INTO source_accounts
                    (account_id, platform, external_id, handle_current, display_name_current,
                     first_seen_at, last_seen_at, created_at, updated_at)
                VALUES (?, 'twitch', ?, ?, ?, ?, ?, ?, ?)
                """,
                (account_id, external_id, handle, display_name, now, now, now, now),
            )

        # ── Twitch profiles ───────────────────────────────────────────────
        # streamer_a: 5000 followers, recent activity
        conn.execute(
            """
            INSERT INTO twitch_profiles_latest
                (account_id, broadcaster_id, login, display_name, followers_count,
                 last_live_at, fetched_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (ACCOUNT_A, "111", "streamer_a", "StreamerA", 5000,
             "2026-03-25T12:00:00", now, expires),
        )
        # streamer_b: 800 followers, recent activity
        conn.execute(
            """
            INSERT INTO twitch_profiles_latest
                (account_id, broadcaster_id, login, display_name, followers_count,
                 last_live_at, fetched_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (ACCOUNT_B, "222", "streamer_b", "StreamerB", 800,
             "2026-03-20T18:00:00", now, expires),
        )
        # streamer_c: 20000 followers, old activity (more than 365d ago)
        conn.execute(
            """
            INSERT INTO twitch_profiles_latest
                (account_id, broadcaster_id, login, display_name, followers_count,
                 last_live_at, fetched_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (ACCOUNT_C, "333", "streamer_c", "StreamerC", 20000,
             "2024-01-01T00:00:00", now, expires),
        )

        # ── Game plays ────────────────────────────────────────────────────
        # streamer_a plays Slay the Spire + Hades
        for game_name_raw, game_name_key, igdb_id in [
            ("Slay the Spire", "slay the spire", IGDB_SLAY_THE_SPIRE),
            ("Hades", "hades", IGDB_HADES),
        ]:
            conn.execute(
                """
                INSERT INTO creator_games_played
                    (account_id, game_name_raw, game_name_key, platform,
                     first_seen_at, last_seen_at, igdb_game_id)
                VALUES (?, ?, ?, 'twitch', ?, ?, ?)
                """,
                (ACCOUNT_A, game_name_raw, game_name_key, now, now, igdb_id),
            )
        # streamer_b plays Slay the Spire
        conn.execute(
            """
            INSERT INTO creator_games_played
                (account_id, game_name_raw, game_name_key, platform,
                 first_seen_at, last_seen_at, igdb_game_id)
            VALUES (?, 'Slay the Spire', 'slay the spire', 'twitch', ?, ?, ?)
            """,
            (ACCOUNT_B, now, now, IGDB_SLAY_THE_SPIRE),
        )
        # streamer_c plays Stardew Valley
        conn.execute(
            """
            INSERT INTO creator_games_played
                (account_id, game_name_raw, game_name_key, platform,
                 first_seen_at, last_seen_at, igdb_game_id)
            VALUES (?, 'Stardew Valley', 'stardew valley', 'twitch', ?, ?, ?)
            """,
            (ACCOUNT_C, now, now, IGDB_STARDEW_VALLEY),
        )

        # ── Contact points ────────────────────────────────────────────────
        # streamer_a has email
        conn.execute(
            """
            INSERT INTO contact_points
                (contact_point_id, account_id, contact_type, contact_value,
                 source_kind, first_seen_at, last_seen_at, updated_at)
            VALUES (?, ?, 'email', 'streamer_a@example.com', 'profile', ?, ?, ?)
            """,
            ("cp_a_email", ACCOUNT_A, now, now, now),
        )
        # streamer_b has discord
        conn.execute(
            """
            INSERT INTO contact_points
                (contact_point_id, account_id, contact_type, contact_value,
                 source_kind, first_seen_at, last_seen_at, updated_at)
            VALUES (?, ?, 'discord', 'streamer_b#1234', 'profile', ?, ?, ?)
            """,
            ("cp_b_discord", ACCOUNT_B, now, now, now),
        )

    return path


@pytest.fixture
def seeded_db(db_path) -> str:
    """Alias for db_path — exposes the seeded SQLite path as a plain string."""
    return db_path


@pytest.fixture
def query_service(db_path) -> ReportQueryService:
    return ReportQueryService(db_path)
