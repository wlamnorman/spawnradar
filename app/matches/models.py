"""Domain models for ranked creator matches."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

type MatchWorkflowStatus = Literal[
    "suggested",
    "to_contact",
    "contacted",
    "replied",
    "to_cover",
    "covered",
    "not_pursuing",
]

MATCH_WORKFLOW_STATUS_ORDER: tuple[MatchWorkflowStatus, ...] = (
    "suggested",
    "to_contact",
    "contacted",
    "replied",
    "to_cover",
    "covered",
    "not_pursuing",
)

MATCH_DEFAULT_STATUS: MatchWorkflowStatus = "suggested"

MATCH_WORKFLOW_STATUS_LABELS: dict[MatchWorkflowStatus, str] = {
    "suggested": "Suggested",
    "to_contact": "To Contact",
    "contacted": "Contacted",
    "replied": "Replied",
    "to_cover": "To Cover",
    "covered": "Covered",
    "not_pursuing": "Not Pursuing",
}


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
    """A surfaced played game for one creator match row."""

    name: str
    cover_url: str | None
    is_similar: bool = False


@dataclass(frozen=True)
class ObservedTag:
    """One overlapping tag plus the number of distinct played games behind it."""

    tag_type: str
    tag_id: int | str
    observed_game_count: int


@dataclass(frozen=True)
class MatchWorkflowState:
    """Customer-managed workflow state for a match."""

    status: MatchWorkflowStatus = MATCH_DEFAULT_STATUS
    notes: str = ""
    updated_at: str | None = None

    @property
    def has_notes(self) -> bool:
        return bool(self.notes.strip())


@dataclass(frozen=True)
class RankedMatch:
    """One scored creator for a CustomerGame."""

    profile: CreatorRankingProfile
    coverage_score: float
    overlap_tags: tuple[tuple[str, int | str], ...]
    observed_tags: tuple[ObservedTag, ...]
    relevant_game_count: int
    workflow: MatchWorkflowState = field(default_factory=MatchWorkflowState)
    relevant_games: tuple[RelevantGame, ...] = ()
