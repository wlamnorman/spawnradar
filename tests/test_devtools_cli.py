"""Tests for the local SpawnRadar developer CLI."""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import app.devtools.game_presets as game_presets
from app.auth.repository import UserRepository
from app.database import get_connection
from app.devtools.bootstrap import DEV_EMAIL
from app.devtools.cli import (
    main,
    run_clear_queues,
    run_reset_discovery_runs,
    run_rm_db,
    run_snapshot_game_preset,
    run_strife_of_stars,
    run_wikiquests,
)
from app.devtools.game_presets import PRESET_FILE, load_game_presets
from app.games.repository import (
    AssetRepository,
    GameRepository,
    MessageTemplateRepository,
)
from app.games.service import GameService


def _insert_prospect(db_path: str) -> str:
    now = datetime.now(UTC).isoformat()
    prospect_id = str(uuid.uuid4())
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO prospects
                (prospect_id, platform, handle, display_name, raw_data, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                prospect_id,
                "youtube",
                f"handle-{prospect_id[:8]}",
                "Queue Tester",
                json.dumps({}),
                now,
                now,
            ),
        )
    return prospect_id


def _insert_draft_item(db_path: str, game_id: str, prospect_id: str) -> str:
    now = datetime.now(UTC).isoformat()
    draft_item_id = str(uuid.uuid4())
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO draft_items
                (draft_item_id, game_id, prospect_id, body_text, status, score_breakdown, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                draft_item_id,
                game_id,
                prospect_id,
                "Hello from the queue",
                "queued",
                json.dumps({}),
                now,
                now,
            ),
        )
    return draft_item_id


def _insert_discovery_run(db_path: str, user_id: str, game_id: str) -> str:
    now = datetime.now(UTC).isoformat()
    run_id = str(uuid.uuid4())
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO discovery_runs (run_id, user_id, game_id, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (run_id, user_id, game_id, now),
        )
    return run_id


def _copy_preset_file(tmp_path) -> Path:
    target = tmp_path / "game_presets.json"
    target.write_text(PRESET_FILE.read_text())
    return target


def test_run_wikiquests_creates_expected_game(db_path):
    result = run_wikiquests(db_path)

    user = UserRepository(db_path).get_by_email(DEV_EMAIL)
    assert user is not None
    game = GameRepository(db_path).list_by_user(user.user_id)[0]

    assert result.created is True
    assert game.name == "WikiQuests"
    assert game.description == load_game_presets()["wikiquests"]["description"]
    assert game.website_url == "https://wikiquests.com"
    assert game.genre_tags == [
        "speedrun",
        "trivia",
        "racing",
        "daily challenge",
    ]
    assert game.audience_tags == [
        "wikipedia fans",
        "puzzle solvers",
        "speedrunners",
    ]
    assert game.platform_tags == ["browser"]


def test_run_wikiquests_is_idempotent_and_updates_existing_game(db_path):
    first = run_wikiquests(db_path)
    second = run_wikiquests(db_path)

    user = UserRepository(db_path).get_by_email(DEV_EMAIL)
    assert user is not None
    games = GameRepository(db_path).list_by_user(user.user_id)

    assert first.created is True
    assert second.created is False
    assert len(games) == 1
    assert games[0].description == load_game_presets()["wikiquests"]["description"]


def test_run_strife_of_stars_creates_expected_game(db_path):
    result = run_strife_of_stars(db_path)

    user = UserRepository(db_path).get_by_email(DEV_EMAIL)
    assert user is not None
    game = next(
        game
        for game in GameRepository(db_path).list_by_user(user.user_id)
        if game.name == "Strife Of Stars"
    )

    assert result.created is True
    assert game.description == load_game_presets()["strife-of-stars"]["description"]
    assert game.genre_tags == [
        "strategy",
        "roguelike",
        "roguelite",
        "turn-based tactics",
        "turn-based combat",
        "sci-fi",
    ]
    assert game.audience_tags == [
        "tactics players",
        "strategy fans",
        "sci-fi players",
        "roguelite fans",
        "challenge seekers",
        "chess fans",
    ]
    assert game.platform_tags == ["PC"]
    assert game.website_url is None


