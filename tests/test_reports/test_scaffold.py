from app.reports.models import CreatorSummary, GapEntry, GrowthSignal, ReportStats
from app.reports.scaffold import generate_scaffold


class TestGenerateScaffold:
    def test_contains_all_sections(self):
        stats = ReportStats(
            catalog_game_slug="roguelite_strategy",
            genre_label="Roguelite / Strategy",
            total_creators=150,
            median_audience=1200,
            mean_audience=5400,
            platform_split={"twitch": 0.85},
            contact_rates={"email": 0.42},
            activity_recency={"30d": 0.25, "90d": 0.55, "365d": 0.88},
        )
        top_creators = [
            CreatorSummary("twitch:a", "StreamerA", "a", "twitch", 5000, 85, ("Strategy",)),
        ]
        gaps = [GapEntry(("roguelite",), 5, 40, 0.125)]
        growth = [GrowthSignal("NewGuy", "ng", "twitch", 800, 70, "2026-03-29")]

        md = generate_scaffold(stats=stats, top_creators=top_creators, gaps=gaps, growth_signals=growth)

        assert "Roguelite / Strategy" in md
        assert "150" in md
        assert "StreamerA" in md
        assert "roguelite" in md
        assert "NewGuy" in md
        assert "title:" in md
        assert "date:" in md

    def test_contains_chart_references(self):
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
        md = generate_scaffold(stats=stats, top_creators=[], gaps=[], growth_signals=[])
        assert "audience_distribution_blog.png" in md
        assert "activity_recency_blog.png" in md
