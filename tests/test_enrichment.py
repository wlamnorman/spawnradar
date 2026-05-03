"""Unit tests for app.creator_index.enrichment."""

from __future__ import annotations

import asyncio

from app.creator_index.adapters.base import ContactType, TwitchProfileSeed
from app.creator_index.enrichment import (
    TwitchChannelInfoRecord,
    TwitchClipRecord,
    TwitchEnrichment,
    TwitchStreamRecord,
    TwitchUser,
    TwitchVideoRecord,
    bundle_from_records,
    extract_panel_contacts,
    infer_account_type,
    parse_clip_record,
    parse_user,
)

# ---------------------------------------------------------------------------
# test_parse_user
# ---------------------------------------------------------------------------


def test_parse_user_parses_valid_json():
    raw = {
        "id": "12345",
        "login": "streamerx",
        "display_name": "StreamerX",
        "description": "I play games.",
        "profile_image_url": "https://img.twitch.tv/12345.jpg",
    }
    user = parse_user(raw)
    assert user is not None
    assert user.user_id == "12345"
    assert user.login == "streamerx"
    assert user.display_name == "StreamerX"
    assert user.description == "I play games."
    assert user.profile_image_url == "https://img.twitch.tv/12345.jpg"


def test_parse_user_returns_none_for_missing_fields():
    assert parse_user({"id": "1", "login": "x"}) is None
    assert parse_user({}) is None


def test_parse_user_strips_whitespace():
    raw = {
        "id": "  42  ",
        "login": "  alice  ",
        "display_name": " Alice ",
        "description": "  ",
        "profile_image_url": None,
    }
    user = parse_user(raw)
    assert user is not None
    assert user.user_id == "42"
    assert user.login == "alice"
    assert user.display_name == "Alice"
    assert user.description is None  # stripped to empty -> None
    assert user.profile_image_url is None


# ---------------------------------------------------------------------------
# test_parse_clip_record
# ---------------------------------------------------------------------------


def test_parse_clip_record_parses_valid_json():
    raw = {
        "id": "clip-abc",
        "broadcaster_id": "999",
        "game_id": "33214",
        "title": "Amazing play!",
        "view_count": 1500,
        "created_at": "2025-06-15T10:00:00Z",
        "thumbnail_url": "https://clips.twitch.tv/thumb.jpg",
        "url": "https://clips.twitch.tv/clip-abc",
        "language": "en",
    }
    clip = parse_clip_record(raw)
    assert clip is not None
    assert clip.clip_id == "clip-abc"
    assert clip.broadcaster_id == "999"
    assert clip.game_id == "33214"
    assert clip.title == "Amazing play!"
    assert clip.view_count == 1500
    assert clip.language == "en"


def test_parse_clip_record_returns_none_for_missing_game_id():
    raw = {
        "id": "clip-x",
        "broadcaster_id": "1",
        "title": "No game",
    }
    assert parse_clip_record(raw) is None


# ---------------------------------------------------------------------------
# test_extract_panel_contacts_email
# ---------------------------------------------------------------------------


def test_extract_panel_contacts_email():
    panels = [
        {"description": "Business: biz@example.com", "linkURL": ""},
    ]
    contacts = extract_panel_contacts(panels, "testuser", set(), set())
    email_contacts = [
        c for c in contacts if c.contact_type == ContactType.EMAIL
    ]
    assert len(email_contacts) == 1
    assert email_contacts[0].contact_value == "biz@example.com"
    assert email_contacts[0].source_kind == "channel_panel"


# ---------------------------------------------------------------------------
# test_extract_panel_contacts_discord
# ---------------------------------------------------------------------------


def test_extract_panel_contacts_discord():
    panels = [
        {"description": "Join us https://discord.gg/myserver", "linkURL": ""},
    ]
    contacts = extract_panel_contacts(panels, "testuser", set(), set())
    discord_contacts = [
        c for c in contacts if c.contact_type == ContactType.DISCORD
    ]
    assert len(discord_contacts) == 1
    assert discord_contacts[0].contact_value == "https://discord.gg/myserver"