def test_run_strife_of_stars_is_idempotent(db_path):
    first = run_strife_of_stars(db_path)
    second = run_strife_of_stars(db_path)

    user = UserRepository(db_path).get_by_email(DEV_EMAIL)
    assert user is not None
    games = [
        game
        for game in GameRepository(db_path).list_by_user(user.user_id)
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
    repo = GameRepository(db_path)
    service = GameService(
        repo, AssetRepository(db_path), MessageTemplateRepository(db_path)
    )
    game = next(
        game for game in repo.list_by_user(user.user_id) if game.name == "Strife Of Stars"
    )
    service.update_game(
        game.game_id,
        user.user_id,
        name="Strife Of Stars",
        summary="A tighter tactical fleet roguelite for PC strategy fans.",
        description="Updated description from the setup page.",
        genre_tags_raw="",
        audience_tags_raw="",
        platform_tags=["PC", "Nintendo Switch"],
        website_url="https://strife.example",
        genre_primary_tags_raw="strategy, tactics",
        genre_secondary_tags_raw="sci-fi",
        audience_primary_tags_raw="strategy fans, pc players",
        mechanics_primary_tags_raw="grid-based, resource management",
        tone_primary_tags_raw="tense, atmospheric",
    )

    preset_path = _copy_preset_file(tmp_path)
    result = run_snapshot_game_preset(
        db_path, "strife-of-stars", preset_path=preset_path
    )

    presets = load_game_presets(preset_path)
    preset = presets["strife-of-stars"]
    assert result.message.startswith("Snapshotted Strife Of Stars into preset 'strife-of-stars'")
    assert preset["summary"] == "A tighter tactical fleet roguelite for PC strategy fans."
    assert preset["description"] == "Updated description from the setup page."
    assert preset["genre_primary_tags_raw"] == "strategy, tactics"
    assert preset["genre_secondary_tags_raw"] == "sci-fi"
    assert preset["audience_primary_tags_raw"] == "strategy fans, pc players"
    assert preset["mechanics_primary_tags_raw"] == "grid-based, resource management"
    assert preset["tone_primary_tags_raw"] == "tense, atmospheric"
    assert preset["platform_tags"] == ["PC", "Nintendo Switch"]
    assert preset["website_url"] == "https://strife.example"


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
    assert load_game_presets(preset_path)["strife-of-stars"]["name"] == "Strife Of Stars"


def test_run_clear_queues_removes_draft_items_and_outcomes(
    db_path, sample_game
):
    prospect_id = _insert_prospect(db_path)
    draft_item_id = _insert_draft_item(
        db_path, sample_game.game_id, prospect_id
    )
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO outcomes (outcome_id, draft_item_id, outcome_type)
            VALUES (?, ?, ?)
            """,
            (str(uuid.uuid4()), draft_item_id, "approved"),
        )

    result = run_clear_queues(db_path)

    with get_connection(db_path) as conn:
        draft_count = conn.execute(
            "SELECT COUNT(*) FROM draft_items"
        ).fetchone()[0]
        outcome_count = conn.execute(
            "SELECT COUNT(*) FROM outcomes"
        ).fetchone()[0]

    assert result.deleted_count == 1
    assert draft_count == 0
    assert outcome_count == 0


def test_run_rm_db_removes_database_and_sidecar_files(db_path):
    wal_path = f"{db_path}-wal"
    shm_path = f"{db_path}-shm"

    with open(wal_path, "w", encoding="utf-8") as fh:
        fh.write("wal")
    with open(shm_path, "w", encoding="utf-8") as fh:
        fh.write("shm")

    result = run_rm_db(db_path)

    assert result.deleted_count == 3
    assert not Path(db_path).exists()
    assert not Path(wal_path).exists()
    assert not Path(shm_path).exists()


def test_run_rm_db_reports_when_files_do_not_exist(tmp_path):
    missing_db = str(tmp_path / "missing.sqlite3")

    result = run_rm_db(missing_db)

    assert result.deleted_count is None
    assert result.message == f"No database files found at {missing_db}."


def test_run_reset_discovery_runs_defaults_to_dev_user(
    db_path, sample_game, registered_user
):
    run_wikiquests(db_path)

    dev_user = UserRepository(db_path).get_by_email(DEV_EMAIL)
    assert dev_user is not None
    dev_game = GameRepository(db_path).list_by_user(dev_user.user_id)[0]

    _insert_discovery_run(db_path, dev_user.user_id, dev_game.game_id)
    _insert_discovery_run(db_path, dev_user.user_id, dev_game.game_id)
    _insert_discovery_run(
        db_path, registered_user.user_id, sample_game.game_id
    )

    result = run_reset_discovery_runs(db_path)

    with get_connection(db_path) as conn:
        dev_count = conn.execute(
            "SELECT COUNT(*) FROM discovery_runs WHERE user_id = ?",
            (dev_user.user_id,),
        ).fetchone()[0]
        other_count = conn.execute(
            "SELECT COUNT(*) FROM discovery_runs WHERE user_id = ?",
            (registered_user.user_id,),
        ).fetchone()[0]

    assert result.deleted_count == 2
    assert result.message == (
        f"Reset discovery usage for {DEV_EMAIL}. Deleted 2 recorded runs."
    )
    assert dev_count == 0
    assert other_count == 1


def test_main_reset_discovery_runs_accepts_an_explicit_email(
    db_path, sample_game, registered_user
):
    _insert_discovery_run(db_path, registered_user.user_id, sample_game.game_id)

    exit_code = main(
        [
            "--db-path",
            db_path,
            "reset-discovery-runs",
            registered_user.email,
        ]
    )

    with get_connection(db_path) as conn:
        remaining = conn.execute(
            "SELECT COUNT(*) FROM discovery_runs WHERE user_id = ?",
            (registered_user.user_id,),
        ).fetchone()[0]

    assert exit_code == 0
    assert remaining == 0


def test_main_wikiquests_returns_zero_and_writes_game(db_path):
    exit_code = main(["--db-path", db_path, "wikiquests"])

    user = UserRepository(db_path).get_by_email(DEV_EMAIL)
    assert user is not None
    assert exit_code == 0
    assert len(GameRepository(db_path).list_by_user(user.user_id)) == 1


def test_main_strife_of_stars_returns_zero_and_writes_game(db_path):
    exit_code = main(["--db-path", db_path, "strife-of-stars"])

    user = UserRepository(db_path).get_by_email(DEV_EMAIL)
    assert user is not None
    games = GameRepository(db_path).list_by_user(user.user_id)

    assert exit_code == 0
    assert any(game.name == "Strife Of Stars" for game in games)


def test_main_rm_db_returns_zero_and_removes_database(db_path):
    exit_code = main(["--db-path", db_path, "rm-db"])

    assert exit_code == 0
    assert not Path(db_path).exists()
