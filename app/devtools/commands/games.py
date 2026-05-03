"""Game seeding commands for the developer CLI."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from app.database import initialize_database
from app.devtools.bootstrap import (
    DEV_EMAIL,
    TEST_EMAIL,
    ensure_dev_user,
    ensure_test_user,
)
from app.devtools.game_presets import load_game_presets, save_game_presets
from app.devtools.utils import (
    CommandResult,
    find_dev_game,
    load_preset,
    snapshot_payload_for_game,
)
from app.games.repository import CustomerGameRepository
from app.games.service import CustomerGameService


def _seed_game(
    db_path: str,
    *,
    name: str,
    summary: str = "",
    description: str,
    website_url: str | None,
    platforms: list[str] | None = None,
    igdb_genre_ids: list[int] | None = None,
    igdb_theme_ids: list[int] | None = None,
    igdb_keyword_ids: list[str] | None = None,
    similar_game_names: list[str] | None = None,
    user_email: str = DEV_EMAIL,
    ensure_user: object = ensure_dev_user,
) -> CommandResult:
    """Create or update a game under the specified user account."""
    initialize_database(db_path)
    user = ensure_user(db_path)  # type: ignore[operator]
    game_repo = CustomerGameRepository(db_path)
    service = CustomerGameService(game_repo)

    existing = next(
        (
            game
            for game in game_repo.list_by_user(user.user_id)
            if game.name == name
        ),
        None,
    )
    payload: dict = {
        "name": name,
        "summary": summary,
        "description": description,
        "website_url": website_url,
        "platforms": platforms,
        "igdb_genre_ids": igdb_genre_ids,
        "igdb_theme_ids": igdb_theme_ids,
        "igdb_keyword_ids": igdb_keyword_ids,
        "similar_game_names": similar_game_names,
    }

    if existing is None:
        game = service.create_game(user_id=user.user_id, **payload)
        return CommandResult(
            message=(
                f"Created {name} for {user_email} "
                f"({game.customer_game_id}) at {game.website_url or 'no website'}"
            ),
            created=True,
        )

    game = service.update_game(
        customer_game_id=existing.customer_game_id,
        user_id=user.user_id,
        **payload,
    )
    return CommandResult(
        message=(
            f"Updated {name} for {user_email} "
            f"({game.customer_game_id}) at {game.website_url or 'no website'}"
        ),
        created=False,
    )


def _seed_preset_game(
    db_path: str,
    preset_key: str,
    preset_path: str | Path | None = None,
    *,
    user_email: str = DEV_EMAIL,
    ensure_user: object = ensure_dev_user,
) -> CommandResult:
    preset = load_preset(preset_key, preset_path)
    return _seed_game(
        db_path,
        name=str(preset["name"]),
        summary=str(preset.get("summary", "")),
        description=str(preset["description"]),
        website_url=cast(str | None, preset.get("website_url")),
        platforms=cast(list[str] | None, preset.get("platforms")),
        igdb_genre_ids=cast(list[int] | None, preset.get("igdb_genre_ids")),
        igdb_theme_ids=cast(list[int] | None, preset.get("igdb_theme_ids")),
        igdb_keyword_ids=cast(
            list[str] | None, preset.get("igdb_keyword_ids")
        ),
        similar_game_names=cast(
            list[str] | None, preset.get("similar_game_names")
        ),
        user_email=user_email,
        ensure_user=ensure_user,
    )


def run_wikiquests(db_path: str) -> CommandResult:
    """Seed or refresh the WikiQuests game for the local dev user."""
    return _seed_preset_game(db_path, "wikiquests")


def run_strife_of_stars(db_path: str) -> CommandResult:
    """Seed or refresh the Strife Of Stars game for the local dev user."""
    return _seed_preset_game(db_path, "strife-of-stars")


def run_forgetting_hour(db_path: str) -> CommandResult:
    """Seed or refresh The Forgetting Hour game for the local dev user."""
    return _seed_preset_game(db_path, "forgetting-hour")


def run_volgarr_the_viking_ii(db_path: str) -> CommandResult:
    """Seed or refresh Volgarr the Viking II for the local dev user."""
    return _seed_preset_game(db_path, "volgarr-the-viking-ii")


def run_seed_test_user(db_path: str) -> CommandResult:
    """Create a test user with Strife Of Stars for non-subscriber testing."""
    return _seed_preset_game(
        db_path,
        "strife-of-stars",
        user_email=TEST_EMAIL,
        ensure_user=ensure_test_user,
    )


def run_snapshot_game_preset(
    db_path: str,
    preset_key: str,
    game_ref: str | None = None,
    *,
    preset_path: str | Path | None = None,
) -> CommandResult:
    """Overwrite a built-in dev-game preset from the saved local DB state."""
    initialize_database(db_path)
    presets = load_game_presets(preset_path)
    if preset_key not in presets:
        choices = ", ".join(sorted(presets))
        raise ValueError(
            f"Unknown game preset '{preset_key}'. Expected one of: {choices}."
        )
    fallback_name = str(presets[preset_key].get("name") or preset_key)
    game = find_dev_game(db_path, game_ref, fallback_name=fallback_name)
    presets[preset_key] = snapshot_payload_for_game(game)
    output_path = save_game_presets(presets, preset_path)
    return CommandResult(
        message=(
            f"Snapshotted {game.name} into preset '{preset_key}' at {output_path}."
        ),
        created=False,
    )
