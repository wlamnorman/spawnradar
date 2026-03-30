"""Tests for catalog game definition loading."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.creator_index.catalog import (
    _CATALOG_USER_ID,
    load_catalog_game,
    load_catalog_games,
)


def _write_definition(tmp_path: Path, name: str, data: dict) -> Path:
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(data))
    return path


PATCHWORK_ACRES = {
    "customer_game_name": "Patchwork Acres",
    "customer_game_slug_hint": "patchwork-acres",
    "baseline_summary": "A cozy farming sim.",
    "broad_igdb_genres": [
        {"id": 32, "label": "Indie"},
        {"id": 13, "label": "Simulator"},
    ],
    "broad_igdb_themes": [
        {"id": 27, "label": "Comedy"},
        {"id": 33, "label": "Sandbox"},
    ],
    "required_game_modes": [
        {"id": 1, "label": "Single player"},
        {"id": 3, "label": "Co-operative"},
    ],
    "extra_custom_tags": ["cozy", "farming simulation"],
}


class TestLoadCatalogGame:
    def test_basic_fields(self, tmp_path: Path):
        path = _write_definition(tmp_path, "patchwork", PATCHWORK_ACRES)
        game = load_catalog_game(path)

        assert game.name == "Patchwork Acres"
        assert game.user_id == _CATALOG_USER_ID
        assert game.customer_game_id == "catalog-patchwork-acres"
        assert game.slug == "patchwork-acres"
        assert game.status == "active"

    def test_igdb_genre_ids(self, tmp_path: Path):
        path = _write_definition(tmp_path, "patchwork", PATCHWORK_ACRES)
        game = load_catalog_game(path)
        assert game.igdb_genre_ids == [32, 13]

    def test_igdb_theme_ids(self, tmp_path: Path):
        path = _write_definition(tmp_path, "patchwork", PATCHWORK_ACRES)
        game = load_catalog_game(path)
        assert game.igdb_theme_ids == [27, 33]

    def test_game_mode_ids(self, tmp_path: Path):
        path = _write_definition(tmp_path, "patchwork", PATCHWORK_ACRES)
        game = load_catalog_game(path)
        assert game.igdb_game_mode_ids == [1, 3]

    def test_keyword_ids_from_extra_custom_tags(self, tmp_path: Path):
        path = _write_definition(tmp_path, "patchwork", PATCHWORK_ACRES)
        game = load_catalog_game(path)
        assert game.igdb_keyword_ids == ["cozy", "farming simulation"]

    def test_anchor_games_become_similar_game_names(self, tmp_path: Path):
        data = {
            **PATCHWORK_ACRES,
            "anchor_games": ["Stardew Valley", "Story of Seasons"],
        }
        path = _write_definition(tmp_path, "with_anchors", data)
        game = load_catalog_game(path)
        assert game.similar_game_names == [
            "Stardew Valley",
            "Story of Seasons",
        ]

    def test_no_anchor_games(self, tmp_path: Path):
        path = _write_definition(tmp_path, "patchwork", PATCHWORK_ACRES)
        game = load_catalog_game(path)
        assert game.similar_game_names == []

    def test_slug_generated_when_no_hint(self, tmp_path: Path):
        data = dict(PATCHWORK_ACRES)
        del data["customer_game_slug_hint"]
        path = _write_definition(tmp_path, "no_slug", data)
        game = load_catalog_game(path)
        assert game.slug == "patchwork-acres"
        assert game.customer_game_id == "catalog-patchwork-acres"

    def test_summary_used_as_description(self, tmp_path: Path):
        path = _write_definition(tmp_path, "patchwork", PATCHWORK_ACRES)
        game = load_catalog_game(path)
        assert game.summary == "A cozy farming sim."
        assert game.description == "A cozy farming sim."


class TestLoadCatalogGames:
    def test_loads_all_json_files(self, tmp_path: Path):
        _write_definition(tmp_path, "game_a", PATCHWORK_ACRES)
        data_b = {**PATCHWORK_ACRES, "customer_game_name": "Hollow Tides"}
        _write_definition(tmp_path, "game_b", data_b)

        games = load_catalog_games(tmp_path)
        assert len(games) == 2
        names = {g.name for g in games}
        assert names == {"Patchwork Acres", "Hollow Tides"}

    def test_skips_invalid_json(self, tmp_path: Path):
        _write_definition(tmp_path, "good", PATCHWORK_ACRES)
        (tmp_path / "bad.json").write_text("{invalid json")

        games = load_catalog_games(tmp_path)
        assert len(games) == 1

    def test_skips_missing_required_field(self, tmp_path: Path):
        _write_definition(tmp_path, "good", PATCHWORK_ACRES)
        _write_definition(tmp_path, "bad", {"some_other_key": "value"})

        games = load_catalog_games(tmp_path)
        assert len(games) == 1

    def test_empty_directory(self, tmp_path: Path):
        games = load_catalog_games(tmp_path)
        assert games == []


class TestLoadRealSandboxDefinitions:
    """Smoke test against the actual sandbox definition files."""

    _SANDBOX_DIR = Path(__file__).resolve().parent.parent / (
        "sandbox/crawl_experiments/initial_experiments/game_defs"
    )

    @pytest.mark.skipif(
        not (
            _SANDBOX_DIR := Path(__file__).resolve().parent.parent
            / "sandbox/crawl_experiments/initial_experiments/game_defs"
        ).exists(),
        reason="Sandbox definitions not present",
    )
    def test_loads_sandbox_definitions(self):
        sandbox_dir = (
            Path(__file__).resolve().parent.parent
            / "sandbox/crawl_experiments/initial_experiments/game_defs"
        )
        games = load_catalog_games(sandbox_dir)
        assert len(games) == 4
        names = {g.name for g in games}
        assert "Patchwork Acres" in names
        assert "Hollow Tides" in names
        for game in games:
            assert game.user_id == _CATALOG_USER_ID
            assert game.igdb_genre_ids  # all definitions have genres


class TestLoadRealAppCatalogDefinitions:
    def test_loads_app_catalog_definitions(self):
        catalog_dir = Path(__file__).resolve().parent.parent / "app/catalog"
        games = load_catalog_games(catalog_dir)
        names = {g.name for g in games}

        assert "Volgarr the Viking II" in names

        volgarr = next(g for g in games if g.name == "Volgarr the Viking II")
        assert volgarr.slug == "volgarr-the-viking-ii"
        assert volgarr.summary.startswith(  # pyright: ignore[reportOptionalMemberAccess]
            "Return to the Golden Age of arcades"
        )
        assert volgarr.igdb_genre_ids == [31, 33, 32, 8]
        assert volgarr.igdb_theme_ids == [1]
        assert volgarr.igdb_game_mode_ids == [1]
        assert volgarr.igdb_keyword_ids == ["soulslike"]
        assert volgarr.similar_game_names == []
