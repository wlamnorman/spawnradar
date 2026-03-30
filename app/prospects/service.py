"""Prospect ranking service: score and rank creators for a CustomerGame."""

from __future__ import annotations

from urllib.parse import urlparse

from app.creator_index.matching import (
    customer_game_tag_keys,
    match_creator_tags_to_game,
)
from app.games.models import CustomerGame
from app.prospects.models import (
    CreatorRankingProfile,
    ObservedTag,
    RankedProspect,
)
from app.prospects.repository import ProspectRepository


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
        unfiltered = (
            max_reach is None
            and min_overlap_score <= 0.0
            and max_overlap_score >= 1.0
            and min_relevant_games <= 0
            and max_relevant_games is None
            and not contact_methods
        )
        true_total_count = (
            self._repo.count_creators_with_overlap(
                game_tags=game_tags,
                min_reach=min_reach,
            )
            if unfiltered
            else None
        )

        # Fetch enough creators to cover the requested page.
        # Over-fetch substantially since scoring and filters remove some out.
        fetch_limit = max((offset + limit) * 4, 1000)
        if (
            min_reach > 0
            or max_reach is not None
            or min_overlap_score > 0.0
            or max_overlap_score < 1.0
            or min_relevant_games > 0
            or max_relevant_games is not None
            or bool(contact_methods)
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

        if not filtered_scored:
            return [], 0

        # Count relevant games per creator
        filtered_ids = [item[0] for item in filtered_scored]
        relevant_game_counts = self._repo.count_relevant_games(
            filtered_ids,
            game_tags,
        )

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
        total_count = (
            true_total_count
            if true_total_count is not None
            else len(filtered_scored)
        )
        if not filtered_scored:
            return [], 0

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
                    relevant_games=tuple(relevant_games.get(account_id, [])),
                )
            )
        return results, total_count
