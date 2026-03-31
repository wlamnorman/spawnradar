"""Tests for game creation, updates, and billing limits."""

import pytest


def test_create_game_stores_and_returns_game(game_service, registered_user):
    game = game_service.create_game(
        user_id=registered_user.user_id,
        name="SpacePuzzle",
        summary="A puzzle game set in space.",
        description="A puzzle game set in space",
        website_url=None,
        igdb_genre_ids=[9],  # Puzzle
    )
    from app.games.models import CustomerGame

    assert isinstance(game, CustomerGame)
    assert game.name == "SpacePuzzle"
    assert game.user_id == registered_user.user_id


def test_create_game_stores_igdb_ids(game_service, registered_user):
    game = game_service.create_game(
        user_id=registered_user.user_id,
        name="TagGame",
        summary="Testing IGDB taxonomy IDs.",
        description="Testing tags",
        website_url=None,
        igdb_genre_ids=[9, 26],  # Puzzle, Quiz/Trivia
        igdb_theme_ids=[42],  # Erotic (just an example ID)
        igdb_game_mode_ids=[1, 3],
        igdb_player_perspective_ids=[2, 4],
    )
    assert 9 in game.igdb_genre_ids
    assert 26 in game.igdb_genre_ids
    assert 42 in game.igdb_theme_ids
    assert 1 in game.igdb_game_mode_ids
    assert 3 in game.igdb_game_mode_ids
    assert 2 in game.igdb_player_perspective_ids
    assert 4 in game.igdb_player_perspective_ids


def test_create_game_stores_platforms_and_labels(
    game_service, registered_user
):
    game = game_service.create_game(
        user_id=registered_user.user_id,
        name="PlatformGame",
        summary="Testing platform storage.",
        description="Testing platform storage.",
        website_url=None,
        platforms=["pc", "switch", "board-game"],
        igdb_genre_ids=[9],
    )
    assert game.platforms == ["pc", "switch", "board-game"]
    assert game.platform_labels == [
        "PC / Steam",
        "Nintendo Switch",
        "Board Game",
    ]


def test_create_game_defaults_optional_igdb_fields(
    game_service, registered_user
):
    game = game_service.create_game(
        user_id=registered_user.user_id,
        name="MinimalGame",
        summary="Minimal game with just a genre.",
        description="Testing defaults",
        website_url=None,
        igdb_genre_ids=[9],  # Puzzle
    )
    assert game.igdb_genre_ids == [9]
    assert game.igdb_theme_ids == []
    assert game.igdb_game_mode_ids == []
    assert game.igdb_player_perspective_ids == []


def test_customer_facing_labels_merge_curated_keyword_buckets(
    game_service, registered_user
):
    game = game_service.create_game(
        user_id=registered_user.user_id,
        name="BucketLabels",
        summary="Labels include curated buckets.",
        description="Labels include curated buckets.",
        website_url=None,
        igdb_genre_ids=[12],
        igdb_theme_ids=[18],
        igdb_keyword_ids=["roguelike", "cozy", "crafting"],
    )
    assert "Role-playing (RPG)" in game.genre_labels
    assert "Roguelike" in game.genre_labels
    assert "Science fiction" in game.theme_labels
    assert "Cozy" in game.theme_labels
    assert game.mechanic_labels == ["Crafting"]


def test_update_game_changes_fields(
    game_service, sample_game, registered_user
):
    updated = game_service.update_game(
        customer_game_id=sample_game.customer_game_id,
        user_id=registered_user.user_id,
        name="PuzzleQuest Updated",
        summary="An updated summary",
        description="An updated description",
        website_url="https://example.com",
        platforms=["mobile", "vr"],
        igdb_genre_ids=[9, 12],  # Puzzle, Strategy
        igdb_game_mode_ids=[1, 2],
        igdb_player_perspective_ids=[3],
    )
    assert updated.name == "PuzzleQuest Updated"
    assert updated.description == "An updated description"
    assert updated.website_url == "https://example.com"
    assert updated.platforms == ["mobile", "vr"]
    assert 9 in updated.igdb_genre_ids
    assert 12 in updated.igdb_genre_ids
    assert updated.igdb_game_mode_ids == [1, 2]
    assert updated.igdb_player_perspective_ids == [3]


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
            website_url=None,
            igdb_genre_ids=[9],
        )

    # Should now be at the Indie trial limit (3 games)
    assert billing_service.check_game_limit(registered_user.user_id) is False


def test_create_game_rejects_summary_longer_than_200_characters(
    game_service, registered_user
):
    with pytest.raises(ValueError, match="200 characters or fewer"):
        game_service.create_game(
            user_id=registered_user.user_id,
            name="Summary Limit",
            summary="x" * 201,
            description="Valid description",
            website_url=None,
        )


def test_update_game_rejects_description_longer_than_1000_characters(
    game_service, sample_game, registered_user
):
    with pytest.raises(ValueError, match="1000 characters or fewer"):
        game_service.update_game(
            customer_game_id=sample_game.customer_game_id,
            user_id=registered_user.user_id,
            name=sample_game.name,
            summary=sample_game.summary or "",
            description="x" * 1001,
            website_url=sample_game.website_url,
        )


def test_create_game_rejects_missing_summary(game_service, registered_user):
    with pytest.raises(ValueError, match="Game summary is required"):
        game_service.create_game(
            user_id=registered_user.user_id,
            name="Missing Summary",
            summary="",
            description="Valid description",
            website_url=None,
        )


def test_create_game_allows_blank_description(game_service, registered_user):
    game = game_service.create_game(
        user_id=registered_user.user_id,
        name="Optional Description",
        summary="A summary is enough for setup.",
        description="",
        website_url=None,
        igdb_genre_ids=[12],
    )

    assert game.description == ""


