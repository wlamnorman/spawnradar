import pytest
from datetime import datetime, timedelta, timezone

from app.reports.analysis import compute_gap_analysis, compute_growth_signals
from app.reports.models import CreatorSummary, GapEntry, GrowthSignal


class TestGapAnalysis:
    def test_returns_sorted_by_ratio(self):
        tag_stats = {
            "Strategy": (50, 100),
            "Roguelite": (5, 40),
            "Fantasy": (80, 60),
        }
        gaps = compute_gap_analysis(tag_stats)
        assert all(isinstance(g, GapEntry) for g in gaps)
        ratios = [g.ratio for g in gaps]
        assert ratios == sorted(ratios)
        assert gaps[0].tag_combination == ("Roguelite",)

    def test_handles_zero_games(self):
        tag_stats = {"Orphan": (10, 0)}
        gaps = compute_gap_analysis(tag_stats)
        assert len(gaps) == 1
        assert gaps[0].ratio == float("inf")


class TestGrowthSignals:
    def test_filters_small_growing_creators(self):
        # Use dates relative to now so test doesn't become time-sensitive
        now = datetime.now(timezone.utc)
        recent = (now - timedelta(days=1)).isoformat()
        old = (now - timedelta(days=60)).isoformat()

        creators = [
            CreatorSummary("twitch:big", "Big", "big", "twitch", 50000, 80, ()),
            CreatorSummary("twitch:small", "Small", "small", "twitch", 800, 70, ()),
            CreatorSummary("twitch:mid", "Mid", "mid", "twitch", 3000, 60, ()),
        ]
        last_active = {
            "big": recent,
            "small": recent,
            "mid": old,
        }
        signals = compute_growth_signals(
            creators, last_active=last_active, audience_cap=10000, days_recent=30
        )
        # Big is over audience cap, Mid is too old
        assert len(signals) == 1
        assert signals[0].handle == "small"
