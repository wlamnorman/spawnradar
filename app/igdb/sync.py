from __future__ import annotations

import logging
from collections.abc import Sequence

from app.database import get_connection
from app.igdb.client import IGDBClient
from app.igdb.models import IGDBGame
from app.igdb.repository import IGDBRepository
from app.steam_enrichment.repository import SteamEnrichmentRepository

_IGDB_GAMES_URL = "https://api.igdb.com/v4/games"
_BACKFILL_BATCH_SIZE = 500

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
        self._db_path = db_path
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

    async def backfill_parent_games(self) -> int:
        """Populate parent_game_id for existing rows that lack it.

        Fetches ``id,parent_game`` in batches from IGDB for every
        locally-cached game whose ``parent_game_id`` is NULL.

        For any game that turns out to have a parent, the parent is also
        fetched and upserted if not already present locally.

        Returns the number of rows updated.
        """
        with get_connection(self._db_path) as con:
            rows = con.execute(
                "SELECT igdb_id FROM igdb_games ORDER BY igdb_id"
            ).fetchall()
        all_ids = [int(r["igdb_id"]) for r in rows]
        if not all_ids:
            return 0

        updated = 0
        parent_ids_to_fetch: set[int] = set()
        all_ids_set = set(all_ids)

        for offset in range(0, len(all_ids), _BACKFILL_BATCH_SIZE):
            batch = all_ids[offset : offset + _BACKFILL_BATCH_SIZE]
            id_list = ",".join(str(i) for i in batch)
            query = (
                f"fields id,parent_game; "
                f"where id = ({id_list}); "
                f"limit {_BACKFILL_BATCH_SIZE};"
            )
            items = await self._client.raw_post(_IGDB_GAMES_URL, query)

            with get_connection(self._db_path) as con:
                for item in items:
                    igdb_id = int(item["id"])
                    parent_game_id = (
                        int(item["parent_game"])
                        if item.get("parent_game")
                        else None
                    )
                    con.execute(
                        "UPDATE igdb_games "
                        "SET parent_game_id = ? "
                        "WHERE igdb_id = ?",
                        (parent_game_id, igdb_id),
                    )
                    updated += 1
                    if parent_game_id and parent_game_id not in all_ids_set:
                        parent_ids_to_fetch.add(parent_game_id)

            log.info(
                "IGDB backfill: processed batch offset=%d size=%d",
                offset,
                len(items),
            )

        # Fetch and upsert any parent games not already in the local DB
        fetched_parents = 0
        for parent_id in parent_ids_to_fetch:
            game = await self._client.fetch_game_by_id(parent_id)
            if game:
                self._repository.upsert(game)
                fetched_parents += 1

        log.info(
            "IGDB backfill complete: %d rows updated, %d parent games fetched",
            updated,
            fetched_parents,
        )
        return updated
