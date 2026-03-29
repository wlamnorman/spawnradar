"""Prospect ranking service: score and rank creators for a CustomerGame."""

from __future__ import annotations

from app.creator_index.matching import (
    customer_game_tag_keys,
    match_creator_tags_to_game,
)
from app.games.models import CustomerGame
from app.prospects.models import RankedProspect
from app.prospects.repository import ProspectRepository


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
        min_overlap_score: float = 0.0,
        max_overlap_score: float = 1.0,
    ) -> tuple[list[RankedProspect], int]:
        """Return ranked creator prospects for one customer game.

        Returns ``(prospects, total_count)`` where *total_count* is the
        number of creators with coverage > 0 (before pagination).

        1. Query per-creator tag counts from resolved game plays.
        2. Score each creator using coverage of the customer game's tags.
        3. Sort by (coverage, audience, reach) descending.
        4. Slice to the requested page and fetch display profiles.
        """
        game_tags = customer_game_tag_keys(customer_game)
        if not game_tags:
            return [], 0

        # Fetch enough creators to cover the requested page.
        # Over-fetch substantially since scoring and filters remove some out.
        fetch_limit = max((offset + limit) * 4, 1000)
        if (
            min_reach > 0
            or max_reach is not None
            or min_overlap_score > 0.0
            or max_overlap_score < 1.0
        ):
            fetch_limit = max(fetch_limit, 5000)
        creator_tag_counts = self._repo.query_creator_tag_counts(
            game_tags=game_tags,
            limit=fetch_limit,
        )
        if not creator_tag_counts:
            return [], 0

        # Score each creator
        scored: list[tuple[str, float, tuple[tuple[str, int | str], ...]]] = []
        for account_id, tag_counts in creator_tag_counts.items():
            match = match_creator_tags_to_game(
                customer_game, creator_tag_counts=tag_counts
            )
            if match.coverage_score > 0:
                scored.append(
                    (account_id, match.coverage_score, match.overlap_tags)
                )

        # Fetch profiles for all scored creators (need audience/reach for sort)
        scored_ids = [s[0] for s in scored]
        profiles = self._repo.get_creator_profiles(scored_ids)

        filtered_scored = [
            item
            for item in scored
            if item[1] >= min_overlap_score
            and item[1] <= max_overlap_score
            and profiles.get(item[0], None) is not None
            and profiles[item[0]].reach >= min_reach
            and (max_reach is None or profiles[item[0]].reach <= max_reach)
        ]

        total_count = len(filtered_scored)
        if not filtered_scored:
            return [], 0

        # Count relevant games per creator
        filtered_ids = [item[0] for item in filtered_scored]
        relevant_game_counts = self._repo.count_relevant_games(
            filtered_ids,
            game_tags,
        )

        # Sort by score, then reach. account_id as deterministic tiebreaker
        # so pagination is stable across requests.
        filtered_scored.sort(
            key=lambda item: (
                item[1],
                profiles[item[0]].reach if item[0] in profiles else 0,
                item[0],
            ),
            reverse=True,
        )

        # Paginate
        page_slice = filtered_scored[offset : offset + limit]
        page_ids = [s[0] for s in page_slice]

        # Fetch relevant games with covers for this page only
        relevant_games = self._repo.get_relevant_games(page_ids, game_tags)

        results: list[RankedProspect] = []
        for account_id, score, overlap_tags in page_slice:
            profile = profiles.get(account_id)
            if profile is None:
                continue
            results.append(
                RankedProspect(
                    profile=profile,
                    coverage_score=score,
                    overlap_tags=overlap_tags,
                    relevant_game_count=relevant_game_counts.get(
                        account_id, 0
                    ),
                    relevant_games=tuple(relevant_games.get(account_id, [])),
                )
            )
        return results, total_count
