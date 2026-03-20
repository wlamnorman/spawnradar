"""Tests for the local SpawnRadar developer CLI."""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from app.auth.repository import UserRepository
from app.database import get_connection
from app.devtools.bootstrap import DEV_EMAIL
from app.devtools.cli import (
    STRIFE_OF_STARS_DESCRIPTION,
    WIKIQUESTS_DESCRIPTION,
    main,
    run_clear_queues,
    run_rm_db,
    run_strife_of_stars,
    run_wikiquests,
)
from app.games.repository import GameRepository


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


def test_run_wikiquests_creates_expected_game(db_path):
    result = run_wikiquests(db_path)

    user = UserRepository(db_path).get_by_email(DEV_EMAIL)
    assert user is not None
    game = GameRepository(db_path).list_by_user(user.user_id)[0]

    assert result.created is True
    assert game.name == "WikiQuests"
    assert game.description == WIKIQUESTS_DESCRIPTION
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
    assert games[0].description == WIKIQUESTS_DESCRIPTION


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
    assert game.description == STRIFE_OF_STARS_DESCRIPTION
    assert game.genre_tags == [
        "strategy",
        "roguelike",
        "roguelite",
        "turn-based tactics",
        "turn-based combat",
        "sci-fi",
        "space",
    ]
    assert game.audience_tags == [
        "tactics players",
        "strategy fans",
        "sci-fi players",
        "roguelite fans",
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
