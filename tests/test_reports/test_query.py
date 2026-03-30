"""Tests for ReportQueryService — the data layer for genre intelligence reports."""

from __future__ import annotations

import pytest

from app.reports.query import CreatorProfile, ReportQueryService
from tests.test_reports.conftest import (
    ACCOUNT_A,
    ACCOUNT_B,
    ACCOUNT_C,
    TAG_COMEDY,
    TAG_FANTASY,
    TAG_INDIE,
    TAG_STRATEGY,
)


# ---------------------------------------------------------------------------
# query_creator_tag_counts
# ---------------------------------------------------------------------------


class TestQueryCreatorTagCounts:
    def test_returns_creators_with_strategy_tag(self, query_service: ReportQueryService):
        # Strategy tag only belongs to Slay the Spire
        # streamer_a and streamer_b played Slay the Spire
        result = query_service.query_creator_tag_counts([("genre", TAG_STRATEGY)])
        assert ACCOUNT_A in result
        assert ACCOUNT_B in result
        assert ACCOUNT_C not in result

    def test_tag_counts_reflect_distinct_games(self, query_service: ReportQueryService):
        # streamer_a played Slay the Spire + Hades, both have Indie tag
        result = query_service.query_creator_tag_counts([("genre", TAG_INDIE)])
        assert result[ACCOUNT_A][("genre", TAG_INDIE)] == 2  # 2 games with Indie tag
        assert result[ACCOUNT_B][("genre", TAG_INDIE)] == 1  # 1 game with Indie tag
        assert result[ACCOUNT_C][("genre", TAG_INDIE)] == 1  # Stardew Valley

    def test_empty_tags_returns_empty_dict(self, query_service: ReportQueryService):
        result = query_service.query_creator_tag_counts([])
        assert result == {}

    def test_all_three_creators_returned_for_indie(self, query_service: ReportQueryService):
        # All three creators played games with Indie tag
        result = query_service.query_creator_tag_counts([("genre", TAG_INDIE)])
        assert set(result.keys()) == {ACCOUNT_A, ACCOUNT_B, ACCOUNT_C}

    def test_tag_key_type_is_tuple_str_int(self, query_service: ReportQueryService):
        result = query_service.query_creator_tag_counts([("genre", TAG_STRATEGY)])
        tag_keys = list(result[ACCOUNT_A].keys())
        for tag_type, tag_id in tag_keys:
            assert isinstance(tag_type, str)
            # tag_id from DB is integer for genre/theme tags
            assert isinstance(tag_id, int)

    def test_multiple_tags_union(self, query_service: ReportQueryService):
        # Fantasy tag: Slay the Spire + Hades → streamer_a, streamer_b
        # Comedy tag: Stardew Valley → streamer_c
        result = query_service.query_creator_tag_counts(
            [("theme", TAG_FANTASY), ("theme", TAG_COMEDY)]
        )
        assert ACCOUNT_A in result
        assert ACCOUNT_B in result
        assert ACCOUNT_C in result

    def test_strategy_tag_count_for_streamer_a(self, query_service: ReportQueryService):
        # streamer_a played Slay the Spire which has Strategy — 1 game
        result = query_service.query_creator_tag_counts([("genre", TAG_STRATEGY)])
        assert result[ACCOUNT_A][("genre", TAG_STRATEGY)] == 1

    def test_streamer_a_full_tag_set(self, query_service: ReportQueryService):
        # Query with Strategy tag; streamer_a's result includes ALL their tags
        result = query_service.query_creator_tag_counts([("genre", TAG_STRATEGY)])
        a_tags = result[ACCOUNT_A]
        # Slay the Spire has Strategy, Indie, Fantasy
        # Hades has Indie, Fantasy — so Indie and Fantasy appear in 2 games
        assert ("genre", TAG_STRATEGY) in a_tags
        assert ("genre", TAG_INDIE) in a_tags
        assert ("theme", TAG_FANTASY) in a_tags
        assert a_tags[("genre", TAG_INDIE)] == 2
        assert a_tags[("theme", TAG_FANTASY)] == 2


# ---------------------------------------------------------------------------
# query_creator_profiles
# ---------------------------------------------------------------------------


class TestQueryCreatorProfiles:
    def test_returns_profiles_for_given_ids(self, query_service: ReportQueryService):
        result = query_service.query_creator_profiles([ACCOUNT_A, ACCOUNT_B])
        assert set(result.keys()) == {ACCOUNT_A, ACCOUNT_B}

    def test_profile_fields(self, query_service: ReportQueryService):
        result = query_service.query_creator_profiles([ACCOUNT_A])
        profile = result[ACCOUNT_A]
        assert isinstance(profile, CreatorProfile)
        assert profile.account_id == ACCOUNT_A
        assert profile.platform == "twitch"
        assert profile.display_name == "StreamerA"
        assert profile.handle == "streamer_a"
        assert profile.followers_count == 5000
        assert profile.last_live_at is not None

    def test_follower_counts(self, query_service: ReportQueryService):
        result = query_service.query_creator_profiles([ACCOUNT_A, ACCOUNT_B, ACCOUNT_C])
        assert result[ACCOUNT_A].followers_count == 5000
        assert result[ACCOUNT_B].followers_count == 800
        assert result[ACCOUNT_C].followers_count == 20000

    def test_empty_ids_returns_empty_dict(self, query_service: ReportQueryService):
        result = query_service.query_creator_profiles([])
        assert result == {}

    def test_unknown_id_not_in_result(self, query_service: ReportQueryService):
        result = query_service.query_creator_profiles(["twitch:unknown_xyz"])
        assert result == {}


