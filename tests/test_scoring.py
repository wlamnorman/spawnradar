"""Tests for the tag-driven scoring engine."""

import uuid
from datetime import UTC, datetime

from app.games.models import Game
from app.prospects.models import Prospect
from app.scoring.engine import ScoreBreakdown, score_prospect


def _make_game(
    genre_tags=None,
    platform_tags=None,
    name="TestGame",
):
    now = datetime.now(UTC).isoformat()
    return Game(
        game_id=str(uuid.uuid4()),
        user_id=str(uuid.uuid4()),
        slug=f"{name.lower()}-{uuid.uuid4().hex[:8]}",
        name=name,
        summary=None,
        description="A test game",
        genre_tags=genre_tags or [],
        platform_tags=platform_tags or [],
        website_url=None,
        status="active",
        created_at=now,
        updated_at=now,
    )


def _make_prospect(
    display_name="Test Creator",
    handle="testcreator",
    description=None,
    contact_channel=None,
    contact_value=None,
    profile_url=None,
    audience_size=None,
    raw_data=None,
):
    now = datetime.now(UTC).isoformat()
    return Prospect(
        prospect_id=str(uuid.uuid4()),
        platform="youtube",
        handle=handle,
        display_name=display_name,
        profile_url=profile_url,
        contact_channel=contact_channel,
        contact_value=contact_value,
        audience_size=audience_size,
        engagement_rate=None,
        description=description,
        raw_data=raw_data or {},
        created_at=now,
        updated_at=now,
    )


def test_score_prospect_returns_score_breakdown():
    game = _make_game(
        genre_tags=["puzzle"],
        platform_tags=["browser"],
    )
    prospect = _make_prospect(description="puzzle fans browser games")
    result = score_prospect(game, prospect)
    assert isinstance(result, ScoreBreakdown)


def test_score_breakdown_has_all_fields():
    game = _make_game(genre_tags=["puzzle"])
    prospect = _make_prospect()
    result = score_prospect(game, prospect)
    assert hasattr(result, "genre_fit")
    assert hasattr(result, "vibe_fit")
    assert hasattr(result, "platform_fit")
    assert hasattr(result, "contactability")
    assert hasattr(result, "audience_size_score")
    assert hasattr(result, "final_score")
    assert hasattr(result, "fit_summary")
    assert hasattr(result, "reasons")


def test_prospect_matching_all_tags_scores_high():
    game = _make_game(
        genre_tags=["puzzle", "word game", "daily"],
        platform_tags=["browser"],
    )
    prospect = _make_prospect(
        display_name="Puzzle Word Game Daily",
        description="wordle fans and puzzle lovers, browser based daily word game",
        contact_channel="email",
        contact_value="creator@example.com",
        audience_size=200_000,
    )
    result = score_prospect(game, prospect)
    assert result.final_score > 0.6


def test_prospect_with_no_matching_tags_scores_low():
    game = _make_game(
        genre_tags=["puzzle", "word game"],
        platform_tags=["browser"],
    )
    prospect = _make_prospect(
        display_name="FPS Shooter Pro",
        description="first person shooter action combat military games",
    )
    result = score_prospect(game, prospect)
    assert result.final_score < 0.3


def test_contactability_increases_with_contact_channel():
    game = _make_game(genre_tags=["puzzle"])
    prospect_no_contact = _make_prospect()
    prospect_with_channel = _make_prospect(contact_channel="email")

    score_no = score_prospect(game, prospect_no_contact)
    score_with = score_prospect(game, prospect_with_channel)
    assert score_with.contactability > score_no.contactability


def test_contactability_increases_with_contact_value():
    game = _make_game(genre_tags=["puzzle"])
    prospect_no_contact = _make_prospect()
    prospect_with_value = _make_prospect(
        contact_channel="email",
        contact_value="creator@example.com",
    )

    score_no = score_prospect(game, prospect_no_contact)
    score_with = score_prospect(game, prospect_with_value)
    assert score_with.contactability > score_no.contactability


def test_contactability_details_do_not_appear_in_reasons():
    game = _make_game(genre_tags=["puzzle"])
    prospect = _make_prospect(
        description="puzzle tactics game",
        contact_channel="reddit_post",
        contact_value="https://reddit.example/post",
        profile_url="https://reddit.example/post",
    )

    result = score_prospect(game, prospect)

    assert result.contactability > 0.3
    assert not any(
        reason.startswith("Contact channel available:")
        for reason in result.reasons
    )
    assert not any(
        reason.startswith("Contact value present:")
        for reason in result.reasons
    )


