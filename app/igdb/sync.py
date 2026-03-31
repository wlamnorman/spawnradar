from __future__ import annotations

import logging
from collections.abc import Sequence

from app.igdb.client import IGDBClient
from app.igdb.models import IGDBGame
from app.igdb.repository import IGDBRepository
from app.steam_enrichment.repository import SteamEnrichmentRepository

log = logging.getLogger(__name__)
_PAGE_SIZE = 500


class IGDBSyncService:
    def __init__(
        self,
        *,
        db_path: str,
        client_id: str,
        client_secret: str,
        repository: IGDBRepository | None = None,
    ) -> None:
        self._client = IGDBClient(
            client_id=client_id, client_secret=client_secret
        )
        self._repository = repository or IGDBRepository(db_path)
        self._steam_enrichment_repository = SteamEnrichmentRepository(db_path)

    async def full_sync(self) -> int:
        total, offset = 0, 0
        while True:
            games = await self._client.fetch_games(
                limit=_PAGE_SIZE, offset=offset
            )
            if not games:
                break
            for game in games:
                self._repository.upsert(game)
                self._steam_enrichment_repository.mark_pending(game.igdb_id)
            total += len(games)
            log.info(
                "IGDB sync: offset=%d stored=%d total=%d",
                offset,
                len(games),
                total,
            )
            offset += len(games)
            if len(games) < _PAGE_SIZE:
                break
        log.info("IGDB full sync complete: %d games", total)
        return total

    async def fetch_game(self, igdb_id: int) -> bool:
        game = await self._client.fetch_game_by_id(igdb_id)
        if game is None:
            log.debug("IGDB fetch returned no game for %s", igdb_id)
            return False
        self._repository.upsert(game)
        self._steam_enrichment_repository.mark_pending(game.igdb_id)
        log.debug("IGDB fetched game %s (%s)", game.igdb_id, game.name)
        return True

    async def fetch_games_by_tags(
        self,
        *,
        genre_ids: Sequence[int] = (),
        theme_ids: Sequence[int] = (),
        limit: int = 25,
        offset: int = 0,
    ) -> list[IGDBGame]:
        games = await self._client.fetch_games_by_tags(
            genre_ids=tuple(sorted({int(genre_id) for genre_id in genre_ids})),
            theme_ids=tuple(sorted({int(theme_id) for theme_id in theme_ids})),
            limit=limit,
            offset=offset,
        )
        for game in games:
            self._repository.upsert(game)
            self._steam_enrichment_repository.mark_pending(game.igdb_id)
        log.info(
            "IGDB fetched %d games for tags genres=%s themes=%s",
            len(games),
            sorted({int(genre_id) for genre_id in genre_ids}),
            sorted({int(theme_id) for theme_id in theme_ids}),
        )
        return games
