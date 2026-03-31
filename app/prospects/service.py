"""Prospect ranking service: score and rank creators for a CustomerGame."""

from __future__ import annotations

import logging
import time
from urllib.parse import urlparse

from app.creator_index.matching import (
    TagCounts,
    customer_game_tag_keys,
    match_creator_tags_to_game,
)
from app.games.models import CustomerGame
from app.prospects.models import (
    PROSPECT_WORKFLOW_STATUS_ORDER,
    CreatorRankingProfile,
    ObservedTag,
    ProspectWorkflowState,
    ProspectWorkflowStatus,
    RankedProspect,
)
from app.prospects.repository import ProspectRepository

log = logging.getLogger(__name__)


def _social_link_matches(
    links: tuple[str, ...], *, domains: tuple[str, ...]
) -> bool:
    """Return whether any public social link matches one of the domains."""
    for link in links:
        try:
            hostname = (urlparse(link).hostname or "").casefold()
        except ValueError:
            continue
        if any(
            hostname == domain or hostname.endswith(f".{domain}")
            for domain in domains
        ):
            return True
    return False


def _profile_has_contact_method(
    profile: CreatorRankingProfile, contact_method: str
) -> bool:
    """Return whether a creator exposes the requested contact method."""
    if contact_method == "email":
        return bool(profile.contact_emails)
    if contact_method == "discord":
        return bool(profile.contact_discord_urls)
    if contact_method == "twitch":
        return (
            profile.platform == "twitch" and bool(profile.canonical_url)
        ) or _social_link_matches(
            profile.contact_social_links,
            domains=("twitch.tv",),
        )
    if contact_method == "youtube":
        return (
            profile.platform == "youtube" and bool(profile.canonical_url)
        ) or _social_link_matches(
            profile.contact_social_links,
            domains=("youtube.com", "youtu.be"),
        )
    if contact_method == "x":
        return _social_link_matches(
            profile.contact_social_links,
            domains=("x.com", "twitter.com"),
        )
    if contact_method == "instagram":
        return _social_link_matches(
            profile.contact_social_links,
            domains=("instagram.com",),
        )
    if contact_method == "tiktok":
        return _social_link_matches(
            profile.contact_social_links,
            domains=("tiktok.com",),
        )
    if contact_method == "bluesky":
        return _social_link_matches(
            profile.contact_social_links,
            domains=("bsky.app",),
        )
    return False


def _profile_has_any_contact_method(
    profile: CreatorRankingProfile, contact_methods: tuple[str, ...]
) -> bool:
    """Return whether a creator matches any selected contact method."""
    if not contact_methods:
        return True
    return any(
        _profile_has_contact_method(profile, contact_method)
        for contact_method in contact_methods
    )


