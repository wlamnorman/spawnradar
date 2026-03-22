"""Tests for game creation, updates, templates, assets, and billing limits."""

import pytest

from app.games.models import Asset, Game, MessageTemplate
from app.games.repository import _parse_sources
from app.games.tags import TagProfile
from app.ingestion.pipeline import youtube_candidate_limit
from app.ingestion.registry import Source


def test_create_game_stores_and_returns_game(game_service, registered_user):
    game = game_service.create_game(
        user_id=registered_user.user_id,
        name="SpacePuzzle",
        summary="A puzzle game set in space.",
        description="A puzzle game set in space",
        genre_tags_raw="puzzle, space",
        audience_tags_raw="space fans",
        platform_tags=["browser"],
        website_url=None,
    )
    assert isinstance(game, Game)
    assert game.name == "SpacePuzzle"
    assert game.user_id == registered_user.user_id


def test_create_game_returns_correct_tags(game_service, registered_user):
    game = game_service.create_game(
        user_id=registered_user.user_id,
        name="TagGame",
        summary="Testing tag normalization.",
        description="Testing tags",
        genre_tags_raw="puzzle, word game, daily",
        audience_tags_raw="wordle fans, puzzle lovers",
        platform_tags=["browser", "mobile"],
        website_url=None,
    )
    assert "puzzle" in game.genre_tags
    assert "word game" in game.genre_tags
    assert "daily" in game.genre_tags
    assert "wordle fans" in game.audience_tags
    assert "browser" in game.platform_tags
    assert "mobile" in game.platform_tags


def test_new_games_default_to_youtube_reddit_and_bluesky(
    game_service, registered_user
):
    game = game_service.create_game(
        user_id=registered_user.user_id,
        name="Signal Game",
        summary="Testing discovery source defaults.",
        description="Testing discovery source defaults",
        genre_tags_raw="strategy",
        audience_tags_raw="indie players",
        platform_tags=["pc"],
        website_url=None,
    )

    assert game.discovery_sources == [
        Source.YOUTUBE,
        Source.REDDIT,
        Source.BLUESKY,
        Source.TWITCH,
    ]


def test_genre_tags_parsed_from_comma_separated_string(
    game_service, registered_user
):
    game = game_service.create_game(
        user_id=registered_user.user_id,
        name="ParseGame",
        summary="Testing tag parsing.",
        description="Testing tag parsing",
        genre_tags_raw="  action , rpg , strategy  ",
        audience_tags_raw="gamers",
        platform_tags=["pc"],
        website_url=None,
    )
    assert game.genre_tags == ["action", "rpg", "strategy"]


def test_structured_tags_store_primary_secondary_and_custom_profiles(
    game_service, registered_user
):
    game = game_service.create_game(
        user_id=registered_user.user_id,
        name="StructureTest",
        summary="Testing structured tags.",
        description="Testing structured tags",
        genre_tags_raw="",
        audience_tags_raw="",
        platform_tags=["pc"],
        website_url=None,
        genre_primary_tags_raw="rts, turn based tactics",
        genre_secondary_tags_raw="tower defence, strategy",
        genre_custom_tags_raw="xcom-like",
        audience_primary_tags_raw="strategy players, xcom players",
        audience_secondary_tags_raw="pc gamers, steam users",
        audience_custom_tags_raw="tactics forum regulars",
    )

    assert game.genre_primary_tags == [
        "real-time strategy",
        "turn-based tactics",
    ]
    assert game.genre_secondary_tags == ["tower defense", "strategy"]
    assert game.genre_custom_tags == ["xcom like"]
    assert game.audience_primary_tags == ["strategy fans", "xcom fans"]
    assert game.audience_secondary_tags == ["pc players", "steam players"]
    assert game.audience_custom_tags == ["tactics forum regulars"]
    assert game.genre_tags == [
        "real-time strategy",
        "turn-based tactics",
        "tower defense",
        "strategy",
        "xcom like",
    ]


