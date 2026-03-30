from pathlib import Path

from app.reports.charts import (
    render_audience_distribution,
    render_activity_recency,
    render_top_creators_bar,
    render_tag_heatmap,
    BLOG_SIZE,
    SOCIAL_SIZE,
)
from app.reports.models import CreatorSummary


class TestConstants:
    def test_blog_size(self):
        assert BLOG_SIZE == (1200, 800)

    def test_social_size(self):
        assert SOCIAL_SIZE == (1080, 1080)


class TestAudienceDistribution:
    def test_generates_both_sizes(self, tmp_path: Path):
        audiences = [100, 500, 800, 1200, 5000, 20000]
        paths = render_audience_distribution(audiences, output_dir=tmp_path)
        assert (tmp_path / "audience_distribution_blog.png").exists()
        assert (tmp_path / "audience_distribution_social.png").exists()
        assert len(paths) == 2

    def test_returns_paths(self, tmp_path: Path):
        audiences = [100, 500, 800, 1200, 5000, 20000]
        paths = render_audience_distribution(audiences, output_dir=tmp_path)
        assert all(isinstance(p, Path) for p in paths)
        assert all(p.exists() for p in paths)


class TestActivityRecency:
    def test_generates_chart(self, tmp_path: Path):
        recency = {"30d": 0.25, "90d": 0.55, "365d": 0.88}
        paths = render_activity_recency(recency, output_dir=tmp_path)
        assert (tmp_path / "activity_recency_blog.png").exists()
        assert (tmp_path / "activity_recency_social.png").exists()

    def test_returns_two_paths(self, tmp_path: Path):
        recency = {"30d": 0.25, "90d": 0.55, "365d": 0.88}
        paths = render_activity_recency(recency, output_dir=tmp_path)
        assert len(paths) == 2


class TestTopCreatorsBar:
    def test_generates_chart(self, tmp_path: Path):
        creators = [
            CreatorSummary("twitch:a", "A", "a", "twitch", 5000, 85, ("Strategy",)),
            CreatorSummary("twitch:b", "B", "b", "twitch", 800, 65, ("Indie",)),
        ]
        paths = render_top_creators_bar(creators, output_dir=tmp_path)
        assert (tmp_path / "top_creators_blog.png").exists()
        assert (tmp_path / "top_creators_social.png").exists()

    def test_returns_two_paths(self, tmp_path: Path):
        creators = [
            CreatorSummary("twitch:a", "A", "a", "twitch", 5000, 85, ("Strategy",)),
        ]
        paths = render_top_creators_bar(creators, output_dir=tmp_path)
        assert len(paths) == 2

    def test_handles_more_than_15_creators(self, tmp_path: Path):
        creators = [
            CreatorSummary(f"twitch:{i}", f"Creator {i}", f"handle{i}", "twitch", 1000 * i, i * 4, ("Strategy",))
            for i in range(1, 21)
        ]
        paths = render_top_creators_bar(creators, output_dir=tmp_path)
        assert len(paths) == 2
        assert all(p.exists() for p in paths)


class TestTagHeatmap:
    def test_generates_chart(self, tmp_path: Path):
        tag_data = {"Strategy": 50, "Indie": 120, "Fantasy": 30, "Roguelite": 15}
        paths = render_tag_heatmap(tag_data, output_dir=tmp_path)
        assert (tmp_path / "tag_heatmap_blog.png").exists()
        assert (tmp_path / "tag_heatmap_social.png").exists()

    def test_returns_two_paths(self, tmp_path: Path):
        tag_data = {"Strategy": 50, "Indie": 120}
        paths = render_tag_heatmap(tag_data, output_dir=tmp_path)
        assert len(paths) == 2