class ProspectRankingService:
    """Rank content creators by coverage evidence for a customer game."""

    def __init__(self, db_path: str) -> None:
        self._repo = ProspectRepository(db_path)

    def count_prospects(
        self, customer_game: CustomerGame, *, min_reach: int = 0
    ) -> int:
        """Return the unfiltered count of creators with any positive overlap."""
        game_tags = customer_game_tag_keys(customer_game)
        if not game_tags:
            return 0
        return self._repo.count_creators_with_overlap(
            game_tags=game_tags,
            min_reach=min_reach,
        )

    def max_reach(
        self, customer_game: CustomerGame, *, min_reach: int = 0
    ) -> int:
        """Return the maximum reach among overlapping creators."""
        game_tags = customer_game_tag_keys(customer_game)
        if not game_tags:
            return 0
        return self._repo.max_reach_with_overlap(
            game_tags=game_tags,
            min_reach=min_reach,
        )

    def max_relevant_games(
        self, customer_game: CustomerGame, *, min_reach: int = 0
    ) -> int:
        """Return the maximum relevant-game count among overlapping creators."""
        game_tags = customer_game_tag_keys(customer_game)
        if not game_tags:
            return 0
        return self._repo.max_relevant_games_with_overlap(
            game_tags=game_tags,
            min_reach=min_reach,
        )

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
        min_relevant_games: int = 0,
        max_relevant_games: int | None = None,
        contact_methods: tuple[str, ...] = (),
        status_filter: str = "all",
    ) -> tuple[
        list[RankedProspect],
        int,
        dict[ProspectWorkflowStatus, int],
    ]:
        """Return ranked creator prospects for one customer game.

        Returns ``(prospects, total_count, status_counts)`` where *total_count*
        is the number of creators in the current status view and
        *status_counts* reflects the available workflow counts after the
        numeric/contact filters but before status pagination.

        1. Query per-creator tag counts from resolved game plays.
        2. Score each creator using coverage of the customer game's tags.
        3. Sort by (coverage, audience, reach) descending.
        4. Slice to the requested page and fetch display profiles.
        """
        started_at = time.perf_counter()
        fetch_limit = max((offset + limit) * 4, 5000)
        filtered = self._build_filtered_candidates(
            customer_game,
            min_reach=min_reach,
            max_reach=max_reach,
            min_overlap_score=min_overlap_score,
            max_overlap_score=max_overlap_score,
            min_relevant_games=min_relevant_games,
            max_relevant_games=max_relevant_games,
            contact_methods=contact_methods,
            status_filter=status_filter,
            fetch_limit=fetch_limit,
        )
        if filtered is None:
            log.info(
                "[prospects] rank empty game_id=%s fetch_limit=%s elapsed_ms=%.1f",
                customer_game.customer_game_id,
                fetch_limit,
                (time.perf_counter() - started_at) * 1000,
            )
            return (
                [],
                0,
                dict.fromkeys(PROSPECT_WORKFLOW_STATUS_ORDER, 0),
            )

        filtered_scored = filtered.filtered_scored
        creator_tag_counts = filtered.creator_tag_counts
        profiles = filtered.profiles
        relevant_game_counts = filtered.relevant_game_counts
        workflow_states = filtered.workflow_states
        status_counts = filtered.status_counts
        total_count = len(filtered_scored)
        if not filtered_scored:
            return [], 0, status_counts

        # Paginate
        page_slice = filtered_scored[offset : offset + limit]
        page_ids = [s[0] for s in page_slice]

        # Fetch relevant games with covers for this page only
        relevant_games = self._repo.get_relevant_games(
            page_ids,
            filtered.game_tags,
            per_account_limit=10,
        )
        hydration_elapsed_ms = (
            time.perf_counter() - filtered.post_filter_started_at
        ) * 1000

        results: list[RankedProspect] = []
        for account_id, score, overlap_tags in page_slice:
            profile = profiles.get(account_id)
            if profile is None:
                continue
            tag_counts = creator_tag_counts.get(account_id, {})
            results.append(
                RankedProspect(
                    profile=profile,
                    coverage_score=score,
                    overlap_tags=overlap_tags,
                    observed_tags=tuple(
                        ObservedTag(
                            tag_type=tag_type,
                            tag_id=tag_id,
                            observed_game_count=tag_counts.get(
                                (tag_type, tag_id), 0
                            ),
                        )
                        for tag_type, tag_id in overlap_tags
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
            "[prospects] rank complete game_id=%s fetch_limit=%s scored=%s filtered=%s page_size=%s total=%s candidate_ms=%.1f profile_ms=%.1f relevant_count_ms=%.1f workflow_ms=%.1f hydration_ms=%.1f total_ms=%.1f",
            customer_game.customer_game_id,
            fetch_limit,
            filtered.scored_count,
            filtered.pre_status_filtered_count,
            len(results),
            total_count,
            filtered.creator_tag_query_elapsed_ms,
            filtered.profile_query_elapsed_ms,
            filtered.relevant_game_count_elapsed_ms,
            filtered.workflow_state_elapsed_ms,
            hydration_elapsed_ms,
            (time.perf_counter() - started_at) * 1000,
        )
        return results, total_count, status_counts

    def count_ranked_prospects(
        self,
        customer_game: CustomerGame,
        *,
        min_reach: int = 0,
        max_reach: int | None = None,
        min_overlap_score: float = 0.0,
        max_overlap_score: float = 1.0,
        min_relevant_games: int = 0,
        max_relevant_games: int | None = None,
        contact_methods: tuple[str, ...] = (),
        status_filter: str = "all",
        fetch_limit: int = 5000,
    ) -> tuple[int, dict[ProspectWorkflowStatus, int]]:
        """Return filtered prospect counts without page-row hydration."""
        started_at = time.perf_counter()
        filtered = self._build_filtered_candidates(
            customer_game,
            min_reach=min_reach,
            max_reach=max_reach,
            min_overlap_score=min_overlap_score,
            max_overlap_score=max_overlap_score,
            min_relevant_games=min_relevant_games,
            max_relevant_games=max_relevant_games,
            contact_methods=contact_methods,
            status_filter=status_filter,
            fetch_limit=fetch_limit,
        )
        if filtered is None:
            log.info(
                "[prospects] count empty game_id=%s fetch_limit=%s elapsed_ms=%.1f",
                customer_game.customer_game_id,
                fetch_limit,
                (time.perf_counter() - started_at) * 1000,
            )
            return 0, dict.fromkeys(PROSPECT_WORKFLOW_STATUS_ORDER, 0)
        log.info(
            "[prospects] count complete game_id=%s fetch_limit=%s scored=%s filtered=%s total=%s candidate_ms=%.1f profile_ms=%.1f relevant_count_ms=%.1f workflow_ms=%.1f total_ms=%.1f",
            customer_game.customer_game_id,
            fetch_limit,
            filtered.scored_count,
            filtered.pre_status_filtered_count,
            len(filtered.filtered_scored),
            filtered.creator_tag_query_elapsed_ms,
            filtered.profile_query_elapsed_ms,
            filtered.relevant_game_count_elapsed_ms,
            filtered.workflow_state_elapsed_ms,
            (time.perf_counter() - started_at) * 1000,
        )
        return len(filtered.filtered_scored), filtered.status_counts

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

    def _build_filtered_candidates(
        self,
        customer_game: CustomerGame,
        *,
        min_reach: int,
        max_reach: int | None,
        min_overlap_score: float,
        max_overlap_score: float,
        min_relevant_games: int,
        max_relevant_games: int | None,
        contact_methods: tuple[str, ...],
        status_filter: str,
        fetch_limit: int,
    ) -> _FilteredCandidates | None:
        """Build the filtered candidate set shared by page and workflow paths."""
        query_started_at = time.perf_counter()
        game_tags = customer_game_tag_keys(customer_game)
        if not game_tags:
            return None

        creator_tag_counts = self._repo.query_creator_tag_counts(
            game_tags=game_tags,
            limit=fetch_limit,
        )
        creator_tag_query_elapsed_ms = (
            time.perf_counter() - query_started_at
        ) * 1000
        if not creator_tag_counts:
            return None

        score_started_at = time.perf_counter()
        scored: list[tuple[str, float, tuple[tuple[str, int | str], ...]]] = []
        for account_id, tag_counts in creator_tag_counts.items():
            match = match_creator_tags_to_game(
                customer_game, creator_tag_counts=tag_counts
            )
            if match.coverage_score > 0:
                scored.append(
                    (account_id, match.coverage_score, match.overlap_tags)
                )

        scored_ids = [account_id for account_id, _, _ in scored]
        profile_started_at = time.perf_counter()
        profiles = self._repo.get_creator_profiles(scored_ids)
        profile_query_elapsed_ms = (
            time.perf_counter() - profile_started_at
        ) * 1000

        filtered_scored = [
            item
            for item in scored
            if item[1] >= min_overlap_score
            and item[1] <= max_overlap_score
            and profiles.get(item[0]) is not None
            and profiles[item[0]].reach >= min_reach
            and (max_reach is None or profiles[item[0]].reach <= max_reach)
        ]
        if not filtered_scored:
            return None

        filtered_ids = [account_id for account_id, _, _ in filtered_scored]
        relevant_count_started_at = time.perf_counter()
        relevant_game_counts = self._repo.count_relevant_games(
            filtered_ids,
            game_tags,
        )
        relevant_game_count_elapsed_ms = (
            time.perf_counter() - relevant_count_started_at
        ) * 1000

        filtered_scored = [
            item
            for item in filtered_scored
            if relevant_game_counts.get(item[0], 0) >= min_relevant_games
            and (
                max_relevant_games is None
                or relevant_game_counts.get(item[0], 0) <= max_relevant_games
            )
            and _profile_has_any_contact_method(
                profiles[item[0]], contact_methods
            )
        ]
        if not filtered_scored:
            return None

        filtered_ids = [account_id for account_id, _, _ in filtered_scored]
        workflow_started_at = time.perf_counter()
        workflow_states = self._repo.get_prospect_workflow_states(
            customer_game_id=customer_game.customer_game_id,
            account_ids=filtered_ids,
        )
        workflow_state_elapsed_ms = (
            time.perf_counter() - workflow_started_at
        ) * 1000
        status_counts = dict.fromkeys(PROSPECT_WORKFLOW_STATUS_ORDER, 0)
        for account_id in filtered_ids:
            workflow_status = workflow_states.get(
                account_id, ProspectWorkflowState()
            ).status
            status_counts[workflow_status] += 1

        if status_filter == "all":
            filtered_scored = [
                item
                for item in filtered_scored
                if workflow_states.get(item[0], ProspectWorkflowState()).status
                != "not_pursuing"
            ]
        else:
            filtered_scored = [
                item
                for item in filtered_scored
                if workflow_states.get(item[0], ProspectWorkflowState()).status
                == status_filter
            ]

        filtered_scored.sort(
            key=lambda item: (
                item[1],
                profiles[item[0]].reach if item[0] in profiles else 0,
                item[0],
            ),
            reverse=True,
        )
        return _FilteredCandidates(
            game_tags=game_tags,
            creator_tag_counts=creator_tag_counts,
            filtered_scored=filtered_scored,
            profiles=profiles,
            relevant_game_counts=relevant_game_counts,
            workflow_states=workflow_states,
            status_counts=status_counts,
            scored_count=len(scored),
            pre_status_filtered_count=len(filtered_ids),
            creator_tag_query_elapsed_ms=creator_tag_query_elapsed_ms,
            profile_query_elapsed_ms=profile_query_elapsed_ms,
            relevant_game_count_elapsed_ms=relevant_game_count_elapsed_ms,
            workflow_state_elapsed_ms=workflow_state_elapsed_ms,
            post_filter_started_at=score_started_at,
        )


class _FilteredCandidates:
    """Internal shared result for filtered prospect candidates."""

    def __init__(
        self,
        *,
        game_tags: tuple[tuple[str, int | str], ...],
        creator_tag_counts: dict[str, TagCounts],
        filtered_scored: list[
            tuple[str, float, tuple[tuple[str, int | str], ...]]
        ],
        profiles: dict[str, CreatorRankingProfile],
        relevant_game_counts: dict[str, int],
        workflow_states: dict[str, ProspectWorkflowState],
        status_counts: dict[ProspectWorkflowStatus, int],
        scored_count: int,
        pre_status_filtered_count: int,
        creator_tag_query_elapsed_ms: float,
        profile_query_elapsed_ms: float,
        relevant_game_count_elapsed_ms: float,
        workflow_state_elapsed_ms: float,
        post_filter_started_at: float,
    ) -> None:
        self.game_tags = game_tags
        self.creator_tag_counts = creator_tag_counts
        self.filtered_scored = filtered_scored
        self.profiles = profiles
        self.relevant_game_counts = relevant_game_counts
        self.workflow_states = workflow_states
        self.status_counts = status_counts
        self.scored_count = scored_count
        self.pre_status_filtered_count = pre_status_filtered_count
        self.creator_tag_query_elapsed_ms = creator_tag_query_elapsed_ms
        self.profile_query_elapsed_ms = profile_query_elapsed_ms
        self.relevant_game_count_elapsed_ms = relevant_game_count_elapsed_ms
        self.workflow_state_elapsed_ms = workflow_state_elapsed_ms
        self.post_filter_started_at = post_filter_started_at