def test_primary_tags_are_ordered_first_in_query_builder(
    game_service, registered_user
):
    game = game_service.create_game(
        user_id=registered_user.user_id,
        name="QueryWeightTest",
        summary="Testing query order.",
        description="Testing query order",
        genre_tags_raw="",
        audience_tags_raw="",
        platform_tags=["pc"],
        website_url=None,
        genre_primary_tags_raw="turn based tactics",
        genre_secondary_tags_raw="strategy, sci-fi",
        audience_primary_tags_raw="tactics fans",
        audience_secondary_tags_raw="pc gamers",
    )

    from app.ingestion.query_builder import build_basic_queries

    queries = build_basic_queries(game)

    assert queries[:5] == [
        "turn-based tactics",
        "strategy",
        "sci-fi",
        "tactics players",
        "pc players",
    ]


def test_discovery_readiness_allows_complete_games(game_service, sample_game):
    readiness = game_service.get_discovery_readiness(sample_game)

    assert readiness.can_run is True
    assert readiness.missing_fields == ()
    assert readiness.message == "Discovery ready."


def test_discovery_readiness_reports_missing_summary_and_primary_genre_tags(
    game_service, game_repo, registered_user
):
    legacy_game = game_repo.create(
        game_id="legacy-game-1",
        user_id=registered_user.user_id,
        name="Legacy Game",
        summary=None,
        description="A legacy game with sparse metadata.",
        genre_tags=[],
        audience_tags=[],
        genre_tag_profile=TagProfile.empty(),
        audience_tag_profile=TagProfile.empty(),
        mechanics_tag_profile=TagProfile.empty(),
        tone_tag_profile=TagProfile.empty(),
        platform_tags=["browser"],
        website_url=None,
    )

    readiness = game_service.get_discovery_readiness(legacy_game)

    assert readiness.can_run is False
    assert readiness.missing_fields == ("summary", "primary genre tags")
    assert (
        readiness.message
        == "Finish setup before running discovery. Missing summary and primary genre tags."
    )


def test_update_game_changes_fields(
    game_service, sample_game, registered_user
):
    updated = game_service.update_game(
        game_id=sample_game.game_id,
        user_id=registered_user.user_id,
        name="PuzzleQuest Updated",
        summary="An updated summary",
        description="An updated description",
        genre_tags_raw="puzzle, adventure",
        audience_tags_raw="puzzle fans",
        platform_tags=["mobile"],
        website_url="https://example.com",
    )
    assert updated.name == "PuzzleQuest Updated"
    assert updated.description == "An updated description"
    assert "adventure" in updated.genre_tags
    assert updated.platform_tags == ["mobile"]
    assert updated.website_url == "https://example.com"


def test_add_template_stores_template_linked_to_game(
    game_service, sample_game, registered_user
):
    template = game_service.add_template(
        game_id=sample_game.game_id,
        user_id=registered_user.user_id,
        name="YouTube Outreach",
        channel="youtube_dm",
        subject_template=None,
        body_template="Hi {{creator_name}}, check out {{game_name}}!",
    )
    assert isinstance(template, MessageTemplate)
    assert template.game_id == sample_game.game_id
    assert template.channel == "youtube_dm"
    assert "{{creator_name}}" in template.body_template


def test_delete_template_removes_it(
    game_service, template_repo, sample_game, registered_user
):
    template = game_service.add_template(
        game_id=sample_game.game_id,
        user_id=registered_user.user_id,
        name="To Delete",
        channel="email",
        subject_template="Hello",
        body_template="Body text here",
    )
    assert template_repo.get_by_id(template.template_id) is not None

    game_service.delete_template(
        template_id=template.template_id,
        game_id=sample_game.game_id,
        user_id=registered_user.user_id,
    )
    assert template_repo.get_by_id(template.template_id) is None


def test_add_asset_stores_asset(game_service, sample_game, registered_user):
    asset = game_service.add_asset(
        game_id=sample_game.game_id,
        user_id=registered_user.user_id,
        asset_type="screenshot",
        title="Main Menu Screenshot",
        body=None,
        url="https://cdn.example.com/screenshot.png",
    )
    assert isinstance(asset, Asset)
    assert asset.game_id == sample_game.game_id
    assert asset.asset_type == "screenshot"
    assert asset.title == "Main Menu Screenshot"


