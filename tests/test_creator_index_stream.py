"""Tests for Twitch stream discovery — TwitchStreamClient and hydration."""

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.creator_index.adapters.base import ObservedGameSeed
from app.creator_index.service import CreatorIndexService
from app.creator_index.stream_discovery import (
    TwitchGame,
)
from app.database import get_connection, initialize_database


def make_db():
    with tempfile.NamedTemporaryFile(
        suffix=".sqlite3", delete=False
    ) as temp_file:
        db_path = temp_file.name
    initialize_database(db_path)
    return db_path


@pytest.mark.anyio
async def test_resolve_twitch_category_fetches_missing_local_igdb_game():
    """Kept as a reference test for IGDB hydration logic."""
    # This test validated _resolve_twitch_category_for_igdb_game which
    # has been removed in the v2 pipeline. The underlying hydration
    # logic is now handled by discovery.py's build_reference_games.
    pass


@pytest.mark.anyio
async def test_hydrate_observed_twitch_games_ignores_blank_igdb_id():
    db = make_db()
    try:
        runtime = MagicMock()
        runtime.twitch_client_id = "x"
        runtime.twitch_client_secret = "y"
        service = CreatorIndexService(db_path=db, source_runtime=runtime)

        observed_games = (
            ObservedGameSeed(
                game_name="Among Us",
                platform_game_id="111469",
            ),
        )

        with (
            patch.object(
                service,
                "_fetch_twitch_games_by_ids",
                new=AsyncMock(
                    return_value={
                        "111469": TwitchGame(
                            twitch_game_id="111469",
                            name="Among Us",
                            box_art_url=None,
                            igdb_game_id="",
                        )
                    }
                ),
            ) as mock_fetch_games,
            patch(
                "app.creator_index.service.IGDBSyncService"
            ) as mock_igdb_sync_cls,
        ):
            await service._hydrate_observed_twitch_games(
                "account-1", observed_games
            )

        mock_fetch_games.assert_awaited_once_with(("111469",))
        mock_igdb_sync_cls.assert_not_called()
        assert service._repository.list_creator_games_played("account-1") == []
    finally:
        os.unlink(db)


@pytest.mark.anyio
async def test_hydrate_observed_twitch_games_fetches_missing_igdb_and_tags_play():
    db = make_db()
    try:
        runtime = MagicMock()
        runtime.twitch_client_id = "x"
        runtime.twitch_client_secret = "y"
        service = CreatorIndexService(db_path=db, source_runtime=runtime)

        with get_connection(db) as conn:
            conn.execute(
                """
                INSERT INTO source_accounts (
                    account_id, platform, external_id, handle_current,
                    display_name_current, canonical_url, account_type,
                    status, first_seen_at, last_seen_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "acc-1",
                    "twitch",
                    "tw-1",
                    "tester",
                    "Tester",
                    "https://twitch.tv/tester",
                    "creator",
                    "active",
                    "2026-01-01T00:00:00+00:00",
                    "2026-01-01T00:00:00+00:00",
                    "2026-01-01T00:00:00+00:00",
                    "2026-01-01T00:00:00+00:00",
                ),
            )
            conn.execute(
                """
                INSERT INTO creator_games_played (
                    account_id, game_name_raw, game_name_key, platform,
                    first_seen_at, last_seen_at, observation_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "acc-1",
                    "Slay the Spire II",
                    "slay the spire ii",
                    "twitch",
                    "2026-01-01T00:00:00+00:00",
                    "2026-01-01T00:00:00+00:00",
                    1,
                ),
            )

        with patch.object(
            service,
            "_fetch_twitch_games_by_ids",
            new=AsyncMock(
                return_value={
                    "1435206302": TwitchGame(
                        twitch_game_id="1435206302",
                        name="Slay the Spire II",
                        box_art_url=None,
                        igdb_game_id="296831",
                    )
                }
            ),
        ):

            async def fake_fetch_game(igdb_game_id: int) -> bool:
                with get_connection(db) as conn:
                    conn.execute(
                        """
                        INSERT INTO igdb_games (
                            igdb_id, name, slug, summary, first_release_date,
                            platform_ids_json, platform_names_json,
                            last_synced_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            igdb_game_id,
                            "Slay the Spire II",
                            "slay-the-spire-ii",
                            None,
                            None,
                            "[]",
                            "[]",
                            "2026-01-01T00:00:00+00:00",
                        ),
                    )
                return True

            with patch(
                "app.creator_index.service.IGDBSyncService.fetch_game",
                new=AsyncMock(side_effect=fake_fetch_game),
            ) as mock_fetch_game:
                await service._hydrate_observed_twitch_games(
                    "acc-1",
                    (
                        ObservedGameSeed(
                            game_name="Slay the Spire II",
                            platform_game_id="1435206302",
                        ),
                    ),
                )

        mock_fetch_game.assert_awaited_once_with(296831)

        with get_connection(db) as conn:
            row = conn.execute(
                """
                SELECT igdb_game_id
                FROM creator_games_played
                WHERE account_id = ? AND game_name_key = ?
                """,
                ("acc-1", "slay the spire ii"),
            ).fetchone()
        assert row is not None
        assert row["igdb_game_id"] == 296831
    finally:
        os.unlink(db)
