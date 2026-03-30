import pytest

from app.reports.models import (
    CreatorSummary,
    GapEntry,
    GrowthSignal,
    ReportStats,
)


class TestReportStats:
    def test_construction(self):
        stats = ReportStats(
            catalog_game_slug="roguelite_strategy",
            genre_label="Roguelite / Strategy",
            total_creators=150,
            median_audience=1200,
            mean_audience=5400,
            platform_split={"twitch": 0.85, "youtube": 0.15},
            contact_rates={"email": 0.42, "discord": 0.31},
            activity_recency={"30d": 0.25, "90d": 0.55, "365d": 0.88},
        )
        assert stats.total_creators == 150
        assert stats.platform_split["twitch"] == 0.85

    def test_below_minimum_creators(self):
        stats = ReportStats(
            catalog_game_slug="test",
            genre_label="Test",
            total_creators=10,
            median_audience=0,
            mean_audience=0,
            platform_split={},
            contact_rates={},
            activity_recency={},
        )
        assert stats.has_sufficient_data is False

    def test_above_minimum_creators(self):
        stats = ReportStats(
            catalog_game_slug="test",
            genre_label="Test",
            total_creators=50,
            median_audience=100,
            mean_audience=200,
            platform_split={},
            contact_rates={},
            activity_recency={},
        )
        assert stats.has_sufficient_data is True


class TestCreatorSummary:
    def test_relevance_score_is_0_to_100(self):
        creator = CreatorSummary(
            account_id="twitch:streamerx",
            name="StreamerX",
            handle="streamerx",
            platform="twitch",
            audience_size=5000,
            relevance_score=73,
            overlapping_tags=("Strategy", "Roguelite"),
        )
        assert 0 <= creator.relevance_score <= 100
        assert creator.platform == "twitch"


class TestGapEntry:
    def test_construction(self):
        gap = GapEntry(
            tag_combination=("roguelite", "deck-building"),
            creator_count=12,
            game_count=45,
            ratio=0.27,
        )
        assert gap.ratio == pytest.approx(0.27)


class TestGrowthSignal:
    def test_construction(self):
        signal = GrowthSignal(
            name="NewStreamer",
            handle="newstreamer",
            platform="twitch",
            audience_size=800,
            relevance_score=65,
            last_active="2026-03-28",
        )
        assert signal.audience_size == 800
