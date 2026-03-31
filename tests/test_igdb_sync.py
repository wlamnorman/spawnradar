import os
import tempfile
from unittest.mock import AsyncMock, patch

import pytest

from app.database import initialize_database
from app.igdb.models import IGDBGame
from app.igdb.repository import IGDBRepository
from app.igdb.sync import IGDBSyncService
from app.igdb.taxonomy import IGDBGenre, IGDBTheme
from app.steam_enrichment.repository import SteamEnrichmentRepository


def make_db():
    with tempfile.NamedTemporaryFile(
        suffix=".sqlite3", delete=False
    ) as temp_file:
        db_path = temp_file.name
    initialize_database(db_path)
    return db_path


def fake_game(igdb_id: int) -> IGDBGame:
    return IGDBGame(
        igdb_id=igdb_id,
        name=f"Game {igdb_id}",
        slug=f"game-{igdb_id}",
        summary=None,
        genre_ids=[IGDBGenre.ROLE_PLAYING],
        theme_ids=[IGDBTheme.FANTASY],
        first_release_date=None,
    )


@pytest.mark.anyio
async def test_full_sync_paginates_until_empty():
    db = make_db()
    try:
        service = IGDBSyncService(db_path=db, client_id="x", client_secret="y")
        page1 = [fake_game(i) for i in range(500)]
        page2 = [fake_game(i + 500) for i in range(200)]
        with patch.object(
            service._client,
            "fetch_games",
            new=AsyncMock(side_effect=[page1, page2, []]),
        ):
            total = await service.full_sync()
        assert total == 700
        assert IGDBRepository(db).count() == 700
    finally:
        os.unlink(db)


@pytest.mark.anyio
async def test_fetch_game_persists_single_game():
    db = make_db()
    try:
        service = IGDBSyncService(db_path=db, client_id="x", client_secret="y")
        with patch.object(
            service._client,
            "fetch_game_by_id",
            new=AsyncMock(return_value=fake_game(296831)),
        ):
            fetched = await service.fetch_game(296831)

        assert fetched is True
        row = IGDBRepository(db).get(296831)
        assert row is not None
        assert row["name"] == "Game 296831"
        candidates = SteamEnrichmentRepository(db).load_backfill_candidates(
            limit=10
        )
        assert any(candidate.igdb_id == 296831 for candidate in candidates)
    finally:
        os.unlink(db)
