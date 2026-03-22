"""Games domain models."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.games.tags import TagProfile, WeightedTag
from app.ingestion.registry import DEFAULT_DISCOVERY_SOURCES, Source


@dataclass(frozen=True)
class Game:
    """A registered indie game with audience metadata."""

    game_id: str
    user_id: str
    name: str
    summary: str | None
    description: str
    genre_tags: list[str]  # deserialized from JSON column
    audience_tags: list[str]  # deserialized from JSON column
    platform_tags: list[str]  # deserialized from JSON column
    website_url: str | None
    status: str
    slug: str
    created_at: str
    updated_at: str
    genre_tag_profile: TagProfile = field(default_factory=TagProfile.empty)
    audience_tag_profile: TagProfile = field(default_factory=TagProfile.empty)
    mechanics_tag_profile: TagProfile = field(default_factory=TagProfile.empty)
    tone_tag_profile: TagProfile = field(default_factory=TagProfile.empty)
    discovery_schedule: str = "manual"
    discovery_sources: list[Source] = field(
        default_factory=lambda: list(DEFAULT_DISCOVERY_SOURCES)
    )

    @property
    def genre_primary_tags(self) -> list[str]:
        return list(self.genre_tag_profile.primary)

    @property
    def genre_secondary_tags(self) -> list[str]:
        return list(self.genre_tag_profile.secondary)

    @property
    def genre_custom_tags(self) -> list[str]:
        return list(self.genre_tag_profile.custom)

    @property
    def audience_primary_tags(self) -> list[str]:
        return list(self.audience_tag_profile.primary)

    @property
    def audience_secondary_tags(self) -> list[str]:
        return list(self.audience_tag_profile.secondary)

    @property
    def audience_custom_tags(self) -> list[str]:
        return list(self.audience_tag_profile.custom)

    @property
    def mechanics_primary_tags(self) -> list[str]:
        return list(self.mechanics_tag_profile.primary)

    @property
    def mechanics_secondary_tags(self) -> list[str]:
        return list(self.mechanics_tag_profile.secondary)

    @property
    def tone_primary_tags(self) -> list[str]:
        return list(self.tone_tag_profile.primary)

    @property
    def tone_secondary_tags(self) -> list[str]:
        return list(self.tone_tag_profile.secondary)

    def ordered_genre_tags(self) -> list[str]:
        if self.genre_tag_profile.all_tags:
            return self.genre_tag_profile.ordered_tags()
        return list(self.genre_tags)

    def ordered_audience_tags(self) -> list[str]:
        if self.audience_tag_profile.all_tags:
            return self.audience_tag_profile.ordered_tags()
        return list(self.audience_tags)

    def weighted_genre_tags(self) -> list[WeightedTag]:
        if self.genre_tag_profile.all_tags:
            return self.genre_tag_profile.weighted_tags()
        return [
            WeightedTag(name=tag, weight=1.0, label="primary")
            for tag in self.genre_tags
        ]

    def weighted_audience_tags(self) -> list[WeightedTag]:
        if self.audience_tag_profile.all_tags:
            return self.audience_tag_profile.weighted_tags()
        return [
            WeightedTag(name=tag, weight=1.0, label="primary")
            for tag in self.audience_tags
        ]

    def ordered_mechanics_tags(self) -> list[str]:
        return self.mechanics_tag_profile.ordered_tags()

    def ordered_tone_tags(self) -> list[str]:
        return self.tone_tag_profile.ordered_tags()

    def weighted_mechanics_tags(self) -> list[WeightedTag]:
        return self.mechanics_tag_profile.weighted_tags()

    def weighted_tone_tags(self) -> list[WeightedTag]:
        return self.tone_tag_profile.weighted_tags()


def _human_join(parts: tuple[str, ...]) -> str:
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return f"{', '.join(parts[:-1])}, and {parts[-1]}"


@dataclass(frozen=True)
class DiscoveryReadiness:
    """Whether a game has enough structured data for useful discovery."""

    can_run: bool
    missing_fields: tuple[str, ...] = ()

    @property
    def message(self) -> str:
        if self.can_run:
            return "Discovery ready."
        missing = _human_join(self.missing_fields)
        return f"Finish setup before running discovery. Missing {missing}."


@dataclass(frozen=True)
class Asset:
    """A promotional asset associated with a game (screenshot, blurb, etc.)."""

    asset_id: str
    game_id: str
    asset_type: str  # screenshot | banner | logo | blurb
    title: str
    body: str | None
    url: str | None
    created_at: str


@dataclass(frozen=True)
class MessageTemplate:
    """An outreach message template with variable placeholders.

    Supported placeholders: {{creator_name}}, {{game_name}}, {{fit_reason}}
    """

    template_id: str
    game_id: str
    name: str
    channel: str  # email | youtube_dm | twitch_dm | reddit_dm | twitter
    subject_template: str | None
    body_template: str
    created_at: str
    updated_at: str
