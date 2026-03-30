"""Domain models for ranked creator prospects."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CreatorRankingProfile:
    """Display-ready profile data for one creator."""

    account_id: str
    platform: str
    display_name: str
    handle: str | None
    canonical_url: str | None
    avatar_url: str | None
    summary_text: str | None
    recent_audience: int
    reach: int
    contact_emails: tuple[str, ...]
    contact_discord_urls: tuple[str, ...]
    contact_social_links: tuple[str, ...]


@dataclass(frozen=True)
class RelevantGame:
    """A game this creator plays that overlaps with the customer game."""

    name: str
    cover_url: str | None


@dataclass(frozen=True)
class ObservedTag:
    """One overlapping tag plus the number of distinct played games behind it."""

    tag_type: str
    tag_id: int | str
    observed_game_count: int


@dataclass(frozen=True)
class RankedProspect:
    """One scored creator for a CustomerGame."""

    profile: CreatorRankingProfile
    coverage_score: float
    overlap_tags: tuple[tuple[str, int | str], ...]
    observed_tags: tuple[ObservedTag, ...]
    relevant_game_count: int
    relevant_games: tuple[RelevantGame, ...] = ()

    @property
    def overlap_score(self) -> float:
        """Backward-compatible alias while callers migrate."""
        return self.coverage_score