# ---------------------------------------------------------------------------
# query_contact_rates
# ---------------------------------------------------------------------------


class TestQueryContactRates:
    def test_email_rate_for_all_creators(self, query_service: ReportQueryService):
        # 1 out of 3 creators has email
        result = query_service.query_contact_rates([ACCOUNT_A, ACCOUNT_B, ACCOUNT_C])
        assert "email" in result
        assert result["email"] == pytest.approx(1 / 3)

    def test_discord_rate_for_all_creators(self, query_service: ReportQueryService):
        # 1 out of 3 creators has discord
        result = query_service.query_contact_rates([ACCOUNT_A, ACCOUNT_B, ACCOUNT_C])
        assert "discord" in result
        assert result["discord"] == pytest.approx(1 / 3)

    def test_contact_rate_subset(self, query_service: ReportQueryService):
        # Only streamer_a and streamer_b — email rate = 0.5, discord rate = 0.5
        result = query_service.query_contact_rates([ACCOUNT_A, ACCOUNT_B])
        assert result["email"] == pytest.approx(0.5)
        assert result["discord"] == pytest.approx(0.5)

    def test_no_contacts_for_creator_with_none(self, query_service: ReportQueryService):
        # streamer_c has no contacts
        result = query_service.query_contact_rates([ACCOUNT_C])
        assert result == {}

    def test_empty_ids_returns_empty_dict(self, query_service: ReportQueryService):
        result = query_service.query_contact_rates([])
        assert result == {}


# ---------------------------------------------------------------------------
# query_activity_recency
# ---------------------------------------------------------------------------


class TestQueryActivityRecency:
    def test_keys_present(self, query_service: ReportQueryService):
        result = query_service.query_activity_recency([ACCOUNT_A, ACCOUNT_B, ACCOUNT_C])
        assert set(result.keys()) == {"30d", "90d", "365d"}

    def test_recent_creators_counted(self, query_service: ReportQueryService):
        # streamer_a and streamer_b were recently active (within 30d)
        # streamer_c was last live in 2024-01-01 (>365d ago)
        result = query_service.query_activity_recency([ACCOUNT_A, ACCOUNT_B, ACCOUNT_C])
        # 2 out of 3 active within 30d
        assert result["30d"] == pytest.approx(2 / 3)
        assert result["90d"] == pytest.approx(2 / 3)
        assert result["365d"] == pytest.approx(2 / 3)

    def test_all_active_subset(self, query_service: ReportQueryService):
        # Only querying recent creators
        result = query_service.query_activity_recency([ACCOUNT_A, ACCOUNT_B])
        assert result["30d"] == pytest.approx(1.0)
        assert result["90d"] == pytest.approx(1.0)
        assert result["365d"] == pytest.approx(1.0)

    def test_inactive_only(self, query_service: ReportQueryService):
        # streamer_c last live in 2024, over 365d ago
        result = query_service.query_activity_recency([ACCOUNT_C])
        assert result["30d"] == pytest.approx(0.0)
        assert result["90d"] == pytest.approx(0.0)
        assert result["365d"] == pytest.approx(0.0)

    def test_empty_ids_returns_zero_buckets(self, query_service: ReportQueryService):
        result = query_service.query_activity_recency([])
        assert result == {}


# ---------------------------------------------------------------------------
# query_game_counts_per_tag
# ---------------------------------------------------------------------------


class TestQueryGameCountsPerTag:
    def test_strategy_tag_has_one_game(self, query_service: ReportQueryService):
        result = query_service.query_game_counts_per_tag([("genre", TAG_STRATEGY)])
        assert f"genre:{TAG_STRATEGY}" in result
        assert result[f"genre:{TAG_STRATEGY}"] == 1  # Only Slay the Spire

    def test_indie_tag_has_three_games(self, query_service: ReportQueryService):
        # All 3 games have Indie tag
        result = query_service.query_game_counts_per_tag([("genre", TAG_INDIE)])
        assert result[f"genre:{TAG_INDIE}"] == 3

    def test_fantasy_tag_has_two_games(self, query_service: ReportQueryService):
        # Slay the Spire and Hades have Fantasy
        result = query_service.query_game_counts_per_tag([("theme", TAG_FANTASY)])
        assert result[f"theme:{TAG_FANTASY}"] == 2

    def test_comedy_tag_has_one_game(self, query_service: ReportQueryService):
        result = query_service.query_game_counts_per_tag([("theme", TAG_COMEDY)])
        assert result[f"theme:{TAG_COMEDY}"] == 1

    def test_multiple_tags_returned(self, query_service: ReportQueryService):
        result = query_service.query_game_counts_per_tag(
            [("genre", TAG_STRATEGY), ("theme", TAG_FANTASY)]
        )
        assert f"genre:{TAG_STRATEGY}" in result
        assert f"theme:{TAG_FANTASY}" in result

    def test_empty_tags_returns_empty_dict(self, query_service: ReportQueryService):
        result = query_service.query_game_counts_per_tag([])
        assert result == {}

    def test_nonexistent_tag_not_in_result(self, query_service: ReportQueryService):
        result = query_service.query_game_counts_per_tag([("genre", 9999)])
        assert result == {}
