from pathlib import Path

from app.creator_index.catalog import load_catalog_game
from app.reports.models import CreatorSummary
from app.reports.scoring import score_creators_for_game


class TestScoreCreators:
    def test_returns_sorted_creator_summaries(self, seeded_db: str, tmp_path: Path):
        catalog_json = tmp_path / "roguelite.json"
        catalog_json.write_text(
            '{"customer_game_name": "Test Roguelite",'
            '"baseline_summary": "A test game",'
            '"broad_igdb_genres": [{"id": 15, "label": "Strategy"}, {"id": 32, "label": "Indie"}],'
            '"broad_igdb_themes": [{"id": 17, "label": "Fantasy"}],'
            '"required_game_modes": [],'
            '"extra_custom_tags": [],'
            '"anchor_games": []}'
        )
        game = load_catalog_game(catalog_json)
        creators = score_creators_for_game(seeded_db, game)

        assert len(creators) >= 1
        assert all(isinstance(c, CreatorSummary) for c in creators)
        scores = [c.relevance_score for c in creators]
        assert scores == sorted(scores, reverse=True)
        assert all(0 <= s <= 100 for s in scores)

    def test_streamer_a_ranks_higher_than_b(self, seeded_db: str, tmp_path: Path):
        catalog_json = tmp_path / "roguelite.json"
        catalog_json.write_text(
            '{"customer_game_name": "Test Roguelite",'
            '"baseline_summary": "A test game",'
            '"broad_igdb_genres": [{"id": 15, "label": "Strategy"}, {"id": 32, "label": "Indie"}],'
            '"broad_igdb_themes": [{"id": 17, "label": "Fantasy"}],'
            '"required_game_modes": [],'
            '"extra_custom_tags": [],'
            '"anchor_games": []}'
        )
        game = load_catalog_game(catalog_json)
        creators = score_creators_for_game(seeded_db, game)

        by_handle = {c.handle: c for c in creators}
        # streamer_a plays 2 matching games, streamer_b plays 1
        assert by_handle["streamer_a"].relevance_score >= by_handle["streamer_b"].relevance_score
