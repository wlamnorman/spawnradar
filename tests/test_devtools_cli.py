"""Tests for the local SpawnRadar developer CLI."""

from pathlib import Path

import app.devtools.game_presets as game_presets
from app.auth.repository import UserRepository
from app.database import get_connection
from app.devtools.bootstrap import DEV_EMAIL
from app.devtools.cli import (
    main,
    run_customer_ids,
    run_forgetting_hour,
    run_get_profiles,
    run_igdb_fetch,
    run_inspect_twitch_igdb,
    run_snapshot_game_preset,
    run_strife_of_stars,
    run_twitch_search_categories,
    run_twitch_streams,
    run_wikiquests,
)
from app.devtools.game_presets import PRESET_FILE, load_game_presets
from app.games.repository import CustomerGameRepository
from app.games.service import CustomerGameService


def _copy_preset_file(tmp_path) -> Path:
    target = tmp_path / "game_presets.json"
    target.write_text(PRESET_FILE.read_text())
    return target


def test_run_wikiquests_creates_expected_game(db_path):
    result = run_wikiquests(db_path)

    user = UserRepository(db_path).get_by_email(DEV_EMAIL)
    assert user is not None
    game = CustomerGameRepository(db_path).list_by_user(user.user_id)[0]

    preset = load_game_presets()["wikiquests"]
    assert result.created is True
    assert game.name == "WikiQuests"
    assert game.description == preset["description"]
    assert game.website_url == "https://wikiquests.com"
    assert game.igdb_genre_ids == preset["igdb_genre_ids"]


def test_run_wikiquests_is_idempotent_and_updates_existing_game(db_path):
    first = run_wikiquests(db_path)
    second = run_wikiquests(db_path)

    user = UserRepository(db_path).get_by_email(DEV_EMAIL)
    assert user is not None
    games = CustomerGameRepository(db_path).list_by_user(user.user_id)

    assert first.created is True
    assert second.created is False
    assert len(games) == 1
    assert (
        games[0].description
        == load_game_presets()["wikiquests"]["description"]
    )


def test_run_strife_of_stars_creates_expected_game(db_path):
    result = run_strife_of_stars(db_path)

    user = UserRepository(db_path).get_by_email(DEV_EMAIL)
    assert user is not None
    game = next(
        game
        for game in CustomerGameRepository(db_path).list_by_user(user.user_id)
        if game.name == "Strife Of Stars"
    )

    preset = load_game_presets()["strife-of-stars"]
    assert result.created is True
    assert game.description == preset["description"]
    assert game.igdb_genre_ids == preset["igdb_genre_ids"]
    assert game.igdb_theme_ids == preset["igdb_theme_ids"]
    assert game.website_url is None


def test_run_strife_of_stars_is_idempotent(db_path):
    first = run_strife_of_stars(db_path)
    second = run_strife_of_stars(db_path)

    user = UserRepository(db_path).get_by_email(DEV_EMAIL)
    assert user is not None
    games = [
        game
        for game in CustomerGameRepository(db_path).list_by_user(user.user_id)
        if game.name == "Strife Of Stars"
    ]

    assert first.created is True
    assert second.created is False
    assert len(games) == 1


