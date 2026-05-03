"""Load catalog game definitions from JSON files.

Catalog definitions are pre-built game profiles (e.g. in ``sandbox/definitions/``)
used for pre-populating the creator database without a real customer account.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from app.games.models import CustomerGame

log = logging.getLogger(__name__)

_CATALOG_WORKSPACE_ID = "__catalog__"
CATALOG_USER_ID = _CATALOG_WORKSPACE_ID


def _slug_from_name(name: str) -> str:
    """Generate a URL-safe slug from a game name."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


def load_catalog_game(path: Path) -> CustomerGame:
    """Load a catalog game definition from a JSON file.

    The JSON is expected to have the structure used in
    ``sandbox/crawl_experiments/initial_experiments/game_defs/``.

    Returns a :class:`CustomerGame` with ``workspace_id`` set to the
    catalog sentinel value (``__catalog__``).
    """
    data = json.loads(path.read_text())

    name = data["customer_game_name"]
    slug = data.get("customer_game_slug_hint") or _slug_from_name(name)
    customer_game_id = f"catalog-{slug}"

    igdb_genre_ids = [g["id"] for g in data.get("broad_igdb_genres", [])]
    igdb_theme_ids = [t["id"] for t in data.get("broad_igdb_themes", [])]
    igdb_game_mode_ids = [m["id"] for m in data.get("required_game_modes", [])]
    igdb_keyword_ids = list(data.get("extra_custom_tags", []))
    similar_game_names = list(data.get("anchor_games", []))

    now = "2000-01-01T00:00:00"  # placeholder for catalog entries

    return CustomerGame(
        customer_game_id=customer_game_id,
        workspace_id=_CATALOG_WORKSPACE_ID,
        name=name,
        summary=data.get("baseline_summary", ""),
        description=data.get("baseline_summary", ""),
        website_url=None,
        status="active",
        slug=slug,
        created_at=now,
        updated_at=now,
        igdb_genre_ids=igdb_genre_ids,
        igdb_theme_ids=igdb_theme_ids,
        igdb_game_mode_ids=igdb_game_mode_ids,
        igdb_player_perspective_ids=[],
        igdb_keyword_ids=igdb_keyword_ids,
        similar_game_names=similar_game_names,
    )


def load_catalog_games(directory: Path) -> list[CustomerGame]:
    """Load all ``*.json`` catalog definitions from *directory*."""
    games: list[CustomerGame] = []
    for path in sorted(directory.glob("*.json")):
        try:
            games.append(load_catalog_game(path))
        except (json.JSONDecodeError, KeyError):
            log.warning("Skipping invalid catalog definition: %s", path)
    return games
