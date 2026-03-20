"""Games domain models."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.ingestion.registry import DEFAULT_DISCOVERY_SOURCES, Source


@dataclass(frozen=True)
class Game:
    """A registered indie game with audience metadata."""

    game_id: str
    user_id: str
    name: str
    description: str
    genre_tags: list[str]  # deserialized from JSON column
    audience_tags: list[str]  # deserialized from JSON column
    platform_tags: list[str]  # deserialized from JSON column
    website_url: str | None
    status: str
    slug: str
    created_at: str
    updated_at: str
    discovery_schedule: str = "manual"
    discovery_sources: list[Source] = field(
        default_factory=lambda: list(DEFAULT_DISCOVERY_SOURCES)
    )


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
    channel: str  # email | youtube_dm | reddit_dm | twitter
    subject_template: str | None
    body_template: str
    created_at: str
    updated_at: str