def test_run_snapshot_game_preset_updates_seed_payload_from_saved_game(
    db_path, tmp_path
):
    run_strife_of_stars(db_path)

    user = UserRepository(db_path).get_by_email(DEV_EMAIL)
    assert user is not None
    repo = CustomerGameRepository(db_path)
    service = CustomerGameService(repo)
    game = next(
        game
        for game in repo.list_by_user(user.user_id)
        if game.name == "Strife Of Stars"
    )
    service.update_game(
        game.customer_game_id,
        user.user_id,
        name="Strife Of Stars",
        summary="A tighter tactical fleet roguelite for PC strategy fans.",
        description="Updated description from the setup page.",
        website_url="https://strife.example",
        platforms=["pc"],
        igdb_genre_ids=[12, 24],  # Strategy, Tactical
        igdb_theme_ids=[18],  # Sci-fi
        igdb_keyword_ids=["roguelike", "grid-based"],
        similar_game_names=["Slay the Spire", "FTL: Faster Than Light"],
    )

    preset_path = _copy_preset_file(tmp_path)
    result = run_snapshot_game_preset(
        db_path, "strife-of-stars", preset_path=preset_path
    )

    presets = load_game_presets(preset_path)
    preset = presets["strife-of-stars"]
    assert result.message.startswith(
        "Snapshotted Strife Of Stars into preset 'strife-of-stars'"
    )
    assert (
        preset["summary"]
        == "A tighter tactical fleet roguelite for PC strategy fans."
    )
    assert preset["description"] == "Updated description from the setup page."
    assert preset["platforms"] == ["pc"]
    assert preset["igdb_genre_ids"] == [12, 24]
    assert preset["igdb_theme_ids"] == [18]
    assert preset["igdb_keyword_ids"] == ["roguelike", "grid-based"]
    assert preset["similar_game_names"] == [
        "Slay the Spire",
        "FTL: Faster Than Light",
    ]
    assert preset["website_url"] == "https://strife.example"


def test_run_strife_of_stars_round_trips_all_settings_after_snapshot(
    db_path, tmp_path, monkeypatch
):
    preset_path = _copy_preset_file(tmp_path)
    monkeypatch.setattr(game_presets, "PRESET_FILE", preset_path)

    run_strife_of_stars(db_path)

    user = UserRepository(db_path).get_by_email(DEV_EMAIL)
    assert user is not None
    repo = CustomerGameRepository(db_path)
    service = CustomerGameService(repo)
    game = next(
        game
        for game in repo.list_by_user(user.user_id)
        if game.name == "Strife Of Stars"
    )
    service.update_game(
        game.customer_game_id,
        user.user_id,
        name="Strife Of Stars",
        summary="A tighter tactical fleet roguelite for PC strategy fans.",
        description="Updated description from the setup page.",
        website_url="https://strife.example",
        platforms=["pc"],
        igdb_genre_ids=[12, 24],
        igdb_theme_ids=[18],
        igdb_keyword_ids=["roguelike", "grid-based"],
        similar_game_names=["Slay the Spire", "FTL: Faster Than Light"],
    )

    run_snapshot_game_preset(db_path, "strife-of-stars")
    repo.delete(game.customer_game_id)

    result = run_strife_of_stars(db_path)

    reseeded = next(
        game
        for game in repo.list_by_user(user.user_id)
        if game.name == "Strife Of Stars"
    )
    assert result.created is True
    assert (
        reseeded.summary
        == "A tighter tactical fleet roguelite for PC strategy fans."
    )
    assert reseeded.description == "Updated description from the setup page."
    assert reseeded.website_url == "https://strife.example"
    assert reseeded.platforms == ["pc"]
    assert reseeded.igdb_genre_ids == [12, 24]
    assert reseeded.igdb_theme_ids == [18]
    assert reseeded.igdb_keyword_ids == ["roguelike", "grid-based"]
    assert reseeded.similar_game_names == [
        "Slay the Spire",
        "FTL: Faster Than Light",
    ]


def test_run_forgetting_hour_round_trips_all_settings_after_snapshot(
    db_path, tmp_path, monkeypatch
):
    preset_path = _copy_preset_file(tmp_path)
    monkeypatch.setattr(game_presets, "PRESET_FILE", preset_path)

    run_forgetting_hour(db_path)

    user = UserRepository(db_path).get_by_email(DEV_EMAIL)
    assert user is not None
    repo = CustomerGameRepository(db_path)
    service = CustomerGameService(repo)
    game = next(
        game
        for game in repo.list_by_user(user.user_id)
        if game.name == "The Forgetting Hour"
    )
    service.update_game(
        game.customer_game_id,
        user.user_id,
        name="The Forgetting Hour",
        summary="A cozy time-loop mystery for handheld and PC players.",
        description="Updated forgetting hour description from the setup page.",
        website_url="https://forgetting.example",
        platforms=["switch", "pc"],
        igdb_genre_ids=[31, 13],
        igdb_theme_ids=[27],
        igdb_keyword_ids=["cozy"],
        similar_game_names=["Beacon Pines", "Night in the Woods"],
    )

    run_snapshot_game_preset(db_path, "forgetting-hour")
    repo.delete(game.customer_game_id)

    result = run_forgetting_hour(db_path)

    reseeded = next(
        game
        for game in repo.list_by_user(user.user_id)
        if game.name == "The Forgetting Hour"
    )
    assert result.created is True
    assert (
        reseeded.summary
        == "A cozy time-loop mystery for handheld and PC players."
    )
    assert (
        reseeded.description
        == "Updated forgetting hour description from the setup page."
    )
    assert reseeded.website_url == "https://forgetting.example"
    assert reseeded.platforms == ["switch", "pc"]
    assert reseeded.igdb_genre_ids == [31, 13]
    assert reseeded.igdb_theme_ids == [27]
    assert reseeded.igdb_keyword_ids == ["cozy"]
    assert reseeded.similar_game_names == [
        "Beacon Pines",
        "Night in the Woods",
    ]