def test_audience_size_score_is_zero_for_none():
    game = _make_game(genre_tags=["puzzle"])
    prospect = _make_prospect(audience_size=None)
    result = score_prospect(game, prospect)
    assert result.audience_size_score == 0.0


def test_audience_size_score_positive_for_100k():
    game = _make_game(genre_tags=["puzzle"])
    prospect = _make_prospect(audience_size=100_000)
    result = score_prospect(game, prospect)
    assert result.audience_size_score > 0.0


def test_audience_size_score_near_one_for_500k_plus():
    game = _make_game(genre_tags=["puzzle"])
    prospect = _make_prospect(audience_size=500_000)
    result = score_prospect(game, prospect)
    assert result.audience_size_score >= 0.99


def test_final_score_within_zero_to_one():
    game = _make_game(
        genre_tags=["puzzle", "word game"],
        platform_tags=["browser"],
    )
    prospect = _make_prospect(
        description="puzzle word game wordle fans browser",
        contact_channel="email",
        contact_value="x@x.com",
        audience_size=500_000,
    )
    result = score_prospect(game, prospect)
    assert 0.0 <= result.final_score <= 1.0


def test_fit_summary_is_non_empty_string():
    game = _make_game(genre_tags=["puzzle"], name="MyGame")
    prospect = _make_prospect(display_name="PuzzleFan")
    result = score_prospect(game, prospect)
    assert isinstance(result.fit_summary, str)
    assert len(result.fit_summary) > 0


def test_reasons_non_empty_when_there_are_matches():
    game = _make_game(genre_tags=["puzzle"])
    prospect = _make_prospect(description="puzzle fans community")
    result = score_prospect(game, prospect)
    assert len(result.reasons) > 0


def test_reasons_empty_when_no_matches():
    game = _make_game(genre_tags=["puzzle"])
    prospect = _make_prospect(description="fps shooter action")
    result = score_prospect(game, prospect)
    # Only contactability reasons could appear; genre/vibe reasons should be absent
    genre_vibe_reasons = [
        r
        for r in result.reasons
        if r.startswith("Genre") or r.startswith("Vibe")
    ]
    assert len(genre_vibe_reasons) == 0


def test_developer_prospects_are_downranked_vs_creators_and_communities():
    game = _make_game(
        genre_tags=["strategy", "roguelite"],
        platform_tags=["PC"],
    )
    common_description = "strategy roguelite indie tactics fans pc devlog browser steam"

    creator = _make_prospect(
        display_name="Strategy Creator",
        description=common_description,
        contact_channel="email",
        contact_value="creator@example.com",
        audience_size=50_000,
        raw_data={"prospect_type": "creator", "last_active_days": 3},
    )
    community = _make_prospect(
        display_name="Strategy Community",
        description=common_description,
        contact_channel="reddit_post",
        contact_value="https://reddit.example/post",
        audience_size=50_000,
        raw_data={"prospect_type": "community", "last_active_days": 3},
    )
    developer = _make_prospect(
        display_name="Indie Dev",
        description=common_description,
        contact_channel="email",
        contact_value="dev@example.com",
        audience_size=50_000,
        raw_data={"prospect_type": "developer", "last_active_days": 3},
    )

    creator_score = score_prospect(game, creator)
    community_score = score_prospect(game, community)
    developer_score = score_prospect(game, developer)

    assert developer_score.final_score > 0.0
    assert developer_score.final_score < creator_score.final_score
    assert developer_score.final_score < community_score.final_score


def test_developer_prospects_still_surface_when_they_match_well():
    game = _make_game(
        genre_tags=["strategy"],
        platform_tags=["PC"],
    )
    developer = _make_prospect(
        display_name="Helpful Indie Dev",
        description="strategy indie tactics fans pc devlog and game marketing",
        contact_channel="email",
        contact_value="dev@example.com",
        raw_data={"prospect_type": "developer", "last_active_days": 2},
    )

    result = score_prospect(game, developer)

    assert 0.2 < result.final_score < 0.7