def test_extract_panel_contacts_social_link():
    panels = [
        {"description": "", "linkURL": "https://twitter.com/testuser"},
    ]
    contacts = extract_panel_contacts(panels, "testuser", set(), set())
    social_contacts = [
        c for c in contacts if c.contact_type == ContactType.SOCIAL_LINK
    ]
    assert len(social_contacts) == 1
    assert social_contacts[0].contact_value == "https://twitter.com/testuser"


# ---------------------------------------------------------------------------
# test_bundle_from_records
# ---------------------------------------------------------------------------


def test_bundle_from_records_assembles_bundle():
    user = TwitchUser(
        user_id="100",
        login="gamergal",
        display_name="GamerGal",
        description="I stream indie games",
        profile_image_url="https://img.twitch.tv/100.jpg",
    )
    channel_info = TwitchChannelInfoRecord(
        broadcaster_id="100",
        broadcaster_language="en",
        title="Playing something cool",
        game_id="12345",
        game_name="Stardew Valley",
        tags=("farming", "chill"),
    )
    video = TwitchVideoRecord(
        video_id="v001",
        title="Chill farming stream",
        description="Join our discord https://discord.gg/test",
        thumbnail_url=None,
        created_at="2026-03-20T10:00:00Z",
        view_count=500,
        url="https://www.twitch.tv/videos/v001",
        stream_id=None,
        language="en",
        game_id="12345",
        game_name="Stardew Valley",
        video_type="archive",
        duration="3h20m",
    )
    clip = TwitchClipRecord(
        clip_id="c001",
        broadcaster_id="100",
        game_id="67890",
        title="Epic moment",
        view_count=2000,
        created_at="2026-03-15T08:00:00Z",
        thumbnail_url=None,
        url="https://clips.twitch.tv/c001",
        language="en",
    )

    bundle = bundle_from_records(
        user=user,
        channel_info=channel_info,
        stream=None,
        videos=[video],
        clips=[clip],
        clip_game_names={"67890": "Minecraft"},
        follower_total=5000,
        panels=[],
        youtube_emails=[],
    )

    assert bundle is not None
    assert bundle.account.external_id == "100"
    assert bundle.account.handle_current == "gamergal"
    assert bundle.account.display_name_current == "GamerGal"
    assert bundle.account.canonical_url == "https://www.twitch.tv/gamergal"
    assert bundle.account.account_type == "creator"

    profile = bundle.platform_profile
    assert isinstance(profile, TwitchProfileSeed)
    assert profile.broadcaster_id == "100"
    assert profile.followers_count == 5000
    assert profile.language == "en"
    assert "Stardew Valley" in profile.games_played
    assert profile.recent_avg_vod_views == 500

    assert len(bundle.content_samples) == 1
    assert bundle.content_samples[0].title_or_text == "Chill farming stream"

    # Clip game should appear in observed games
    observed_names = [og.game_name for og in bundle.observed_games]
    assert "Stardew Valley" in observed_names
    assert "Minecraft" in observed_names

    # Discord from VOD description
    discord_contacts = [
        c
        for c in bundle.contact_points
        if c.contact_type == ContactType.DISCORD
    ]
    assert len(discord_contacts) >= 1


def test_bundle_from_records_returns_none_for_empty_user():
    user = TwitchUser(
        user_id="",
        login="",
        display_name="",
        description=None,
        profile_image_url=None,
    )
    assert (
        bundle_from_records(
            user=user,
            channel_info=None,
            stream=None,
            videos=[],
            follower_total=None,
        )
        is None
    )