def test_main_snapshot_game_preset_accepts_explicit_game_selector(
    db_path, tmp_path, monkeypatch
):
    run_strife_of_stars(db_path)
    preset_path = _copy_preset_file(tmp_path)
    monkeypatch.setattr(game_presets, "PRESET_FILE", preset_path)

    exit_code = main(
        [
            "--db-path",
            db_path,
            "snapshot-game-preset",
            "strife-of-stars",
            "--game",
            "Strife Of Stars",
        ]
    )

    assert exit_code == 0
    assert (
        load_game_presets(preset_path)["strife-of-stars"]["name"]
        == "Strife Of Stars"
    )


def test_main_wikiquests_returns_zero_and_writes_game(db_path):
    exit_code = main(["--db-path", db_path, "wikiquests"])

    user = UserRepository(db_path).get_by_email(DEV_EMAIL)
    assert user is not None
    assert exit_code == 0
    assert len(CustomerGameRepository(db_path).list_by_user(user.user_id)) == 1


def test_main_strife_of_stars_returns_zero_and_writes_game(db_path):
    exit_code = main(["--db-path", db_path, "strife-of-stars"])

    user = UserRepository(db_path).get_by_email(DEV_EMAIL)
    assert user is not None
    games = CustomerGameRepository(db_path).list_by_user(user.user_id)

    assert exit_code == 0
    assert any(game.name == "Strife Of Stars" for game in games)


def test_run_inspect_twitch_igdb_delegates_to_async_helper(
    db_path, monkeypatch
):
    import app.devtools.cli as cli_module

    async def fake_inspect(
        passed_db_path: str,
        *,
        igdb_game_id: int,
        max_pages: int,
        page_size: int,
        languages: tuple[str, ...],
        persist: bool,
        persist_limit: int,
    ):
        assert passed_db_path == db_path
        assert igdb_game_id == 40477
        assert max_pages == 2
        assert page_size == 10
        assert languages == ("en",)
        assert persist is True
        assert persist_limit == 7
        return cli_module.CommandResult(message="inspection ok")

    monkeypatch.setattr(
        cli_module, "_run_inspect_twitch_igdb_async", fake_inspect
    )

    result = run_inspect_twitch_igdb(
        db_path,
        igdb_game_id=40477,
        max_pages=2,
        page_size=10,
        languages=("en",),
        persist=True,
        persist_limit=7,
    )

    assert result.message == "inspection ok"


def test_run_twitch_streams_delegates_to_async_helper(monkeypatch):
    import app.devtools.cli as cli_module

    async def fake_run(
        *,
        twitch_game_id: str,
        page_size: int,
        languages: tuple[str, ...],
    ):
        assert twitch_game_id == "296831"
        assert page_size == 10
        assert languages == ("en",)
        return cli_module.CommandResult(message="streams ok")

    monkeypatch.setattr(cli_module, "_run_twitch_streams_async", fake_run)

    result = run_twitch_streams(
        twitch_game_id="296831",
        page_size=10,
        languages=("en",),
    )

    assert result.message == "streams ok"