def test_delete_asset_removes_it(
    game_service, asset_repo, sample_game, registered_user
):
    asset = game_service.add_asset(
        game_id=sample_game.game_id,
        user_id=registered_user.user_id,
        asset_type="logo",
        title="Game Logo",
        body=None,
        url="https://cdn.example.com/logo.png",
    )
    assert asset_repo.get_by_id(asset.asset_id) is not None

    game_service.delete_asset(
        asset_id=asset.asset_id,
        game_id=sample_game.game_id,
        user_id=registered_user.user_id,
    )
    assert asset_repo.get_by_id(asset.asset_id) is None


def test_game_limit_returns_false_after_trial_limit(
    game_service, billing_service, registered_user
):
    # New subscriptions are in a 3-day Indie trial (3 game limit).
    assert billing_service.check_game_limit(registered_user.user_id) is True

    for i in range(3):
        game_service.create_game(
            user_id=registered_user.user_id,
            name=f"Game {i}",
            summary="First game summary",
            description="First game description",
            genre_tags_raw="puzzle",
            audience_tags_raw="fans",
            platform_tags=["browser"],
            website_url=None,
        )

    # Should now be at the Indie trial limit (3 games)
    assert billing_service.check_game_limit(registered_user.user_id) is False


def test_youtube_candidate_limit_is_capped_at_ten():
    assert youtube_candidate_limit(50) == 10
    assert youtube_candidate_limit(10) == 10
    assert youtube_candidate_limit(6) == 6


def test_message_templates_can_target_twitch_dm(game_service, registered_user):
    game = game_service.create_game(
        user_id=registered_user.user_id,
        name="Twitch Template Game",
        summary="Testing Twitch template support.",
        description="Testing Twitch template support",
        genre_tags_raw="strategy",
        audience_tags_raw="stream viewers",
        platform_tags=["pc"],
        website_url=None,
    )

    template = game_service.add_template(
        game_id=game.game_id,
        user_id=registered_user.user_id,
        name="Twitch Whisper",
        channel="twitch_dm",
        subject_template=None,
        body_template="Hi {{creator_name}}, want to see {{game_name}}?",
    )

    assert template.channel == "twitch_dm"


def test_legacy_default_source_lists_gain_twitch():
    parsed = _parse_sources('["youtube", "reddit", "bluesky"]')

    assert parsed == [
        Source.YOUTUBE,
        Source.REDDIT,
        Source.BLUESKY,
        Source.TWITCH,
    ]


def test_create_game_rejects_summary_longer_than_150_characters(
    game_service, registered_user
):
    with pytest.raises(ValueError, match="150 characters or fewer"):
        game_service.create_game(
            user_id=registered_user.user_id,
            name="Summary Limit",
            summary="x" * 151,
            description="Valid description",
            genre_tags_raw="strategy",
            audience_tags_raw="players",
            platform_tags=["pc"],
            website_url=None,
        )


def test_update_game_rejects_description_longer_than_1500_characters(
    game_service, sample_game, registered_user
):
    with pytest.raises(ValueError, match="1500 characters or fewer"):
        game_service.update_game(
            game_id=sample_game.game_id,
            user_id=registered_user.user_id,
            name=sample_game.name,
            summary=sample_game.summary or "",
            description="x" * 1501,
            genre_tags_raw=", ".join(sample_game.genre_tags),
            audience_tags_raw=", ".join(sample_game.audience_tags),
            platform_tags=sample_game.platform_tags,
            website_url=sample_game.website_url,
        )


def test_create_game_rejects_missing_summary(game_service, registered_user):
    with pytest.raises(ValueError, match="Game summary is required"):
        game_service.create_game(
            user_id=registered_user.user_id,
            name="Missing Summary",
            summary="",
            description="Valid description",
            genre_tags_raw="strategy",
            audience_tags_raw="players",
            platform_tags=["pc"],
            website_url=None,
        )


def test_create_game_rejects_missing_primary_genre_tag(game_service, registered_user):
    with pytest.raises(ValueError, match="primary genre tag"):
        game_service.create_game(
            user_id=registered_user.user_id,
            name="Missing Genre",
            summary="Valid summary",
            description="Valid description",
            genre_tags_raw="",
            audience_tags_raw="players",
            platform_tags=["pc"],
            website_url=None,
        )
