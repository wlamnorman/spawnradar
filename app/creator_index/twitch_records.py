"""Twitch record dataclasses and parsers.

Extracted from ``app.creator_index.enrichment`` to allow independent reuse
of the data structures and their parsing logic.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from app.creator_index.adapters.common import as_list, optional_int

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TwitchUser:
    user_id: str
    login: str
    display_name: str
    description: str | None
    profile_image_url: str | None


@dataclass(frozen=True)
class TwitchStreamRecord:
    user_id: str
    game_id: str | None
    game_name: str | None
    title: str | None
    tags: tuple[str, ...]
    viewer_count: int | None
    language: str | None
    started_at: str | None


@dataclass(frozen=True)
class TwitchChannelInfoRecord:
    broadcaster_id: str
    broadcaster_language: str | None
    title: str | None
    game_id: str | None
    game_name: str | None
    tags: tuple[str, ...]


@dataclass(frozen=True)
class TwitchVideoRecord:
    video_id: str
    title: str
    description: str | None
    thumbnail_url: str | None
    created_at: str | None
    view_count: int | None
    url: str | None
    stream_id: str | None
    language: str | None
    game_id: str | None
    game_name: str | None
    video_type: str | None
    duration: str | None


@dataclass(frozen=True)
class TwitchClipRecord:
    clip_id: str
    broadcaster_id: str
    game_id: str
    title: str
    view_count: int | None
    created_at: str | None
    thumbnail_url: str | None
    url: str | None
    language: str | None


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def clean_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _tags(value: object) -> tuple[str, ...]:
    return tuple(
        item.strip()
        for item in as_list(value)
        if isinstance(item, str) and item.strip()
    )


def parse_user(item: Mapping[str, object]) -> TwitchUser | None:
    user_id = clean_str(item.get("id"))
    login = clean_str(item.get("login"))
    display_name = clean_str(item.get("display_name"))
    if user_id is None or login is None or display_name is None:
        return None
    return TwitchUser(
        user_id=user_id,
        login=login,
        display_name=display_name,
        description=clean_str(item.get("description")),
        profile_image_url=clean_str(item.get("profile_image_url")),
    )


def parse_stream_record(
    item: Mapping[str, object],
) -> TwitchStreamRecord | None:
    user_id = clean_str(item.get("user_id"))
    if user_id is None:
        return None
    return TwitchStreamRecord(
        user_id=user_id,
        game_id=clean_str(item.get("game_id")),
        game_name=clean_str(item.get("game_name")),
        title=clean_str(item.get("title")),
        tags=_tags(item.get("tags")),
        viewer_count=optional_int(item.get("viewer_count")),
        language=clean_str(item.get("language")),
        started_at=clean_str(item.get("started_at")),
    )


def parse_channel_info_record(
    item: Mapping[str, object],
) -> TwitchChannelInfoRecord | None:
    broadcaster_id = clean_str(item.get("broadcaster_id"))
    if broadcaster_id is None:
        return None
    return TwitchChannelInfoRecord(
        broadcaster_id=broadcaster_id,
        broadcaster_language=clean_str(item.get("broadcaster_language")),
        title=clean_str(item.get("title")),
        game_id=clean_str(item.get("game_id")),
        game_name=clean_str(item.get("game_name")),
        tags=_tags(item.get("tags")),
    )


def parse_video_record(
    item: Mapping[str, object],
) -> TwitchVideoRecord | None:
    video_id = clean_str(item.get("id"))
    title = clean_str(item.get("title"))
    if video_id is None or title is None:
        return None
    return TwitchVideoRecord(
        video_id=video_id,
        title=title,
        description=clean_str(item.get("description")),
        thumbnail_url=clean_str(item.get("thumbnail_url")),
        created_at=clean_str(item.get("created_at")),
        view_count=optional_int(item.get("view_count")),
        url=clean_str(item.get("url")),
        stream_id=clean_str(item.get("stream_id")),
        language=clean_str(item.get("language")),
        game_id=clean_str(item.get("game_id")),
        game_name=clean_str(item.get("game_name")),
        video_type=clean_str(item.get("type")),
        duration=clean_str(item.get("duration")),
    )


def parse_clip_record(
    item: Mapping[str, object],
) -> TwitchClipRecord | None:
    clip_id = clean_str(item.get("id"))
    game_id = clean_str(item.get("game_id"))
    title = clean_str(item.get("title"))
    broadcaster_id = clean_str(item.get("broadcaster_id"))
    if (
        clip_id is None
        or game_id is None
        or title is None
        or broadcaster_id is None
    ):
        return None
    return TwitchClipRecord(
        clip_id=clip_id,
        broadcaster_id=broadcaster_id,
        game_id=game_id,
        title=title,
        view_count=optional_int(item.get("view_count")),
        created_at=clean_str(item.get("created_at")),
        thumbnail_url=clean_str(item.get("thumbnail_url")),
        url=clean_str(item.get("url")),
        language=clean_str(item.get("language")),
    )