def test_run_twitch_search_categories_delegates_to_async_helper(monkeypatch):
    import app.devtools.cli as cli_module

    async def fake_run(
        *,
        query: str,
        page_size: int,
    ):
        assert query == "Slay the Spire II"
        assert page_size == 10
        return cli_module.CommandResult(message="categories ok")

    monkeypatch.setattr(
        cli_module, "_run_twitch_search_categories_async", fake_run
    )

    result = run_twitch_search_categories(
        query="Slay the Spire II",
        page_size=10,
    )

    assert result.message == "categories ok"


def test_run_igdb_fetch_delegates_to_async_helper(db_path, monkeypatch):
    import app.devtools.cli as cli_module

    async def fake_run(
        passed_db_path: str,
        *,
        igdb_game_id: int,
    ):
        assert passed_db_path == db_path
        assert igdb_game_id == 296831
        return cli_module.CommandResult(message="igdb ok")

    monkeypatch.setattr(cli_module, "_run_igdb_fetch_async", fake_run)

    result = run_igdb_fetch(db_path, igdb_game_id=296831)

    assert result.message == "igdb ok"


def test_run_customer_ids_lists_active_games(db_path, registered_user):
    service = CustomerGameService(CustomerGameRepository(db_path))
    first = service.create_game(
        user_id=registered_user.user_id,
        name="Strife Of Stars",
        summary="Fleet tactics for strategy players.",
        description="Fleet tactics.",
        website_url=None,
        igdb_genre_ids=[12],
    )
    second = service.create_game(
        user_id=registered_user.user_id,
        name="WikiQuests",
        summary="Wiki racing for trivia players.",
        description="Wiki speedruns.",
        website_url="https://wikiquests.com",
        igdb_genre_ids=[9],
    )

    result = run_customer_ids(db_path)

    assert "Active customer games: 2" in result.message
    assert first.customer_game_id in result.message
    assert second.customer_game_id in result.message
    assert "strife-of-stars" in result.message
    assert "wikiquests" in result.message


