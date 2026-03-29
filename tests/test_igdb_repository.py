import os
import tempfile

from app.database import initialize_database
from app.igdb.models import IGDBGame
from app.igdb.repository import IGDBRepository
from app.igdb.taxonomy import IGDBGenre, IGDBTheme


def make_db() -> str:
    with tempfile.NamedTemporaryFile(
        suffix=".sqlite3", delete=False
    ) as temp_file:
        db_path = temp_file.name
    initialize_database(db_path)
    return db_path


def hades() -> IGDBGame:
    return IGDBGame(
        igdb_id=1994,
        name="Hades",
        slug="hades",
        summary="Roguelite dungeon crawler.",
        genre_ids=[IGDBGenre.ROLE_PLAYING, IGDBGenre.INDIE],
        theme_ids=[IGDBTheme.ACTION, IGDBTheme.FANTASY],
        first_release_date=1600300800,
        platform_ids=[6, 167],
        platform_names=["PC (Microsoft Windows)", "PlayStation 5"],
        keyword_names=["roguelike"],
    )


def test_upsert_and_get():
    db = make_db()
    try:
        repo = IGDBRepository(db)
        repo.upsert(hades())
        row = repo.get(1994)
        assert row is not None and row["name"] == "Hades"
        assert row["summary"] == "Roguelite dungeon crawler."
        assert row["platform_names_json"] == (
            '["PC (Microsoft Windows)", "PlayStation 5"]'
        )
    finally:
        os.unlink(db)


def test_upsert_is_idempotent():
    db = make_db()
    try:
        repo = IGDBRepository(db)
        repo.upsert(hades())
        repo.upsert(hades())
        assert repo.count() == 1
    finally:
        os.unlink(db)


def test_tags_stored_with_igdb_ids():
    db = make_db()
    try:
        repo = IGDBRepository(db)
        repo.upsert(hades())
        tags = repo.get_tags(1994)
        tag_ids = {t["tag_id"] for t in tags}
        assert IGDBGenre.ROLE_PLAYING in tag_ids
        assert IGDBTheme.FANTASY in tag_ids
        assert "roguelike" in tag_ids
    finally:
        os.unlink(db)


def test_list_by_theme():
    db = make_db()
    try:
        repo = IGDBRepository(db)
        repo.upsert(hades())
        results = repo.list_by_tag(tag_type="theme", tag_id=IGDBTheme.FANTASY)
        assert any(r["igdb_id"] == 1994 for r in results)
        results = repo.list_by_tag(tag_type="theme", tag_id=IGDBTheme.HORROR)
        assert not any(r["igdb_id"] == 1994 for r in results)
    finally:
        os.unlink(db)
