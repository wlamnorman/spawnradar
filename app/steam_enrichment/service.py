"""Background Steam enrichment for cached IGDB games."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from app.database import get_connection
from app.steam_enrichment.client import SteamStoreClient
from app.steam_enrichment.models import (
    SteamBackfillCandidate,
    SteamEnrichmentResult,
    SteamStoreGame,
)
from app.steam_enrichment.repository import SteamEnrichmentRepository
from app.steam_enrichment.resolver import (
    parse_release_year,
    resolve_steam_candidate,
)
from app.steam_enrichment.tag_mapping import (
    map_steam_terms_to_canonical_tags,
    normalize_steam_label,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SteamBackfillSummary:
    attempted: int
    linked: int
    no_match: int
    errored: int


class SteamTagEnrichmentService:
    """Resolve and enrich cached IGDB games with Steam store tags."""

    def __init__(
        self,
        *,
        db_path: str,
        repository: SteamEnrichmentRepository | None = None,
        client: SteamStoreClient | None = None,
    ) -> None:
        self._db_path = db_path
        self._repository = repository or SteamEnrichmentRepository(db_path)
        self._client = client or SteamStoreClient()

    def mark_pending(self, igdb_id: int) -> None:
        self._repository.mark_pending(igdb_id)

    def load_backfill_candidates(
        self, *, limit: int, include_no_match: bool = False
    ) -> list[SteamBackfillCandidate]:
        return self._repository.load_backfill_candidates(
            limit=limit,
            include_no_match=include_no_match,
        )

    async def backfill(
        self, *, limit: int = 25, include_no_match: bool = False
    ) -> SteamBackfillSummary:
        attempted = 0
        linked = 0
        no_match = 0
        errored = 0
        for candidate in self.load_backfill_candidates(
            limit=limit,
            include_no_match=include_no_match,
        ):
            attempted += 1
            result = await self.enrich_igdb_game(candidate.igdb_id)
            if result.status == "linked":
                linked += 1
            elif result.status == "no_match":
                no_match += 1
            else:
                errored += 1
        return SteamBackfillSummary(
            attempted=attempted,
            linked=linked,
            no_match=no_match,
            errored=errored,
        )

    async def enrich_igdb_game(self, igdb_id: int) -> SteamEnrichmentResult:
        candidate = self._load_backfill_candidate(igdb_id)
        if candidate is None:
            raise ValueError(f"Unknown igdb_id={igdb_id}")

        log.debug(
            "[steam-enrichment] Starting igdb_id=%s name=%r",
            igdb_id,
            candidate.name,
        )
        local_tag_keys = self._repository.local_tag_keys_for(igdb_id)
        try:
            search_candidates = await self._client.search_candidates(
                candidate.name
            )
            log.debug(
                "[steam-enrichment] Search returned %d candidates for igdb_id=%s name=%r",
                len(search_candidates),
                igdb_id,
                candidate.name,
            )
            if not search_candidates:
                self._repository.mark_no_match(igdb_id, "no_candidates")
                log.info(
                    "[steam-enrichment] No Steam candidates for igdb_id=%s name=%r",
                    igdb_id,
                    candidate.name,
                )
                return SteamEnrichmentResult(
                    igdb_id=igdb_id,
                    status="no_match",
                    rejection_reason="no_candidates",
                )

            store_candidates: list[SteamStoreGame] = []
            mapped_keys_by_app_id: dict[int, set[tuple[str, str]]] = {}
            mapped_tags_by_app_id = {}
            for search_candidate in search_candidates[:5]:
                store_game = await self._client.fetch_store_game(
                    search_candidate.app_id
                )
                log.debug(
                    "[steam-enrichment] Fetched Steam app_id=%s name=%r raw_tags=%d api_genres=%d api_categories=%d",
                    store_game.app_id,
                    store_game.name,
                    len(store_game.raw_tags),
                    len(store_game.api_genre_labels),
                    len(store_game.api_category_labels),
                )
                store_candidates.append(store_game)
                text_blobs = [
                    text
                    for text in (
                        candidate.summary,
                        store_game.short_description,
                        store_game.detailed_description,
                    )
                    if text
                ]
                mapped_tags = tuple(
                    map_steam_terms_to_canonical_tags(
                        api_genre_labels=list(store_game.api_genre_labels),
                        api_category_labels=list(
                            store_game.api_category_labels
                        ),
                        raw_tags=list(store_game.raw_tags),
                        text_blobs=text_blobs,
                    )
                )
                mapped_tags_by_app_id[store_game.app_id] = mapped_tags
                mapped_keys_by_app_id[store_game.app_id] = {
                    (entry.tag_type, str(entry.tag_id))
                    for entry in mapped_tags
                }
                log.debug(
                    "[steam-enrichment] Candidate app_id=%s produced %d mapped tags",
                    store_game.app_id,
                    len(mapped_tags),
                )

            resolution = resolve_steam_candidate(
                igdb_id=igdb_id,
                igdb_name=candidate.name,
                igdb_developers=candidate.developer_names,
                igdb_release_year=parse_release_year(
                    candidate.first_release_date
                ),
                local_tag_keys=local_tag_keys,
                candidates=store_candidates,
                candidate_mapped_tag_keys=mapped_keys_by_app_id,
            )
            if (
                resolution.accepted_link is None
                or resolution.accepted_candidate is None
            ):
                reason = resolution.rejection_reason or "unresolved"
                self._repository.mark_no_match(igdb_id, reason)
                top_score = (
                    f"{resolution.evaluations[0].score:.2f}"
                    if resolution.evaluations
                    else "n/a"
                )
                log.info(
                    "[steam-enrichment] No match for igdb_id=%s name=%r reason=%s candidates=%d top_score=%s",
                    igdb_id,
                    candidate.name,
                    reason,
                    len(store_candidates),
                    top_score,
                )
                return SteamEnrichmentResult(
                    igdb_id=igdb_id,
                    status="no_match",
                    rejection_reason=reason,
                )

            accepted_candidate = resolution.accepted_candidate
            raw_tags = tuple(accepted_candidate.raw_tags)
            normalized_tags = tuple(
                normalize_steam_label(tag)
                for tag in accepted_candidate.raw_tags
            )
            mapped_tags = mapped_tags_by_app_id[accepted_candidate.app_id]
            self._repository.replace_enrichment(
                link=resolution.accepted_link,
                raw_tags=raw_tags,
                normalized_tags=normalized_tags,
                mapped_tags=mapped_tags,
            )
            log.info(
                "[steam-enrichment] Linked igdb_id=%s name=%r steam_app_id=%s method=%s raw_tags=%d mapped_tags=%d",
                igdb_id,
                candidate.name,
                resolution.accepted_link.steam_app_id,
                resolution.accepted_link.match_method,
                len(raw_tags),
                len(mapped_tags),
            )
            return SteamEnrichmentResult(
                igdb_id=igdb_id,
                status="linked",
                resolved_link=resolution.accepted_link,
                raw_tags=raw_tags,
                mapped_tags=mapped_tags,
            )
        except Exception as exc:
            self._repository.mark_error(igdb_id, str(exc))
            log.exception(
                "[steam-enrichment] Error enriching igdb_id=%s name=%r",
                igdb_id,
                candidate.name,
            )
            return SteamEnrichmentResult(
                igdb_id=igdb_id,
                status="error",
                errors=(str(exc),),
            )

    def _load_backfill_candidate(
        self, igdb_id: int
    ) -> SteamBackfillCandidate | None:
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                """
                SELECT
                    igdb_id,
                    name,
                    slug,
                    summary,
                    first_release_date,
                    developer_names_json
                FROM igdb_games
                WHERE igdb_id = ?
                """,
                (igdb_id,),
            ).fetchone()
        if row is None:
            return None
        return SteamBackfillCandidate(
            igdb_id=int(row["igdb_id"]),
            name=str(row["name"]),
            slug=str(row["slug"]),
            summary=str(row["summary"])
            if row["summary"] is not None
            else None,
            first_release_date=row["first_release_date"],
            developer_names=tuple(
                str(name)
                for name in json.loads(row["developer_names_json"] or "[]")
            ),
        )
