"""Tests for the local SpawnRadar developer CLI."""

from pathlib import Path

import pytest

import app.devtools.game_presets as game_presets
from app.auth.repository import SessionRepository, UserRepository
from app.devtools.bootstrap import DEV_EMAIL
from app.devtools.cli import (
    main,
    run_forgetting_hour,
    run_mint_session,
    run_snapshot_game_preset,
    run_strife_of_stars,
    run_volgarr_the_viking_ii,
)
from app.devtools.game_presets import PRESET_FILE, load_game_presets
from app.games.repository import CustomerGameRepository
from app.games.service import CustomerGameService


def _copy_preset_file(tmp_path) -> Path:
    target = tmp_path / "game_presets.json"
    target.write_text(PRESET_FILE.read_text())
    return target


def test_run_strife_creates_expected_game(db_path):
    result = run_strife_of_stars(db_path)

    user = UserRepository(db_path).get_by_email(DEV_EMAIL)
    assert user is not None
    game = CustomerGameRepository(db_path).list_by_user(user.user_id)[0]

    preset = load_game_presets()["strife-of-stars"]
    assert result.created is True
    assert game.name == "Strife Of Stars"
    assert game.description == preset["description"]
    assert game.igdb_genre_ids == preset["igdb_genre_ids"]


def test_run_strife_is_idempotent_and_updates_existing_game(db_path):
    first = run_strife_of_stars(db_path)
    second = run_strife_of_stars(db_path)

    user = UserRepository(db_path).get_by_email(DEV_EMAIL)
    assert user is not None
    games = CustomerGameRepository(db_path).list_by_user(user.user_id)

    assert first.created is True
    assert second.created is False
    assert len(games) == 1
    assert (
        games[0].description
        == load_game_presets()["strife-of-stars"]["description"]
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


def test_run_volgarr_the_viking_ii_creates_expected_game(db_path):
    result = run_volgarr_the_viking_ii(db_path)

    user = UserRepository(db_path).get_by_email(DEV_EMAIL)
    assert user is not None
    game = next(
        game
        for game in CustomerGameRepository(db_path).list_by_user(user.user_id)
        if game.name == "Volgarr the Viking II"
    )

    preset = load_game_presets()["volgarr-the-viking-ii"]
    assert result.created is True
    assert game.summary == preset.get("summary", "")
    assert game.description == preset["description"]
    assert game.website_url == preset.get("website_url")
    assert game.platforms == preset.get("platforms", [])
    assert game.igdb_genre_ids == preset.get("igdb_genre_ids", [])
    assert game.igdb_theme_ids == preset.get("igdb_theme_ids", [])
    assert game.igdb_keyword_ids == preset.get("igdb_keyword_ids", [])
    assert game.similar_game_names == preset.get("similar_game_names", [])


def test_run_volgarr_the_viking_ii_is_idempotent(db_path):
    first = run_volgarr_the_viking_ii(db_path)
    second = run_volgarr_the_viking_ii(db_path)

    user = UserRepository(db_path).get_by_email(DEV_EMAIL)
    assert user is not None
    games = [
        game
        for game in CustomerGameRepository(db_path).list_by_user(user.user_id)
        if game.name == "Volgarr the Viking II"
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
        customer_game_id=game.customer_game_id,
        user_id=user.user_id,
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
        customer_game_id=game.customer_game_id,
        user_id=user.user_id,
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
        customer_game_id=game.customer_game_id,
        user_id=user.user_id,
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


def test_run_volgarr_the_viking_ii_round_trips_all_settings_after_snapshot(
    db_path, tmp_path, monkeypatch
):
    preset_path = _copy_preset_file(tmp_path)
    monkeypatch.setattr(game_presets, "PRESET_FILE", preset_path)

    run_volgarr_the_viking_ii(db_path)

    user = UserRepository(db_path).get_by_email(DEV_EMAIL)
    assert user is not None
    repo = CustomerGameRepository(db_path)
    service = CustomerGameService(repo)
    game = next(
        game
        for game in repo.list_by_user(user.user_id)
        if game.name == "Volgarr the Viking II"
    )
    service.update_game(
        customer_game_id=game.customer_game_id,
        user_id=user.user_id,
        name="Volgarr the Viking II",
        summary="A brutal retro action platformer inspired by 1980s arcade design.",
        description="Updated Volgarr description from the setup page.",
        website_url="https://volgarr.example",
        platforms=["pc", "switch"],
        igdb_genre_ids=[8, 32],
        igdb_theme_ids=[1, 19],
        igdb_keyword_ids=["platformer", "retro"],
        similar_game_names=["Ghosts 'n Goblins", "Castlevania"],
    )

    run_snapshot_game_preset(db_path, "volgarr-the-viking-ii")
    repo.delete(game.customer_game_id)

    result = run_volgarr_the_viking_ii(db_path)

    reseeded = next(
        game
        for game in repo.list_by_user(user.user_id)
        if game.name == "Volgarr the Viking II"
    )
    assert result.created is True
    assert (
        reseeded.summary
        == "A brutal retro action platformer inspired by 1980s arcade design."
    )
    assert (
        reseeded.description
        == "Updated Volgarr description from the setup page."
    )
    assert reseeded.website_url == "https://volgarr.example"
    assert reseeded.platforms == ["pc", "switch"]
    assert reseeded.igdb_genre_ids == [8, 32]
    assert reseeded.igdb_theme_ids == [1, 19]
    assert reseeded.igdb_keyword_ids == ["platformer", "retro"]
    assert reseeded.similar_game_names == [
        "Ghosts 'n Goblins",
        "Castlevania",
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


def test_main_snapshot_game_preset_requires_preset_key(db_path):
    with pytest.raises(SystemExit) as exc_info:
        main(["--db-path", db_path, "snapshot-game-preset"])

    assert exc_info.value.code == 2


def test_main_strife_of_stars_returns_zero_and_writes_game(db_path):
    exit_code = main(["--db-path", db_path, "strife-of-stars"])

    user = UserRepository(db_path).get_by_email(DEV_EMAIL)
    assert user is not None
    games = CustomerGameRepository(db_path).list_by_user(user.user_id)

    assert exit_code == 0
    assert any(game.name == "Strife Of Stars" for game in games)


def test_main_volgarr_the_viking_ii_returns_zero_and_writes_game(db_path):
    exit_code = main(["--db-path", db_path, "volgarr-the-viking-ii"])

    user = UserRepository(db_path).get_by_email(DEV_EMAIL)
    assert user is not None
    games = CustomerGameRepository(db_path).list_by_user(user.user_id)

    assert exit_code == 0
    assert any(game.name == "Volgarr the Viking II" for game in games)


def test_main_grant_admin_defaults_to_dev_account(db_path):
    exit_code = main(["--db-path", db_path, "grant-admin"])

    user = UserRepository(db_path).get_by_email(DEV_EMAIL)
    assert user is not None
    assert exit_code == 0
    assert user.is_admin is True


def test_run_mint_session_creates_session_for_existing_user(db_path):
    user = UserRepository(db_path).create(
        user_id="user-1",
        email="oauth@example.com",
        password_hash=None,
        google_id="google-123",
    )

    result = run_mint_session(db_path, user.email)

    assert result.created is True
    assert len(result.message) > 20
    assert SessionRepository(db_path).get_by_id(result.message) is not None


def test_main_mint_session_returns_zero_and_prints_session_id(db_path, capsys):
    UserRepository(db_path).create(
        user_id="user-1",
        email="oauth@example.com",
        password_hash=None,
        google_id="google-123",
    )

    exit_code = main(
        ["--db-path", db_path, "mint-session", "oauth@example.com"]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert len(captured.out.strip()) > 20
