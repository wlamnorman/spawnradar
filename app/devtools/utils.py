"""Shared utilities for the developer CLI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.devtools.bootstrap import ensure_dev_user
from app.devtools.game_presets import load_game_presets
from app.games.repository import CustomerGameRepository

PRESET_KEYS = (
    "wikiquests",
    "strife-of-stars",
    "forgetting-hour",
    "volgarr-the-viking-ii",
)


@dataclass(frozen=True)
class CommandResult:
    """Structured command result for printing and testing."""

    message: str
    created: bool | None = None
    deleted_count: int | None = None


def load_preset(
    preset_key: str, preset_path: str | Path | None = None
) -> dict[str, object]:
    presets = load_game_presets(preset_path)
    try:
        preset = presets[preset_key]
    except KeyError as exc:
        choices = ", ".join(sorted(presets))
        raise ValueError(
            f"Unknown game preset '{preset_key}'. Expected one of: {choices}."
        ) from exc
    return dict(preset)


def find_dev_game(db_path: str, game_ref: str | None, *, fallback_name: str):
    user = ensure_dev_user(db_path)
    games = CustomerGameRepository(db_path).list_by_user(user.user_id)
    target = (game_ref or fallback_name).strip()
    for game in games:
        if game.slug == target or game.name == target:
            return game
    raise ValueError(
        f"No dev game found matching '{target}'. Save the game first, then retry."
    )


def snapshot_payload_for_game(game) -> dict[str, object]:
    return {
        "name": game.name,
        "summary": game.summary or "",
        "description": game.description,
        "website_url": game.website_url,
        "platforms": game.platforms,
        "igdb_genre_ids": game.igdb_genre_ids,
        "igdb_theme_ids": game.igdb_theme_ids,
        "igdb_keyword_ids": game.igdb_keyword_ids,
        "similar_game_names": game.similar_game_names,
    }