def test_run_get_profiles_lists_top_profiles_for_game(
    db_path, registered_user
):
    service = CustomerGameService(CustomerGameRepository(db_path))
    game = service.create_game(
        user_id=registered_user.user_id,
        name="Strife Of Stars",
        summary="Fleet tactics for strategy players.",
        description="Fleet tactics.",
        website_url=None,
        igdb_genre_ids=[12, 15, 24],
        igdb_theme_ids=[18],
    )

    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO source_accounts (
                account_id, platform, external_id, handle_current,
                display_name_current, canonical_url, first_seen_at,
                last_seen_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'),
                      datetime('now'), datetime('now'))
            """,
            (
                "acct-tw-1",
                "twitch",
                "tw-1",
                "captainstar",
                "Captain Star",
                "https://twitch.tv/captainstar",
            ),
        )
        conn.execute(
            """
            INSERT INTO twitch_profiles_latest (
                account_id, broadcaster_id, login, display_name, description,
                followers_count, viewer_count, recent_avg_live_viewers,
                recent_median_live_viewers, recent_avg_vod_views,
                recent_median_vod_views, streams_last_30d, language,
                avatar_url, last_live_at, fetched_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'),
                      datetime('now'))
            """,
            (
                "acct-tw-1",
                "tw-1",
                "captainstar",
                "Captain Star",
                "Tactical fleet streams.",
                5000,
                120,
                250,
                200,
                300,
                280,
                12,
                "en",
                None,
                "2026-03-25T10:00:00+00:00",
            ),
        )
        conn.execute(
            """
            INSERT INTO creator_profile_facets_latest (
                account_id, platform, summary_text, genre_tags_json,
                interest_tags_json, language, last_activity_at, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                "acct-tw-1",
                "twitch",
                "Streams tactical strategy games.",
                '["Role-Playing (RPG)", "Tactical", "Strategy"]',
                '["Science Fiction"]',
                "en",
                "2026-03-25T10:00:00+00:00",
            ),
        )
        conn.execute(
            """
            INSERT INTO igdb_games (
                igdb_id, name, slug, summary, first_release_date,
                platform_ids_json, platform_names_json,
                last_synced_at
            ) VALUES (?, ?, ?, ?, ?, '[]', '[]', datetime('now'))
            """,
            (100, "Slay the Spire", "slay-the-spire", None, None),
        )
        conn.execute(
            """
            INSERT INTO igdb_game_tags (igdb_id, tag_type, tag_name, tag_id)
            VALUES
                (100, 'genre', 'Role-playing (RPG)', 12),
                (100, 'genre', 'Strategy', 15),
                (100, 'genre', 'Tactical', 24),
                (100, 'theme', 'Science Fiction', 18)
            """
        )
        conn.execute(
            """
            INSERT INTO creator_games_played (
                account_id, game_name_raw, game_name_key, platform,
                first_seen_at, last_seen_at, observation_count, igdb_game_id
            ) VALUES (?, ?, ?, ?, datetime('now'), datetime('now'), ?, ?)
            """,
            (
                "acct-tw-1",
                "Slay the Spire",
                "slay the spire",
                "twitch",
                3,
                100,
            ),
        )
        conn.execute(
            """
            INSERT INTO source_accounts (
                account_id, platform, external_id, handle_current,
                display_name_current, canonical_url, first_seen_at,
                last_seen_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'),
                      datetime('now'), datetime('now'))
            """,
            (
                "acct-yt-1",
                "youtube",
                "yt-1",
                "@admiralplays",
                "Admiral Plays",
                "https://youtube.com/@admiralplays",
            ),
        )
        conn.execute(
            """
            INSERT INTO youtube_channels_latest (
                account_id, channel_id, handle, display_name, description,
                subscriber_count, video_count, recent_avg_views,
                recent_median_views, uploads_last_30d, default_language,
                country, channel_created_at, avatar_url, uploads_playlist_id,
                last_upload_at, fetched_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                      datetime('now'), datetime('now'))
            """,
            (
                "acct-yt-1",
                "yt-1",
                "@admiralplays",
                "Admiral Plays",
                "Strategy breakdowns.",
                12000,
                220,
                600,
                550,
                8,
                "en",
                "US",
                "2020-01-01T00:00:00+00:00",
                None,
                "uu-yt-1",
                "2026-03-24T10:00:00+00:00",
            ),
        )
        conn.execute(
            """
            INSERT INTO creator_profile_facets_latest (
                account_id, platform, summary_text, genre_tags_json,
                interest_tags_json, language, last_activity_at, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                "acct-yt-1",
                "youtube",
                "Covers sci-fi strategy games.",
                '["Strategy"]',
                '["Science Fiction"]',
                "en",
                "2026-03-24T10:00:00+00:00",
            ),
        )
        conn.execute(
            """
            INSERT INTO igdb_games (
                igdb_id, name, slug, summary, first_release_date,
                platform_ids_json, platform_names_json,
                last_synced_at
            ) VALUES (?, ?, ?, ?, ?, '[]', '[]', datetime('now'))
            """,
            (200, "Age of Empires", "age-of-empires", None, None),
        )
        conn.execute(
            """
            INSERT INTO igdb_game_tags (igdb_id, tag_type, tag_name, tag_id)
            VALUES
                (200, 'genre', 'Role-playing (RPG)', 12),
                (200, 'theme', 'Comedy', 27)
            """
        )
        conn.execute(
            """
            INSERT INTO creator_games_played (
                account_id, game_name_raw, game_name_key, platform,
                first_seen_at, last_seen_at, observation_count, igdb_game_id
            ) VALUES (?, ?, ?, ?, datetime('now'), datetime('now'), ?, ?)
            """,
            (
                "acct-yt-1",
                "Age of Empires",
                "age of empires",
                "youtube",
                2,
                200,
            ),
        )

    result = run_get_profiles(db_path, "strife-of-stars")

    assert (
        f"Top matched creator profiles for Strife Of Stars ({game.customer_game_id})"
        in result.message
    )
    assert "coverage" in result.message
    assert "overlap_tags" in result.message
    assert "genre:12, genre:15, genre:24, theme:18" in result.message
    assert "Captain Star" in result.message
    assert "Admiral Plays" in result.message
    assert result.message.index("Captain Star") < result.message.index(
        "Admiral Plays"
    )


def test_main_get_profiles_returns_zero(db_path, registered_user):
    service = CustomerGameService(CustomerGameRepository(db_path))
    service.create_game(
        user_id=registered_user.user_id,
        name="Strife Of Stars",
        summary="Fleet tactics for strategy players.",
        description="Fleet tactics.",
        website_url=None,
        igdb_genre_ids=[12],
    )

    exit_code = main(
        ["--db-path", db_path, "ccs-for", "strife-of-stars", "--limit", "3"]
    )

    assert exit_code == 0


def test_run_get_profiles_accepts_fuzzy_game_name(db_path, registered_user):
    service = CustomerGameService(CustomerGameRepository(db_path))
    game = service.create_game(
        user_id=registered_user.user_id,
        name="Strife Of Stars",
        summary="Fleet tactics for strategy players.",
        description="Fleet tactics.",
        website_url=None,
        igdb_genre_ids=[12, 15, 24],
        igdb_theme_ids=[18],
    )
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO source_accounts (
                account_id, platform, external_id, handle_current,
                display_name_current, canonical_url, first_seen_at,
                last_seen_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'),
                      datetime('now'), datetime('now'))
            """,
            (
                "acct-fuzzy-1",
                "youtube",
                "yt-fuzzy-1",
                "@fuzzy",
                "Fuzzy Match",
                "https://youtube.com/@fuzzy",
            ),
        )
        conn.execute(
            """
            INSERT INTO youtube_channels_latest (
                account_id, channel_id, handle, display_name, description,
                subscriber_count, video_count, recent_avg_views,
                recent_median_views, uploads_last_30d, default_language,
                country, channel_created_at, avatar_url, uploads_playlist_id,
                last_upload_at, fetched_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                      datetime('now'), datetime('now'))
            """,
            (
                "acct-fuzzy-1",
                "yt-fuzzy-1",
                "@fuzzy",
                "Fuzzy Match",
                "Sci-fi tactics.",
                1000,
                10,
                200,
                180,
                2,
                "en",
                "US",
                "2020-01-01T00:00:00+00:00",
                None,
                "uu-fuzzy-1",
                "2026-03-24T10:00:00+00:00",
            ),
        )
        conn.execute(
            """
            INSERT INTO creator_profile_facets_latest (
                account_id, platform, summary_text, genre_tags_json,
                interest_tags_json, language, last_activity_at, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                "acct-fuzzy-1",
                "youtube",
                "Covers tactical sci-fi RPGs.",
                '["Role-Playing (RPG)", "Tactical"]',
                '["Science Fiction"]',
                "en",
                "2026-03-24T10:00:00+00:00",
            ),
        )
        conn.execute(
            """
            INSERT INTO igdb_games (
                igdb_id, name, slug, summary, first_release_date,
                platform_ids_json, platform_names_json,
                last_synced_at
            ) VALUES (?, ?, ?, ?, ?, '[]', '[]', datetime('now'))
            """,
            (300, "Into the Breach", "into-the-breach", None, None),
        )
        conn.execute(
            """
            INSERT INTO igdb_game_tags (igdb_id, tag_type, tag_name, tag_id)
            VALUES
                (300, 'genre', 'Role-playing (RPG)', 12),
                (300, 'genre', 'Tactical', 24),
                (300, 'theme', 'Science Fiction', 18)
            """
        )
        conn.execute(
            """
            INSERT INTO creator_games_played (
                account_id, game_name_raw, game_name_key, platform,
                first_seen_at, last_seen_at, observation_count, igdb_game_id
            ) VALUES (?, ?, ?, ?, datetime('now'), datetime('now'), ?, ?)
            """,
            (
                "acct-fuzzy-1",
                "Into the Breach",
                "into the breach",
                "youtube",
                2,
                300,
            ),
        )

    result = run_get_profiles(db_path, "strife stars")

    assert f"({game.customer_game_id})" in result.message
    assert "Fuzzy Match" in result.message
