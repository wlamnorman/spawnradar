import json
from pathlib import Path

from app.reports.pipeline import run_genre_report, run_data_check


_CATALOG_JSON = (
    '{"customer_game_name": "Test Roguelite",'
    '"baseline_summary": "A test game",'
    '"broad_igdb_genres": [{"id": 15, "label": "Strategy"}, {"id": 32, "label": "Indie"}],'
    '"broad_igdb_themes": [{"id": 17, "label": "Fantasy"}],'
    '"required_game_modes": [],'
    '"extra_custom_tags": [],'
    '"anchor_games": []}'
)


class TestRunDataCheck:
    def test_reports_creator_count(self, seeded_db: str, tmp_path: Path):
        catalog_json = tmp_path / "roguelite.json"
        catalog_json.write_text(_CATALOG_JSON)
        result = run_data_check(seeded_db, catalog_json)
        assert "creator_count" in result
        assert isinstance(result["creator_count"], int)
        assert "sufficient" in result


class TestRunGenreReport:
    def test_creates_output_bundle(self, seeded_db: str, tmp_path: Path):
        catalog_json = tmp_path / "roguelite.json"
        catalog_json.write_text(_CATALOG_JSON)
        output_dir = tmp_path / "output"
        run_genre_report(seeded_db, catalog_json, output_dir=output_dir)

        assert (output_dir / "stats.json").exists()
        assert (output_dir / "top_creators.json").exists()
        assert (output_dir / "gap_analysis.json").exists()
        assert (output_dir / "growth_signals.json").exists()
        assert (output_dir / "report_scaffold.md").exists()
        assert (output_dir / "charts").is_dir()

        stats = json.loads((output_dir / "stats.json").read_text())
        assert stats["total_creators"] >= 1
        assert stats["catalog_game_slug"] is not None

    def test_scaffold_contains_frontmatter(self, seeded_db: str, tmp_path: Path):
        catalog_json = tmp_path / "roguelite.json"
        catalog_json.write_text(_CATALOG_JSON)
        output_dir = tmp_path / "output"
        run_genre_report(seeded_db, catalog_json, output_dir=output_dir)
        scaffold = (output_dir / "report_scaffold.md").read_text()
        assert "title:" in scaffold