def test_enrich_broadcaster_includes_stream_and_video_audience(monkeypatch):
    enrichment = TwitchEnrichment("cid", "secret")
    user = TwitchUser(
        user_id="100",
        login="gamergal",
        display_name="GamerGal",
        description="Indie streams",
        profile_image_url="https://img.twitch.tv/100.jpg",
    )
    channel_info = TwitchChannelInfoRecord(
        broadcaster_id="100",
        broadcaster_language="en",
        title="Live now",
        game_id="12345",
        game_name="Stardew Valley",
        tags=("cozy",),
    )
    stream = TwitchStreamRecord(
        user_id="100",
        game_id="12345",
        game_name="Stardew Valley",
        title="Live now",
        tags=("cozy",),
        viewer_count=42,
        language="en",
        started_at="2026-03-20T12:00:00Z",
    )
    videos = [
        TwitchVideoRecord(
            video_id="v001",
            title="Stream archive 1",
            description=None,
            thumbnail_url=None,
            created_at="2026-03-19T10:00:00Z",
            view_count=120,
            url="https://www.twitch.tv/videos/v001",
            stream_id="s001",
            language="en",
            game_id="12345",
            game_name="Stardew Valley",
            video_type="archive",
            duration="3h",
        ),
        TwitchVideoRecord(
            video_id="v002",
            title="Stream archive 2",
            description=None,
            thumbnail_url=None,
            created_at="2026-03-18T10:00:00Z",
            view_count=180,
            url="https://www.twitch.tv/videos/v002",
            stream_id="s002",
            language="en",
            game_id="67890",
            game_name="Dave the Diver",
            video_type="archive",
            duration="2h",
        ),
    ]
    clips = [
        TwitchClipRecord(
            clip_id="c001",
            broadcaster_id="100",
            game_id="67890",
            title="Clip",
            view_count=900,
            created_at="2026-03-18T12:00:00Z",
            thumbnail_url=None,
            url="https://clips.twitch.tv/c001",
            language="en",
        )
    ]

    async def fake_auth_headers(client):
        return {"Authorization": "Bearer test", "Client-Id": "cid"}

    async def fake_fetch_users(broadcaster_ids, *, client=None, headers=None):
        assert broadcaster_ids == ["100"]
        return {"100": user}

    async def fake_fetch_channel_info(
        broadcaster_ids, *, client=None, headers=None
    ):
        assert broadcaster_ids == ["100"]
        return {"100": channel_info}

    async def fake_fetch_streams(
        broadcaster_ids, *, client=None, headers=None
    ):
        assert broadcaster_ids == ["100"]
        return {"100": stream}

    async def fake_fetch_videos_for_users(
        broadcaster_ids,
        *,
        limit_per_user=5,
        client=None,
        headers=None,
    ):
        assert broadcaster_ids == ["100"]
        assert limit_per_user == 5
        return {"100": videos}

    async def fake_fetch_clips_for_users(
        broadcaster_ids, *, client=None, headers=None
    ):
        assert broadcaster_ids == ["100"]
        return {"100": clips}

    async def fake_fetch_follower_totals(
        broadcaster_ids, *, client=None, headers=None
    ):
        assert broadcaster_ids == ["100"]
        return {"100": 5000}

    async def fake_resolve_game_names(game_ids, *, client=None, headers=None):
        assert game_ids == {"67890"}
        return {"67890": "Dave the Diver"}

    monkeypatch.setattr(enrichment, "_auth_headers", fake_auth_headers)
    monkeypatch.setattr(enrichment, "fetch_users", fake_fetch_users)
    monkeypatch.setattr(
        enrichment, "fetch_channel_info", fake_fetch_channel_info
    )
    monkeypatch.setattr(enrichment, "fetch_streams", fake_fetch_streams)
    monkeypatch.setattr(
        enrichment, "fetch_videos_for_users", fake_fetch_videos_for_users
    )
    monkeypatch.setattr(
        enrichment, "fetch_clips_for_users", fake_fetch_clips_for_users
    )
    monkeypatch.setattr(
        enrichment, "fetch_follower_totals", fake_fetch_follower_totals
    )
    monkeypatch.setattr(
        enrichment, "resolve_game_names", fake_resolve_game_names
    )

    bundle = asyncio.run(
        enrichment.enrich_broadcaster("100", skip_contacts=True)
    )

    assert bundle is not None
    profile = bundle.platform_profile
    assert isinstance(profile, TwitchProfileSeed)
    assert profile.viewer_count == 42
    assert profile.recent_avg_vod_views == 150
    assert profile.last_live_at == "2026-03-20T12:00:00Z"
    assert len(bundle.content_samples) == 2


# ---------------------------------------------------------------------------
# test_infer_account_type
# ---------------------------------------------------------------------------


def test_infer_account_type_detects_developer():
    assert infer_account_type("indie gamedev here", None, []) == "developer"
    assert infer_account_type(None, "devlog stream", []) == "developer"
    assert infer_account_type(None, None, ["indiedev"]) == "developer"


def test_infer_account_type_defaults_to_creator():
    assert (
        infer_account_type("Just a streamer", "Playing Fortnite", ["fps"])
        == "creator"
    )
    assert infer_account_type(None, None, []) == "creator"
