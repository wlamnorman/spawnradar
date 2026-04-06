"""Tests for v2 matching functions (coverage, overlap, evidence)."""

from __future__ import annotations

import pytest

from app.creator_index.matching import (
    GENRE_WEIGHT,
    MECHANIC_WEIGHT,
    THEME_WEIGHT,
    TagCounts,
    compute_coverage,
    compute_overlap,
    customer_game_tag_counts,
    tag_weight,
)
from app.games.models import CustomerGame
from app.igdb.taxonomy import canonical_keyword_for_igdb_name

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_GAME_DEFAULTS = {
    "customer_game_id": "g1",
    "workspace_id": "u1",
    "name": "Test Game",
    "summary": None,
    "description": "",
    "website_url": None,
    "status": "active",
    "slug": "test-game",
    "created_at": "2026-01-01T00:00:00Z",
    "updated_at": "2026-01-01T00:00:00Z",
}


def _game(**overrides) -> CustomerGame:
    return CustomerGame(**{**_GAME_DEFAULTS, **overrides})


# ---------------------------------------------------------------------------
# tag_weight for unified buckets
# ---------------------------------------------------------------------------


class TestTagWeights:
    def test_genre_keyword_uses_genre_weight(self):
        assert tag_weight(("genre", "roguelike")) == GENRE_WEIGHT

    def test_genre_weight_unchanged(self):
        assert tag_weight(("genre", 1)) == GENRE_WEIGHT

    def test_theme_weight_unchanged(self):
        assert tag_weight(("theme", 1)) == THEME_WEIGHT

    def test_mechanic_weight(self):
        assert tag_weight(("mechanic", "crafting")) == MECHANIC_WEIGHT


# ---------------------------------------------------------------------------
# customer_game_tag_counts buckets curated tags
# ---------------------------------------------------------------------------


class TestCustomerGameTagCountsKeywords:
    def test_customer_game_tag_counts_buckets_curated_tags(self):
        game = _game(
            igdb_genre_ids=[1, 2],
            igdb_theme_ids=[10],
            igdb_keyword_ids=["roguelike", "cozy", "crafting"],
        )
        counts = customer_game_tag_counts(game)
        assert ("genre", "roguelike") in counts
        assert ("theme", "cozy") in counts
        assert ("mechanic", "crafting") in counts
        assert counts[("genre", "roguelike")] == 1
        assert counts[("genre", 1)] == 1
        assert counts[("theme", 10)] == 1

    def test_no_keywords_still_works(self):
        game = _game(igdb_genre_ids=[1], igdb_theme_ids=[10])
        counts = customer_game_tag_counts(game)
        assert len(counts) == 2
        assert ("genre", 1) in counts
        assert ("theme", 10) in counts

    def test_platformer_variants_are_not_curated_keywords(self):
        assert canonical_keyword_for_igdb_name("2d platformer") is None
        assert canonical_keyword_for_igdb_name("3d platformer") is None

    def test_sparse_keywords_are_not_curated_keywords(self):
        assert canonical_keyword_for_igdb_name("logic puzzle") is None
        assert canonical_keyword_for_igdb_name("narrative adventure") is None


# ---------------------------------------------------------------------------
# compute_coverage worked example for the current evidence curve
# ---------------------------------------------------------------------------


class TestCoverageWorkedExample:
    def test_coverage_worked_example(self):
        """Check the weighted coverage result for the current evidence curve.

        Target tags (using int ids as stand-ins):
          strategy (genre 1) -> weight 3
          turn-based strategy (genre 2) -> weight 3
          science fiction (theme 10) -> weight 1
          roguelike (genre "roguelike") -> weight 3
        Total target weight = 10

        Creator evidence:
          strategy: enough games -> evidence 1.0  (count=3)
          turn-based strategy: two games -> evidence 0.967 (count=2)
          science fiction: enough games -> evidence 1.0 (count=3)
          roguelike: one game -> evidence 0.93 (count=1)

        overlap_weight = 3*1.0 + 3*0.967 + 1*1.0 + 3*0.93 = 9.691
        coverage = 9.691 / 10.0 = 0.9691
        """
        game = _game(
            igdb_genre_ids=[1, 2],
            igdb_theme_ids=[10],
            igdb_keyword_ids=["roguelike"],
        )

        creator_tag_counts = {
            ("genre", 1): 3,  # strategy -> evidence 1.0
            ("genre", 2): 2,  # turn-based strategy -> evidence 0.967
            ("theme", 10): 3,  # science fiction -> evidence 1.0
            ("genre", "roguelike"): 1,  # roguelike -> evidence 0.93
        }

        coverage = compute_coverage(game, creator_tag_counts)
        assert coverage == pytest.approx(0.9691, abs=0.01)

    def test_coverage_empty_customer_tags(self):
        game = _game(igdb_genre_ids=[], igdb_theme_ids=[], igdb_keyword_ids=[])
        creator_tag_counts: TagCounts = {("genre", 1): 3}
        assert compute_coverage(game, creator_tag_counts) == 0.0

    def test_coverage_empty_creator_tags(self):
        game = _game(igdb_genre_ids=[1], igdb_theme_ids=[10])
        assert compute_coverage(game, {}) == 0.0


# ---------------------------------------------------------------------------
# compute_overlap worked example for the current evidence curve
# ---------------------------------------------------------------------------


class TestOverlapWorkedExample:
    def test_overlap_worked_example(self):
        """Check overlap for the current evidence curve.

        Same target and creator evidence as coverage example.
        overlap_weight = 9.691

        Creator also has non-target tags:
          horror (theme 20): evidence 1.0 (count=3), weight 1
          soulslike (genre 3): evidence 0.967 (count=2), weight 3
          survival (theme 21): evidence 1.0 (count=3), weight 1

        creator_relevant_weight =
          3*1.0 + 3*0.967 + 1*1.0 + 3*0.93 +  (target tags)
          1*1.0 + 3*0.967 + 1*1.0              (non-target tags)
        = 9.691 + 1 + 2.901 + 1 = 14.592

        overlap = 9.691 / 14.592 = 0.664
        """
        game = _game(
            igdb_genre_ids=[1, 2],
            igdb_theme_ids=[10],
            igdb_keyword_ids=["roguelike"],
        )

        # Tag counts for target tags
        creator_tag_counts = {
            ("genre", 1): 3,
            ("genre", 2): 2,
            ("theme", 10): 3,
            ("genre", "roguelike"): 1,
        }

        # All tag counts (target + non-target)
        creator_all_tag_counts = {
            ("genre", 1): 3,
            ("genre", 2): 2,
            ("theme", 10): 3,
            ("genre", "roguelike"): 1,
            ("theme", 20): 3,  # horror
            ("genre", 3): 2,  # soulslike
            ("theme", 21): 3,  # survival
        }

        overlap = compute_overlap(
            game, creator_tag_counts, creator_all_tag_counts
        )
        assert overlap == pytest.approx(0.664, abs=0.01)

    def test_overlap_empty_all_tags(self):
        game = _game(igdb_genre_ids=[1])
        creator_tag_counts: TagCounts = {("genre", 1): 2}
        assert compute_overlap(game, creator_tag_counts, {}) == 0.0

    def test_overlap_empty_target(self):
        game = _game(igdb_genre_ids=[], igdb_theme_ids=[])
        all_tags: TagCounts = {("genre", 1): 3}
        assert compute_overlap(game, {}, all_tags) == 0.0
