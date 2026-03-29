"""Background sync service for the reusable source-account index."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

from app.creator_index.adapters.base import (
    AccountSeedBundle,
    ContentSampleSeed,
    ObservedGameSeed,
    TwitchProfileSeed,
    YouTubeChannelSeed,
)
from app.creator_index.catalog import load_catalog_games
from app.creator_index.discovery import (
    EnrichedCreator,
    crawl_top_categories,
    discover_creators,
)
from app.creator_index.enrichment import TwitchEnrichment
from app.creator_index.facets import build_creator_profile_facets
from app.creator_index.models import (
    CustomerGameSyncSummary,
    PlatformSyncSummary,
    SweepSyncSummary,
)
from app.creator_index.repository import CreatorIndexRepository
from app.creator_index.stream_discovery import (
    TwitchGame,
    TwitchStreamClient,
)
from app.database import get_connection, initialize_database
from app.games.models import CustomerGame
from app.games.repository import CustomerGameRepository
from app.igdb.client import IGDBClient
from app.igdb.repository import IGDBRepository
from app.igdb.sync import IGDBSyncService
from app.runtime import SourceRuntime

log = logging.getLogger(__name__)
_TWITCH_RETAINED_CONTENT_SAMPLE_LIMIT = 1


class CreatorIndexService:
    """Owns background crawling and persistence for reusable platform data."""

    def __init__(
        self,
        *,
        db_path: str,
        source_runtime: SourceRuntime | None = None,
        repository: CreatorIndexRepository | None = None,
    ) -> None:
        self._db_path = db_path
        initialize_database(db_path)
        self._runtime = source_runtime or SourceRuntime()
        self._repository = repository or CreatorIndexRepository(db_path)

        # Lazy-init pipeline components from runtime credentials
        cid = self._runtime.twitch_client_id
        csecret = self._runtime.twitch_client_secret
        self._igdb_client = IGDBClient(client_id=cid, client_secret=csecret)
        self._enrichment = TwitchEnrichment(cid, csecret)
        self._twitch_stream_client = TwitchStreamClient(
            client_id=cid, client_secret=csecret
        )
        self._igdb_repo = IGDBRepository(db_path)
        self._category_offset = self._load_category_offset()

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    async def sync_active_customer_games(self) -> SweepSyncSummary:
        """Discover and persist creators for every active customer game."""
        customer_games = self._list_active_customer_games()
        game_summaries = [
            await self.sync_customer_game(cg) for cg in customer_games
        ]
        return self._summarize_customer_game_syncs(game_summaries)

    async def sync_customer_game(
        self, customer_game: CustomerGame
    ) -> CustomerGameSyncSummary:
        """Run the discovery pipeline for one customer game.

        Calls :func:`discover_creators` and persists each yielded
        :class:`EnrichedCreator` via the existing repository methods.
        """
        total_accounts = 0
        total_samples = 0
        total_contacts = 0

        current_offset = self._category_offset
        try:
            async for creator in discover_creators(
                customer_game,
                igdb_client=self._igdb_client,
                twitch_client=self._twitch_stream_client,
                enrichment=self._enrichment,
                igdb_repo=self._igdb_repo,
                category_offset=current_offset,
                db_path=self._db_path,
            ):
                (
                    accounts,
                    samples,
                    contacts,
                ) = await self._persist_enriched_creator(creator)
                total_accounts += accounts
                total_samples += samples
                total_contacts += contacts
        except Exception:
            log.exception(
                "Discovery pipeline failed for customer game %s (%s)",
                customer_game.customer_game_id,
                customer_game.name,
            )

        # Advance offset for next run so we crawl different categories
        self._category_offset += 20
        self._save_category_offset()

        platform_summary = PlatformSyncSummary(
            platform="twitch",
            accounts_synced=total_accounts,
            content_samples_synced=total_samples,
            contact_points_synced=total_contacts,
        )
        return CustomerGameSyncSummary(
            customer_game_id=customer_game.customer_game_id,
            customer_game_name=customer_game.name,
            platform_summaries=(platform_summary,),
        )

    async def run_top_categories_crawl(self) -> int:
        """Pre-populate the creator DB by crawling top Twitch categories.

        Returns count of creators discovered.
        """
        count = 0
        try:
            async for creator in crawl_top_categories(
                self._twitch_stream_client,
                self._enrichment,
                self._igdb_repo,
                db_path=self._db_path,
            ):
                await self._persist_enriched_creator(creator)
                count += 1
        except Exception:
            log.exception("Top categories crawl failed")
        log.info("Top categories crawl persisted %d creators", count)
        return count

    async def run_catalog_discovery(self, catalog_dir: Path) -> dict[str, int]:
        """Run discovery against catalog game definitions for pre-population.

        Returns ``{definition_name: creator_count}``.
        """
        results: dict[str, int] = {}
        catalog_games = load_catalog_games(catalog_dir)

        for cg in catalog_games:
            count = 0
            try:
                async for creator in discover_creators(
                    cg,
                    igdb_client=self._igdb_client,
                    twitch_client=self._twitch_stream_client,
                    enrichment=self._enrichment,
                    igdb_repo=self._igdb_repo,
                    db_path=self._db_path,
                ):
                    await self._persist_enriched_creator(creator)
                    count += 1
            except Exception:
                log.exception(
                    "Catalog discovery failed for %s",
                    cg.name,
                )
            results[cg.name] = count
            log.info(
                "Catalog discovery for '%s': %d creators",
                cg.name,
                count,
            )

        return results

    # ------------------------------------------------------------------
    # Category offset persistence
    # ------------------------------------------------------------------

    _OFFSET_SCOPE = "discovery"
    _OFFSET_KEY = "category_offset"

    def _load_category_offset(self) -> int:
        """Load the persisted category rotation offset, defaulting to 0."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT cursor_value FROM crawl_cursors "
                "WHERE platform = 'twitch' AND cursor_scope = ? AND cursor_key = ?",
                (self._OFFSET_SCOPE, self._OFFSET_KEY),
            ).fetchone()
        if row is None:
            return 0
        try:
            return int(row[0])
        except (ValueError, TypeError):
            return 0

    def _save_category_offset(self) -> None:
        """Persist the current category offset for the next run."""
        from datetime import UTC, datetime

        now = datetime.now(UTC).isoformat()
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO crawl_cursors (platform, cursor_scope, cursor_key, cursor_value, updated_at)
                VALUES ('twitch', ?, ?, ?, ?)
                ON CONFLICT(platform, cursor_scope, cursor_key) DO UPDATE SET
                    cursor_value = excluded.cursor_value,
                    updated_at = excluded.updated_at
                """,
                (self._OFFSET_SCOPE, self._OFFSET_KEY, str(self._category_offset), now),
            )

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    async def _persist_enriched_creator(
        self, creator: EnrichedCreator
    ) -> tuple[int, int, int]:
        """Persist one enriched creator using existing repository methods.

        Returns ``(accounts, samples, contacts)`` counts.
        """
        bundle = creator.bundle
        return await self._persist_bundles("twitch", (bundle,))

    async def _persist_bundles(
        self,
        platform: str,
        bundles: Sequence[AccountSeedBundle],
    ) -> tuple[int, int, int]:
        """Persist a batch of bundles. Used by ingestion and tests."""
        accounts_synced = 0
        content_samples_synced = 0
        contact_points_synced = 0
        for bundle in bundles:
            account = self._repository.upsert_source_account(
                platform, bundle.account
            )
            if isinstance(bundle.platform_profile, TwitchProfileSeed):
                self._repository.upsert_twitch_profile_latest(
                    account.account_id, bundle.platform_profile
                )
                if bundle.platform_profile.viewer_count is not None:
                    self._repository.insert_metric_sample(
                        account_id=account.account_id,
                        platform=platform,
                        metric_key="live_viewers",
                        metric_value=float(
                            bundle.platform_profile.viewer_count
                        ),
                        observed_at=bundle.platform_profile.fetched_at,
                    )
                    (
                        recent_avg_live_viewers,
                        recent_median_live_viewers,
                    ) = self._repository.recent_metric_stats(
                        account_id=account.account_id,
                        platform=platform,
                        metric_key="live_viewers",
                    )
                    self._repository.update_twitch_live_viewer_stats(
                        account.account_id,
                        recent_avg_live_viewers=recent_avg_live_viewers,
                        recent_median_live_viewers=recent_median_live_viewers,
                    )
            elif isinstance(bundle.platform_profile, YouTubeChannelSeed):
                self._repository.upsert_youtube_channel_latest(
                    account.account_id, bundle.platform_profile
                )
            else:
                raise TypeError(
                    f"Unsupported platform payload for {platform!r}."
                )

            retained_content_samples = self._retained_content_samples(
                platform, bundle
            )
            facets = build_creator_profile_facets(
                platform,
                bundle.platform_profile,
                retained_content_samples,
            )
            self._repository.upsert_creator_profile_facets_latest(
                account.account_id,
                platform,
                facets,
            )
            self._repository.upsert_creator_games_played(
                account.account_id,
                platform,
                self._games_played_for_bundle(
                    platform,
                    facets_games_played=facets.games_played,
                    observed_games=bundle.observed_games,
                ),
            )
            if platform == "twitch" and bundle.observed_games:
                await self._hydrate_observed_twitch_games(
                    account.account_id,
                    bundle.observed_games,
                )
            content_samples_synced += self._repository.replace_content_samples(
                account.account_id,
                platform,
                retained_content_samples,
            )
            contact_points_synced += self._repository.upsert_contact_points(
                account.account_id,
                bundle.contact_points,
            )
            accounts_synced += 1
        return accounts_synced, content_samples_synced, contact_points_synced

    def _retained_content_samples(
        self, platform: str, bundle: AccountSeedBundle
    ) -> tuple[ContentSampleSeed, ...]:
        if platform != "twitch":
            return bundle.content_samples
        return tuple(
            sorted(
                bundle.content_samples,
                key=lambda sample: (
                    sample.position_rank,
                    sample.external_content_id,
                ),
            )[:_TWITCH_RETAINED_CONTENT_SAMPLE_LIMIT]
        )

    def _games_played_for_bundle(
        self,
        platform: str,
        *,
        facets_games_played: tuple[str, ...],
        observed_games: Sequence[ObservedGameSeed],
    ) -> tuple[str, ...]:
        if platform != "twitch":
            return facets_games_played
        deduped: dict[str, str] = {}
        for game_name in facets_games_played:
            normalized = game_name.strip().lower()
            if normalized and normalized not in deduped:
                deduped[normalized] = game_name.strip()
        for observed_game in observed_games:
            normalized = observed_game.game_name.strip().lower()
            if normalized and normalized not in deduped:
                deduped[normalized] = observed_game.game_name.strip()
        return tuple(deduped.values())

    async def _hydrate_observed_twitch_games(
        self,
        account_id: str,
        observed_games: Sequence[ObservedGameSeed],
    ) -> None:
        twitch_game_ids = tuple(
            {
                observed_game.platform_game_id
                for observed_game in observed_games
                if observed_game.platform_game_id
            }
        )
        if not twitch_game_ids:
            return

        resolved_games = await self._fetch_twitch_games_by_ids(twitch_game_ids)
        if not resolved_games:
            return

        igdb_repo = IGDBRepository(self._db_path)
        igdb_sync: IGDBSyncService | None = None

        game_name_to_igdb_id: dict[str, int] = {}
        for observed_game in observed_games:
            if not observed_game.platform_game_id:
                continue
            resolved = resolved_games.get(observed_game.platform_game_id)
            if resolved is None or resolved.igdb_game_id is None:
                continue
            raw_igdb_game_id = resolved.igdb_game_id.strip()
            if not raw_igdb_game_id:
                continue
            try:
                igdb_game_id = int(raw_igdb_game_id)
            except ValueError:
                log.warning(
                    "Ignoring Twitch game %s with invalid igdb_id=%r",
                    resolved.twitch_game_id,
                    resolved.igdb_game_id,
                )
                continue
            if igdb_repo.get(igdb_game_id) is None:
                if igdb_sync is None:
                    igdb_sync = IGDBSyncService(
                        db_path=self._db_path,
                        client_id=self._runtime.twitch_client_id,
                        client_secret=self._runtime.twitch_client_secret,
                    )
                await igdb_sync.fetch_game(igdb_game_id)
            game_name_to_igdb_id[observed_game.game_name] = igdb_game_id

        self._repository.tag_account_games_played_with_igdb_ids(
            account_id,
            game_name_to_igdb_id=game_name_to_igdb_id,
        )

    async def _fetch_twitch_games_by_ids(
        self, twitch_game_ids: Sequence[str]
    ) -> dict[str, TwitchGame]:
        if not twitch_game_ids:
            return {}
        client = TwitchStreamClient.from_runtime(self._runtime)
        page = await client.get_games(twitch_game_ids=twitch_game_ids)
        return {
            game.twitch_game_id: game
            for game in page.data
            if game.twitch_game_id
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _list_active_customer_games(self) -> list[CustomerGame]:
        return CustomerGameRepository(self._db_path).list_active()

    @staticmethod
    def _failed_platform_sync(
        platform: str, skipped_reason: str
    ) -> PlatformSyncSummary:
        return PlatformSyncSummary(
            platform=platform,
            accounts_synced=0,
            content_samples_synced=0,
            contact_points_synced=0,
            skipped_reason=skipped_reason,
        )

    @staticmethod
    def _summarize_customer_game_syncs(
        game_summaries: Sequence[CustomerGameSyncSummary],
    ) -> SweepSyncSummary:
        return SweepSyncSummary(
            games_seen=len(game_summaries),
            accounts_synced=sum(
                item.accounts_synced for item in game_summaries
            ),
            content_samples_synced=sum(
                item.content_samples_synced for item in game_summaries
            ),
            contact_points_synced=sum(
                item.contact_points_synced for item in game_summaries
            ),
        )
