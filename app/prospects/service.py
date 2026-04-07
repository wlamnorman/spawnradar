"""Prospect ranking service: score and rank creators for a CustomerGame."""

from __future__ import annotations

import logging
import time

from app.creator_index.matching import (
    customer_game_tag_counts,
    customer_game_tag_keys,
    tag_weight,
)
from app.games.models import CustomerGame
from app.prospects.models import (
    PROSPECT_WORKFLOW_STATUS_ORDER,
    ObservedTag,
    ProspectWorkflowState,
    ProspectWorkflowStatus,
    RankedProspect,
)
from app.prospects.repository import ProspectRepository

log = logging.getLogger(__name__)


class ProspectRankingService:
    """Rank content creators by coverage evidence for a customer game."""

    def __init__(self, db_path: str) -> None:
        self._repo = ProspectRepository(db_path)

    def rank_prospects(
        self,
        customer_game: CustomerGame,
        *,
        limit: int = 50,
        offset: int = 0,
        min_reach: int = 0,
        max_reach: int | None = None,
        min_relevant_games: int = 0,
        max_relevant_games: int | None = None,
        contact_methods: tuple[str, ...] = (),
        status_filter: str = "all",
    ) -> tuple[
        list[RankedProspect],
        int,
        dict[ProspectWorkflowStatus, int],
        int,  # reach_filter_max
        int,  # games_filter_max
    ]:
        """Return ranked creator prospects for one customer game.

        Uses a SQL-based scoring path that pushes coverage scoring,
        reach filtering, sorting, and pagination into a single query.
        Only the final page slice is hydrated with profiles, relevant
        games, and workflow state.
        """
        started_at = time.perf_counter()
        game_tags = customer_game_tag_keys(customer_game)
        if not game_tags:
            return (
                [],
                0,
                dict.fromkeys(PROSPECT_WORKFLOW_STATUS_ORDER, 0),
                0,
                0,
            )

        cg_tags = customer_game_tag_counts(customer_game)
        total_weight = sum(tag_weight(k) for k in cg_tags)

        (
            page_rows,
            total_count,
            reach_filter_max,
            games_filter_max,
            status_counts,
        ) = (
            self._repo.rank_scored_page(
                game_tags=game_tags,
                total_weight=total_weight,
                customer_game_id=customer_game.customer_game_id,
                min_reach=min_reach,
                max_reach=max_reach,
                min_relevant_games=min_relevant_games,
                max_relevant_games=max_relevant_games,
                contact_methods=contact_methods,
                status_filter=status_filter,
                limit=limit,
                offset=offset,
            )
        )
        elapsed_ms = (time.perf_counter() - started_at) * 1000

        if not page_rows:
            log.info(
                "[prospects] rank empty game_id=%s elapsed_ms=%.1f",
                customer_game.customer_game_id,
                elapsed_ms,
            )
            return (
                [],
                0,
                status_counts,
                reach_filter_max,
                games_filter_max,
            )

        page_ids = [r[0] for r in page_rows]

        # --- Hydrate page rows -----------------------------------------
        hydrate_started_at = time.perf_counter()
        profiles = self._repo.get_creator_profiles(page_ids)
        relevant_games = self._repo.get_relevant_games(
            page_ids,
            game_tags,
            per_account_limit=10,
        )
        relevant_game_counts = self._repo.count_relevant_games(
            page_ids,
            game_tags,
        )

        # Per-creator tag counts for the overlap-tag display
        page_tag_counts = self._repo.query_creator_tag_counts(
            game_tags=game_tags,
            account_ids=page_ids,
        )
        # Compute overlap tags per page creator
        overlap_tags_by_id: dict[str, tuple[tuple[str, int | str], ...]] = {}
        for account_id in page_ids:
            tc = page_tag_counts.get(account_id, {})
            overlap_tags_by_id[account_id] = tuple(
                sorted(
                    (k for k in cg_tags if k in tc),
                    key=lambda k: (k[0], str(k[1])),
                )
            )

        workflow_states = self._repo.get_prospect_workflow_states(
            customer_game_id=customer_game.customer_game_id,
            account_ids=page_ids,
        )
        hydrate_elapsed_ms = (time.perf_counter() - hydrate_started_at) * 1000

        results: list[RankedProspect] = []
        for account_id, coverage_score, _reach in page_rows:
            profile = profiles.get(account_id)
            if profile is None:
                continue
            tc = page_tag_counts.get(account_id, {})
            overlap = overlap_tags_by_id.get(account_id, ())
            results.append(
                RankedProspect(
                    profile=profile,
                    coverage_score=coverage_score,
                    overlap_tags=overlap,
                    observed_tags=tuple(
                        ObservedTag(
                            tag_type=tag_type,
                            tag_id=tag_id,
                            observed_game_count=tc.get((tag_type, tag_id), 0),
                        )
                        for tag_type, tag_id in overlap
                    ),
                    relevant_game_count=relevant_game_counts.get(
                        account_id, 0
                    ),
                    workflow=workflow_states.get(
                        account_id, ProspectWorkflowState()
                    ),
                    relevant_games=tuple(relevant_games.get(account_id, [])),
                )
            )

        log.info(
            "[prospects] rank complete game_id=%s total=%s page_size=%s sql_ms=%.1f hydrate_ms=%.1f total_ms=%.1f",
            customer_game.customer_game_id,
            total_count,
            len(results),
            elapsed_ms,
            hydrate_elapsed_ms,
            (time.perf_counter() - started_at) * 1000,
        )
        return (
            results,
            total_count,
            status_counts,
            reach_filter_max,
            games_filter_max,
        )

    def count_ranked_prospects(
        self,
        customer_game: CustomerGame,
        *,
        min_reach: int = 0,
        max_reach: int | None = None,
        min_relevant_games: int = 0,
        max_relevant_games: int | None = None,
        contact_methods: tuple[str, ...] = (),
        status_filter: str = "all",
    ) -> tuple[int, dict[ProspectWorkflowStatus, int]]:
        """Return filtered prospect counts without page-row hydration."""
        game_tags = customer_game_tag_keys(customer_game)
        if not game_tags:
            return 0, dict.fromkeys(PROSPECT_WORKFLOW_STATUS_ORDER, 0)

        cg_tags = customer_game_tag_counts(customer_game)
        total_weight = sum(tag_weight(k) for k in cg_tags)

        # Use limit=1 so the SQL returns at least one row with total_count.
        _page_rows, total_count, _reach_max, _games_max, status_counts = (
            self._repo.rank_scored_page(
                game_tags=game_tags,
                total_weight=total_weight,
                customer_game_id=customer_game.customer_game_id,
                min_reach=min_reach,
                max_reach=max_reach,
                min_relevant_games=min_relevant_games,
                max_relevant_games=max_relevant_games,
                contact_methods=contact_methods,
                status_filter=status_filter,
                limit=1,
                offset=0,
            )
        )
        return total_count, status_counts

    def update_prospect_workflow(
        self,
        customer_game: CustomerGame,
        *,
        account_id: str,
        status: ProspectWorkflowStatus,
        notes: str,
    ) -> ProspectWorkflowState:
        """Persist workflow state for one prospect on one customer game."""
        return self._repo.upsert_prospect_workflow_state(
            customer_game_id=customer_game.customer_game_id,
            account_id=account_id,
            status=status,
            notes=notes,
        )
