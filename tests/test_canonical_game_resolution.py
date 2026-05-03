"""Tests for canonical (base) game resolution.

Covers:
- upsert stores parent_game_id
- search_by_name excludes non-base games
- resolve_similar_game_ids follows parent_game_id to the base game
- column migration for existing databases
"""

import os
import tempfile

from app.database import get_connection, initialize_database
from app.igdb.models import IGDBGame
from app.igdb.repository import IGDBRepository
from app.igdb.taxonomy import IGDBGenre, IGDBTheme
from app.matches.repository import MatchRepository


def _make_db() -> str:
    with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as f:
        db_path = f.name
    initialize_database(db_path)
    return db_path


def _base_game() -> IGDBGame:
    return IGDBGame(
        igdb_id=119133,
        name="Elden Ring",
        slug="elden-ring",
        summary="An action RPG.",
        genre_ids=[IGDBGenre.ROLE_PLAYING],
        theme_ids=[IGDBTheme.ACTION, IGDBTheme.FANTASY],
        first_release_date=1645747200,
        parent_game_id=None,
    )


def _dlc_game() -> IGDBGame:
    return IGDBGame(
        igdb_id=272323,
        name="Elden Ring: Shadow of the Erdtree",
        slug="elden-ring-shadow-of-the-erdtree",
        summary="A DLC expansion.",
        genre_ids=[IGDBGenre.ROLE_PLAYING],
        theme_ids=[IGDBTheme.ACTION, IGDBTheme.FANTASY],
        first_release_date=1718928000,
        parent_game_id=119133,
    )


def _expansion_game() -> IGDBGame:
    return IGDBGame(
        igdb_id=55555,
        name="Slay the Spire 2: The Ironclad Rises",
        slug="sts2-ironclad",
        summary="An expansion.",
        genre_ids=[IGDBGenre.STRATEGY],
        theme_ids=[],
        first_release_date=1700000000,
        parent_game_id=77777,
    )


def _expansion_parent() -> IGDBGame:
    return IGDBGame(
        igdb_id=77777,
        name="Slay the Spire 2",
        slug="slay-the-spire-2",
        summary="A deckbuilding roguelike.",
        genre_ids=[IGDBGenre.STRATEGY],
        theme_ids=[],
        first_release_date=1690000000,
        parent_game_id=None,
    )


# --- upsert stores new fields ------------------------------------------------


def test_upsert_stores_parent_game_id():
    db = _make_db()
    try:
        repo = IGDBRepository(db)
        repo.upsert(_base_game())
        repo.upsert(_dlc_game())

        base = repo.get(119133)
        assert base is not None
        assert base["parent_game_id"] is None

        dlc = repo.get(272323)
        assert dlc is not None
        assert dlc["parent_game_id"] == 119133
    finally:
        os.unlink(db)


# --- search_by_name filters non-base games -----------------------------------


def test_search_by_name_excludes_dlc():
    db = _make_db()
    try:
        repo = IGDBRepository(db)
        repo.upsert(_base_game())
        repo.upsert(_dlc_game())

        results = repo.search_by_name("elden ring")
        names = [r["name"] for r in results]
        assert "Elden Ring" in names
        assert "Elden Ring: Shadow of the Erdtree" not in names
    finally:
        os.unlink(db)


def test_search_by_name_excludes_expansion():
    db = _make_db()
    try:
        repo = IGDBRepository(db)
        repo.upsert(_expansion_parent())
        repo.upsert(_expansion_game())

        results = repo.search_by_name("slay the spire")
        names = [r["name"] for r in results]
        assert "Slay the Spire 2" in names
        assert "Slay the Spire 2: The Ironclad Rises" not in names
    finally:
        os.unlink(db)


def test_search_by_name_returns_base_games():
    """Games without a parent should appear normally."""
    db = _make_db()
    try:
        repo = IGDBRepository(db)
        game = IGDBGame(
            igdb_id=999,
            name="Hollow Knight",
            slug="hollow-knight",
            summary="A metroidvania.",
            genre_ids=[],
            theme_ids=[],
            first_release_date=1487635200,
        )
        repo.upsert(game)

        results = repo.search_by_name("hollow")
        assert len(results) == 1
        assert results[0]["name"] == "Hollow Knight"
    finally:
        os.unlink(db)


# --- resolve_similar_game_ids follows parent ----------------------------------


def test_resolve_follows_parent_game_id():
    db = _make_db()
    try:
        repo = IGDBRepository(db)
        repo.upsert(_base_game())
        repo.upsert(_dlc_game())

        match_repo = MatchRepository(db)
        ids = match_repo.resolve_similar_game_ids(
            ["Elden Ring: Shadow of the Erdtree"]
        )
        # Should resolve to the base game, not the DLC
        assert 119133 in ids
        assert 272323 not in ids
    finally:
        os.unlink(db)


def test_resolve_base_game_stays_unchanged():
    db = _make_db()
    try:
        repo = IGDBRepository(db)
        repo.upsert(_base_game())

        match_repo = MatchRepository(db)
        ids = match_repo.resolve_similar_game_ids(["Elden Ring"])
        assert ids == (119133,)
    finally:
        os.unlink(db)


def test_resolve_deduplicates_after_parent_resolution():
    """If both base and DLC are in similar games, resolve to one ID."""
    db = _make_db()
    try:
        repo = IGDBRepository(db)
        repo.upsert(_base_game())
        repo.upsert(_dlc_game())

        match_repo = MatchRepository(db)
        ids = match_repo.resolve_similar_game_ids(
            ["Elden Ring", "Elden Ring: Shadow of the Erdtree"]
        )
        # Both should resolve to 119133, deduplicated via DISTINCT
        assert ids == (119133,)
    finally:
        os.unlink(db)


def test_resolve_with_missing_parent_in_db():
    """If parent isn't cached locally, fall back to the DLC's own ID."""
    db = _make_db()
    try:
        repo = IGDBRepository(db)
        # Only insert the expansion, not its parent
        repo.upsert(_expansion_game())

        match_repo = MatchRepository(db)
        ids = match_repo.resolve_similar_game_ids(
            ["Slay the Spire 2: The Ironclad Rises"]
        )
        # Parent 77777 not in DB, so COALESCE falls back to 55555
        assert ids == (55555,)
    finally:
        os.unlink(db)


# --- column migration ---------------------------------------------------------


def test_migration_adds_columns_to_existing_db():
    """Verify parent_game_id column exists after initialization."""
    db = _make_db()
    try:
        with get_connection(db) as con:
            cols = {
                row[1]
                for row in con.execute(
                    "PRAGMA table_info(igdb_games)"
                ).fetchall()
            }
            assert "parent_game_id" in cols

        # Re-running initialize_database should be idempotent
        initialize_database(db)

        with get_connection(db) as con:
            cols = {
                row[1]
                for row in con.execute(
                    "PRAGMA table_info(igdb_games)"
                ).fetchall()
            }
            assert "parent_game_id" in cols
    finally:
        os.unlink(db)
