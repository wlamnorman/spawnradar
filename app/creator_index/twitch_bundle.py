"""Twitch bundle assembly helpers.

Extracted from ``app.creator_index.enrichment`` to allow independent reuse
of the bundle construction logic without the full enrichment client.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from app.creator_index.adapters.base import (
    AccountSeedBundle,
    ContactPointSeed,
    ContactType,
    ContentSampleSeed,
    ObservedGameSeed,
    SourceAccountSeed,
    TwitchProfileSeed,
)
from app.creator_index.adapters.common import (
    collect_text_contacts,
    count_recent_timestamps,
    mean_int,
    median_int,
)
from app.creator_index.twitch_records import (
    TwitchChannelInfoRecord,
    TwitchClipRecord,
    TwitchStreamRecord,
    TwitchUser,
    TwitchVideoRecord,
)

_MAX_CONTENT_SAMPLES_PER_ACCOUNT = 5


# ---------------------------------------------------------------------------
# Standalone helpers
# ---------------------------------------------------------------------------


_SOCIAL_LINK_DOMAINS = (
    "twitter.com/",
    "x.com/",
    "instagram.com/",
    "tiktok.com/",
    "bsky.app/",
    "youtube.com/",
    "youtu.be/",
)


def extract_panel_contacts(
    panels: Sequence[dict],
    login: str,
    seen_emails: set[str],
    seen_discord: set[str],
) -> list[ContactPointSeed]:
    """Extract email, Discord and social-link contact points from GQL panel data.

    Mutates *seen_emails* and *seen_discord* for cumulative deduplication
    across all contact sources in the bundle.
    """
    contacts: list[ContactPointSeed] = []
    source_url = f"https://www.twitch.tv/{login}"
    seen_socials: set[str] = set()

    for panel in panels:
        if not isinstance(panel, dict):
            continue

        description = panel.get("description") or ""
        link_url = panel.get("linkURL") or ""
        combined_text = f"{description} {link_url}"

        contacts.extend(
            collect_text_contacts(
                combined_text,
                source_kind="channel_panel",
                source_url=source_url,
                seen_emails=seen_emails,
                seen_discord=seen_discord,
            )
        )

        # Persist social links (X/Twitter, Instagram, Bluesky, YouTube)
        if link_url:
            link_lower = link_url.lower()
            if (
                any(d in link_lower for d in _SOCIAL_LINK_DOMAINS)
                and link_lower not in seen_socials
            ):
                seen_socials.add(link_lower)
                contacts.append(
                    ContactPointSeed(
                        contact_type=ContactType.SOCIAL_LINK,
                        contact_value=link_url,
                        source_kind="channel_social",
                        source_url=source_url,
                    )
                )
    return contacts


def _video_to_sample(
    *,
    video: TwitchVideoRecord,
    position_rank: int,
    fetched_at: str,
    expires_at: str,
) -> ContentSampleSeed | None:
    video_id = video.video_id
    title = video.title
    if not video_id or not title:
        return None
    return ContentSampleSeed(
        external_content_id=video_id,
        content_type="vod",
        title_or_text=title,
        body_text=video.description,
        url=video.url or f"https://www.twitch.tv/videos/{video_id}",
        thumbnail_url=video.thumbnail_url,
        published_at=video.created_at,
        engagement_count=video.view_count,
        language=video.language,
        position_rank=position_rank,
        fetched_at=fetched_at,
        expires_at=expires_at,
    )


def infer_account_type(
    description: str | None, title: str | None, tags: Sequence[str]
) -> str:
    haystack = " ".join(
        part for part in [description or "", title or "", *tags] if part
    ).lower()
    if any(
        marker in haystack
        for marker in ("developer", "devlog", "gamedev", "indiedev")
    ):
        return "developer"
    return "creator"


def _append_observed_game(
    games_played: list[str],
    observed_games: list[ObservedGameSeed],
    *,
    game_name: str | None,
    game_id: str | None,
) -> None:
    if not game_name:
        return
    game_name_key = game_name.strip().lower()
    if not game_name_key:
        return
    if game_name_key not in {existing.lower() for existing in games_played}:
        games_played.append(game_name)
    if any(
        existing.game_name.strip().lower() == game_name_key
        and existing.platform_game_id == game_id
        for existing in observed_games
    ):
        return
    observed_games.append(
        ObservedGameSeed(
            game_name=game_name,
            platform_game_id=game_id,
        )
    )


def bundle_from_records(
    *,
    user: TwitchUser,
    channel_info: TwitchChannelInfoRecord | None,
    stream: TwitchStreamRecord | None,
    videos: Sequence[TwitchVideoRecord],
    clips: Sequence[TwitchClipRecord] = (),
    clip_game_names: dict[str, str] | None = None,
    follower_total: int | None,
    panels: Sequence[dict] = (),
    youtube_emails: Sequence[str] = (),
    clip_cursor: str | None = None,
    clips_exhausted: bool = False,
) -> AccountSeedBundle | None:
    """Assemble a full :class:`AccountSeedBundle` from enrichment data.

    This is the public counterpart of the former ``_bundle_from_records`` in
    ``twitch.py``.  It takes a :class:`TwitchUser` instead of a search-channel
    record so it can be used without running a search query first.
    """
    broadcaster_id = user.user_id
    login = user.login.strip().lower()
    display_name = user.display_name.strip() or login
    if not broadcaster_id or not login or not display_name:
        return None

    now = datetime.now(UTC)
    fetched_at = now.isoformat()
    expires_at = (now + timedelta(days=14)).isoformat()
    description = user.description
    avatar_url = user.profile_image_url
    language = (stream.language if stream is not None else None) or (
        channel_info.broadcaster_language if channel_info is not None else None
    )
    last_live_at = stream.started_at if stream is not None else None
    account_type = infer_account_type(
        description,
        (stream.title if stream is not None else None)
        or (channel_info.title if channel_info is not None else None),
        (stream.tags if stream is not None else ())
        or (channel_info.tags if channel_info is not None else ()),
    )

    games_played: list[str] = []
    observed_games: list[ObservedGameSeed] = []
    for game_name, game_id in (
        (
            stream.game_name if stream is not None else None,
            stream.game_id if stream is not None else None,
        ),
        (
            channel_info.game_name if channel_info is not None else None,
            channel_info.game_id if channel_info is not None else None,
        ),
    ):
        _append_observed_game(
            games_played,
            observed_games,
            game_name=game_name,
            game_id=game_id,
        )

    for video in videos:
        _append_observed_game(
            games_played,
            observed_games,
            game_name=video.game_name,
            game_id=video.game_id,
        )

    resolved_names = clip_game_names or {}
    for clip in clips:
        clip_game_name = resolved_names.get(clip.game_id)
        if clip_game_name:
            _append_observed_game(
                games_played,
                observed_games,
                game_name=clip_game_name,
                game_id=clip.game_id,
            )

    content_samples_list: list[ContentSampleSeed] = []
    for position, video in enumerate(
        videos[:_MAX_CONTENT_SAMPLES_PER_ACCOUNT]
    ):
        sample = _video_to_sample(
            video=video,
            position_rank=position,
            fetched_at=fetched_at,
            expires_at=expires_at,
        )
        if sample is not None:
            content_samples_list.append(sample)
    content_samples = tuple(content_samples_list)

    # -- Contact points (cumulative dedup via shared seen-sets) --
    about_url = f"https://www.twitch.tv/{login}/about"
    seen_emails: set[str] = set()
    seen_discord: set[str] = set()
    contact_points_list: list[ContactPointSeed] = []

    # 1. Profile description
    contact_points_list.extend(
        collect_text_contacts(
            description,
            source_kind="profile_description",
            source_url=about_url,
            seen_emails=seen_emails,
            seen_discord=seen_discord,
        )
    )

    # 2. VOD descriptions
    for video in videos:
        contact_points_list.extend(
            collect_text_contacts(
                video.description,
                source_kind="video_description",
                source_url=video.url,
                seen_emails=seen_emails,
                seen_discord=seen_discord,
            )
        )

    # 3. Channel panels + social links
    contact_points_list.extend(
        extract_panel_contacts(list(panels), login, seen_emails, seen_discord)
    )

    # 4. YouTube about page (cross-platform fallback)
    for email in youtube_emails:
        if email not in seen_emails:
            seen_emails.add(email)
            contact_points_list.append(
                ContactPointSeed(
                    contact_type=ContactType.EMAIL,
                    contact_value=email,
                    source_kind="youtube_about",
                    source_url=None,
                )
            )

    contact_points = tuple(contact_points_list)
    vod_view_counts = [
        sample.engagement_count
        for sample in content_samples
        if sample.engagement_count is not None
    ]

    return AccountSeedBundle(
        account=SourceAccountSeed(
            external_id=broadcaster_id,
            handle_current=login,
            display_name_current=display_name,
            canonical_url=f"https://www.twitch.tv/{login}",
            account_type=account_type,
        ),
        platform_profile=TwitchProfileSeed(
            broadcaster_id=broadcaster_id,
            login=login,
            display_name=display_name,
            description=description,
            followers_count=follower_total,
            viewer_count=stream.viewer_count if stream is not None else None,
            recent_avg_live_viewers=None,
            recent_median_live_viewers=None,
            recent_avg_vod_views=mean_int(vod_view_counts),
            recent_median_vod_views=median_int(vod_view_counts),
            streams_last_30d=count_recent_timestamps(
                [sample.published_at for sample in content_samples],
                days=30,
                now=now,
            ),
            language=language,
            games_played=tuple(games_played),
            avatar_url=avatar_url,
            last_live_at=last_live_at,
            fetched_at=fetched_at,
            expires_at=expires_at,
            clip_cursor=clip_cursor,
            clips_exhausted=clips_exhausted,
        ),
        content_samples=content_samples,
        contact_points=contact_points,
        observed_games=tuple(observed_games),
    )
