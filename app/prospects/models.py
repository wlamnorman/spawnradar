"""Domain models for ranked creator prospects."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

type ProspectWorkflowStatus = Literal[
    "new",
    "contacted",
    "replied",
    "access_shared",
    "covered",
    "not_pursuing",
]

PROSPECT_WORKFLOW_STATUS_ORDER: tuple[ProspectWorkflowStatus, ...] = (
    "new",
    "contacted",
    "replied",
    "access_shared",
    "covered",
    "not_pursuing",
)

PROSPECT_DEFAULT_STATUS: ProspectWorkflowStatus = "new"

PROSPECT_WORKFLOW_STATUS_LABELS: dict[ProspectWorkflowStatus, str] = {
    "new": "New",
    "contacted": "Contacted",
    "replied": "Replied",
    "access_shared": "Access Shared",
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
class CreatorRankingFilterProfile:
    """Lightweight profile data used only for ranking/filtering."""

    account_id: str
    platform: str
    canonical_url: str | None
    recent_audience: int
    reach: int
    contact_emails: tuple[str, ...] = ()
    contact_discord_urls: tuple[str, ...] = ()
    contact_social_links: tuple[str, ...] = ()


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
class ProspectWorkflowState:
    """Customer-managed workflow state for a prospect."""

    status: ProspectWorkflowStatus = PROSPECT_DEFAULT_STATUS
    notes: str = ""
    updated_at: str | None = None

    @property
    def has_notes(self) -> bool:
        return bool(self.notes.strip())


@dataclass(frozen=True)
class RankedProspect:
    """One scored creator for a CustomerGame."""

    profile: CreatorRankingProfile
    coverage_score: float
    overlap_tags: tuple[tuple[str, int | str], ...]
    observed_tags: tuple[ObservedTag, ...]
    relevant_game_count: int
    workflow: ProspectWorkflowState = field(
        default_factory=ProspectWorkflowState
    )
    relevant_games: tuple[RelevantGame, ...] = ()
