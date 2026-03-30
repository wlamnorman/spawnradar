"""Tests for the prospect ranking pipeline."""

from __future__ import annotations

import pytest

from app.creator_index.matching import match_creator_tags_to_game
from app.database import get_connection
from app.prospects.repository import ProspectRepository
from app.prospects.service import ProspectRankingService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insert_igdb_game(
    db_path: str,
    igdb_id: int,
    name: str,
    slug: str,
    genre_tags: list[tuple[int, str]] | None = None,
    theme_tags: list[tuple[int, str]] | None = None,
    extra_tags: list[tuple[str, int | str, str]] | None = None,
) -> None:
    """Insert an IGDB game with tags into the test database."""
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO igdb_games (
                igdb_id, name, slug, summary, first_release_date,
                platform_ids_json, platform_names_json,
                last_synced_at
            ) VALUES (?, ?, ?, NULL, NULL, '[]', '[]', datetime('now'))
            """,
            (igdb_id, name, slug),
        )
        for tag_id, tag_name in genre_tags or []:
            conn.execute(
                "INSERT INTO igdb_game_tags (igdb_id, tag_type, tag_name, tag_id) VALUES (?, 'genre', ?, ?)",
                (igdb_id, tag_name, tag_id),
            )
        for tag_id, tag_name in theme_tags or []:
            conn.execute(
                "INSERT INTO igdb_game_tags (igdb_id, tag_type, tag_name, tag_id) VALUES (?, 'theme', ?, ?)",
                (igdb_id, tag_name, tag_id),
            )
        for tag_type, tag_id, tag_name in extra_tags or []:
            conn.execute(
                "INSERT INTO igdb_game_tags (igdb_id, tag_type, tag_name, tag_id) VALUES (?, ?, ?, ?)",
                (igdb_id, tag_type, tag_name, tag_id),
            )


def _insert_creator(
    db_path: str,
    account_id: str,
    platform: str,
    display_name: str,
    handle: str | None = None,
    followers: int = 1000,
    avg_viewers: int = 100,
) -> None:
    """Insert a source account with platform profile."""
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO source_accounts (
                account_id, platform, external_id, handle_current,
                display_name_current, canonical_url,
                first_seen_at, last_seen_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'),
                      datetime('now'), datetime('now'))
            """,
            (
                account_id,
                platform,
                f"ext-{account_id}",
                handle,
                display_name,
                f"https://{platform}.example.com/{handle or account_id}",
            ),
        )
        if platform == "twitch":
            conn.execute(
                """
                INSERT INTO twitch_profiles_latest (
                    account_id, broadcaster_id, login, display_name,
                    followers_count, recent_avg_live_viewers,
                    fetched_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now', '+1 day'))
                """,
                (
                    account_id,
                    f"bid-{account_id}",
                    handle or account_id,
                    display_name,
                    followers,
                    avg_viewers,
                ),
            )
        elif platform == "youtube":
            conn.execute(
                """
                INSERT INTO youtube_channels_latest (
                    account_id, channel_id, handle, display_name,
                    subscriber_count, recent_avg_views,
                    video_count, recent_median_views, uploads_last_30d,
                    fetched_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, 50, 80, 5, datetime('now'), datetime('now', '+1 day'))
                """,
                (
                    account_id,
                    f"ch-{account_id}",
                    handle,
                    display_name,
                    followers,
                    avg_viewers,
                ),
            )


def _insert_game_play(
    db_path: str,
    account_id: str,
    game_name: str,
    igdb_game_id: int,
    platform: str = "twitch",
) -> None:
    """Insert a resolved creator game play."""
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO creator_games_played (
                account_id, game_name_raw, game_name_key, platform,
                first_seen_at, last_seen_at, observation_count, igdb_game_id
            ) VALUES (?, ?, ?, ?, datetime('now'), datetime('now'), 1, ?)
            """,
            (account_id, game_name, game_name.lower(), platform, igdb_game_id),
        )


def _insert_contact_point(
    db_path: str,
    account_id: str,
    contact_type: str,
    contact_value: str,
) -> None:
    """Insert a public contact point for a creator."""
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO contact_points (
                contact_point_id, account_id, contact_type, contact_value,
                source_kind, is_public, first_seen_at, last_seen_at, updated_at
            ) VALUES (?, ?, ?, ?, 'test', 1, datetime('now'), datetime('now'),
                      datetime('now'))
            """,
            (
                f"{account_id}-{contact_type}",
                account_id,
                contact_type,
                contact_value,
            ),
        )


def _insert_prospect_status(
    db_path: str,
    customer_game_id: str,
    account_id: str,
    status: str,
    notes: str = "",
) -> None:
    """Insert sparse workflow state for one prospect."""
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO prospect_statuses (
                customer_game_id, account_id, status, notes, updated_at
            ) VALUES (?, ?, ?, ?, datetime('now'))
            """,
            (customer_game_id, account_id, status, notes),
        )


# ---------------------------------------------------------------------------
# Scoring formula tests
# ---------------------------------------------------------------------------


class TestScoringFormula:
    """Verify the coverage-based wrapper used by ranking surfaces."""

    def test_single_matching_game_has_strong_evidence(self, sample_game):
        """One supporting game yields strong but not full evidence."""
        match = match_creator_tags_to_game(
            sample_game,
            creator_tag_counts={("genre", 9): 1},
        )
        assert match.coverage_score == pytest.approx(0.93, abs=0.01)

    def test_breadth_beats_single_match(self, sample_game):
        """More supporting games still increase coverage toward the cap."""
        single = match_creator_tags_to_game(
            sample_game,
            creator_tag_counts={("genre", 9): 1},
        )
        broad = match_creator_tags_to_game(
            sample_game,
            creator_tag_counts={("genre", 9): 3},
        )
        assert broad.coverage_score > single.coverage_score
        assert broad.coverage_score == pytest.approx(1.0)
        assert single.coverage_score == pytest.approx(0.93)

    def test_unrelated_tags_dont_penalize(self, sample_game):
        """Extra non-overlapping tags on the creator don't reduce the score."""
        focused = match_creator_tags_to_game(
            sample_game,
            creator_tag_counts={("genre", 9): 2},
        )
        diverse = match_creator_tags_to_game(
            sample_game,
            creator_tag_counts={
                ("genre", 9): 2,
                ("genre", 5): 3,  # Shooter — unrelated
                ("theme", 17): 1,  # also unrelated
            },
        )
        assert focused.coverage_score == diverse.coverage_score

    def test_no_overlap_scores_zero(self, sample_game):
        match = match_creator_tags_to_game(
            sample_game,
            creator_tag_counts={("genre", 5): 2, ("theme", 17): 1},
        )
        assert match.coverage_score == 0.0

    def test_genre_weighted_more_than_theme(
        self, game_service, registered_user
    ):
        """Genre overlap contributes 3x more than theme overlap."""
        game = game_service.create_game(
            user_id=registered_user.user_id,
            name="TagTest",
            summary="Test game with both genre and theme.",
            description="Test game.",
            website_url=None,
            igdb_genre_ids=[12],  # Role-playing
            igdb_theme_ids=[18],  # Sci-fi
        )
        # customer_total = 3*1 + 1*1 = 4
        genre_only = match_creator_tags_to_game(
            game, creator_tag_counts={("genre", 12): 1}
        )
        theme_only = match_creator_tags_to_game(
            game, creator_tag_counts={("theme", 18): 1}
        )
        assert genre_only.coverage_score == pytest.approx(0.6975)
        assert theme_only.coverage_score == pytest.approx(0.2325)


# ---------------------------------------------------------------------------
# Repository tests
# ---------------------------------------------------------------------------


class TestProspectRepository:
    def test_query_creator_tag_counts_basic(self, db_path):
        """Creator tag counts aggregate correctly from resolved game plays."""
        _insert_igdb_game(
            db_path,
            100,
            "Slay the Spire",
            "slay-the-spire",
            genre_tags=[(12, "Strategy"), (24, "Tactical")],
            theme_tags=[(18, "Sci-fi")],
        )
        _insert_igdb_game(
            db_path,
            101,
            "Into the Breach",
            "into-the-breach",
            genre_tags=[(12, "Strategy")],
            theme_tags=[(18, "Sci-fi")],
        )
        _insert_creator(db_path, "creator-1", "twitch", "StrategyFan")
        _insert_game_play(db_path, "creator-1", "Slay the Spire", 100)
        _insert_game_play(db_path, "creator-1", "Into the Breach", 101)

        repo = ProspectRepository(db_path)
        result = repo.query_creator_tag_counts(game_tags=(("genre", 12),))

        assert "creator-1" in result
        counts = result["creator-1"]
        # genre:12 appears in both games → count 2
        assert counts[("genre", 12)] == 2
        # genre:24 only in Slay the Spire → count 1
        assert counts[("genre", 24)] == 1
        # theme:18 in both → count 2
        assert counts[("theme", 18)] == 2

    def test_no_overlap_excluded(self, db_path):
        """Creators with zero overlapping tags are not returned."""
        _insert_igdb_game(
            db_path,
            100,
            "Shooter Game",
            "shooter-game",
            genre_tags=[(5, "Shooter")],
        )
        _insert_creator(db_path, "creator-1", "twitch", "ShooterFan")
        _insert_game_play(db_path, "creator-1", "Shooter Game", 100)

        repo = ProspectRepository(db_path)
        result = repo.query_creator_tag_counts(
            game_tags=(("genre", 12),),  # Strategy — no overlap
        )
        assert len(result) == 0

    def test_count_relevant_games(self, db_path):
        """Relevant game count only includes games with overlapping tags."""
        _insert_igdb_game(
            db_path, 100, "Game A", "game-a", genre_tags=[(12, "Strategy")]
        )
        _insert_igdb_game(
            db_path, 101, "Game B", "game-b", genre_tags=[(12, "Strategy")]
        )
        _insert_igdb_game(
            db_path, 102, "Game C", "game-c", genre_tags=[(5, "Shooter")]
        )  # unrelated
        _insert_creator(db_path, "creator-1", "twitch", "MixedFan")
        _insert_game_play(db_path, "creator-1", "Game A", 100)
        _insert_game_play(db_path, "creator-1", "Game B", 101)
        _insert_game_play(db_path, "creator-1", "Game C", 102)

        repo = ProspectRepository(db_path)
        counts = repo.count_relevant_games(["creator-1"], (("genre", 12),))
        assert counts["creator-1"] == 2  # only Game A and Game B

    def test_get_creator_profiles(self, db_path):
        """Profile query returns display-ready data."""
        _insert_creator(
            db_path,
            "c1",
            "twitch",
            "TestStreamer",
            handle="teststreamer",
            followers=5000,
            avg_viewers=200,
        )
        repo = ProspectRepository(db_path)
        profiles = repo.get_creator_profiles(["c1"])
        assert "c1" in profiles
        p = profiles["c1"]
        assert p.display_name == "TestStreamer"
        assert p.platform == "twitch"
        assert p.reach == 5000
        assert p.recent_audience == 200

    def test_get_creator_profiles_falls_back_to_live_viewer_count(
        self, db_path
    ):
        with get_connection(db_path) as conn:
            conn.execute(
                """
                INSERT INTO source_accounts (
                    account_id, platform, external_id, handle_current,
                    display_name_current, canonical_url,
                    first_seen_at, last_seen_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'),
                          datetime('now'), datetime('now'))
                """,
                (
                    "c2",
                    "twitch",
                    "ext-c2",
                    "liveonly",
                    "Live Only",
                    "https://twitch.example.com/liveonly",
                ),
            )
            conn.execute(
                """
                INSERT INTO twitch_profiles_latest (
                    account_id, broadcaster_id, login, display_name,
                    followers_count, viewer_count,
                    fetched_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now', '+1 day'))
                """,
                ("c2", "bid-c2", "liveonly", "Live Only", 1200, 87),
            )

        repo = ProspectRepository(db_path)
        profiles = repo.get_creator_profiles(["c2"])

        assert profiles["c2"].recent_audience == 87

    def test_get_creator_profiles_falls_back_to_twitch_vod_views(
        self, db_path
    ):
        with get_connection(db_path) as conn:
            conn.execute(
                """
                INSERT INTO source_accounts (
                    account_id, platform, external_id, handle_current,
                    display_name_current, canonical_url,
                    first_seen_at, last_seen_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'),
                          datetime('now'), datetime('now'))
                """,
                (
                    "c3",
                    "twitch",
                    "ext-c3",
                    "vodonly",
                    "VOD Only",
                    "https://twitch.example.com/vodonly",
                ),
            )
            conn.execute(
                """
                INSERT INTO twitch_profiles_latest (
                    account_id, broadcaster_id, login, display_name,
                    followers_count, recent_avg_vod_views,
                    fetched_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now', '+1 day'))
                """,
                ("c3", "bid-c3", "vodonly", "VOD Only", 2200, 143),
            )

        repo = ProspectRepository(db_path)
        profiles = repo.get_creator_profiles(["c3"])

        assert profiles["c3"].recent_audience == 143

    def test_get_prospect_workflow_states_returns_sparse_rows(self, db_path):
        _insert_creator(
            db_path, "workflow-creator", "twitch", "Workflow Creator"
        )
        with get_connection(db_path) as conn:
            conn.execute(
                """
                INSERT INTO users (user_id, email, password_hash)
                VALUES ('workflow-user', 'workflow@example.com', 'x')
                """
            )
            conn.execute(
                """
                INSERT INTO customer_games (
                    customer_game_id, user_id, name, summary, description, slug
                ) VALUES (
                    'workflow-game',
                    'workflow-user',
                    'Workflow Game',
                    'Summary',
                    'Description',
                    'workflow-game'
                )
                """
            )
        _insert_prospect_status(
            db_path,
            "workflow-game",
            "workflow-creator",
            "contacted",
            "Worth reaching out",
        )

        repo = ProspectRepository(db_path)
        states = repo.get_prospect_workflow_states(
            customer_game_id="workflow-game",
            account_ids=("workflow-creator", "missing-creator"),
        )

        assert states["workflow-creator"].status == "contacted"
        assert states["workflow-creator"].notes == "Worth reaching out"
        assert "missing-creator" not in states


# ---------------------------------------------------------------------------
# Service integration tests
# ---------------------------------------------------------------------------


class TestProspectRankingService:
    def test_breadth_creator_outranks_single_game_creator(
        self, db_path, game_service, registered_user
    ):
        """More reinforcing games can outrank a single perfect match."""
        game = game_service.create_game(
            user_id=registered_user.user_id,
            name="TactiRPG",
            summary="A tactical RPG with sci-fi themes.",
            description="A tactical RPG.",
            website_url=None,
            igdb_genre_ids=[12, 24],  # Strategy, Tactical
            igdb_theme_ids=[18],  # Sci-fi
        )

        # Perfect-match game: all 3 tags
        _insert_igdb_game(
            db_path,
            100,
            "Perfect Match",
            "perfect-match",
            genre_tags=[(12, "Strategy"), (24, "Tactical")],
            theme_tags=[(18, "Sci-fi")],
        )
        # Partial-match games: each has 1-2 overlapping tags
        _insert_igdb_game(
            db_path, 101, "Game B", "game-b", genre_tags=[(12, "Strategy")]
        )
        _insert_igdb_game(
            db_path, 102, "Game C", "game-c", genre_tags=[(24, "Tactical")]
        )
        _insert_igdb_game(
            db_path,
            103,
            "Game D",
            "game-d",
            genre_tags=[(12, "Strategy")],
            theme_tags=[(18, "Sci-fi")],
        )
        _insert_igdb_game(
            db_path,
            104,
            "Game E",
            "game-e",
            genre_tags=[(24, "Tactical")],
            theme_tags=[(18, "Sci-fi")],
        )

        # Creator A: 1 perfect game
        _insert_creator(
            db_path,
            "narrow",
            "twitch",
            "NarrowGamer",
            followers=1000,
            avg_viewers=100,
        )
        _insert_game_play(db_path, "narrow", "Perfect Match", 100)

        # Creator B: 4 partial games
        _insert_creator(
            db_path,
            "broad",
            "twitch",
            "BroadGamer",
            followers=1000,
            avg_viewers=100,
        )
        _insert_game_play(db_path, "broad", "Game B", 101)
        _insert_game_play(db_path, "broad", "Game C", 102)
        _insert_game_play(db_path, "broad", "Game D", 103)
        _insert_game_play(db_path, "broad", "Game E", 104)

        service = ProspectRankingService(db_path)
        prospects, total, _ = service.rank_prospects(game)

        assert len(prospects) == 2
        assert prospects[0].profile.account_id == "broad"
        assert prospects[1].profile.account_id == "narrow"
        assert prospects[0].coverage_score > prospects[1].coverage_score
        assert prospects[0].coverage_score == pytest.approx(0.967)
        assert prospects[1].coverage_score == pytest.approx(0.93)
        assert prospects[0].relevant_game_count == 4
        assert prospects[1].relevant_game_count == 1

    def test_empty_when_no_creators(
        self, db_path, game_service, registered_user
    ):
        game = game_service.create_game(
            user_id=registered_user.user_id,
            name="LonelyGame",
            summary="No creators play similar games.",
            description="No matching creators.",
            website_url=None,
            igdb_genre_ids=[9],  # Puzzle
        )
        service = ProspectRankingService(db_path)
        assert service.rank_prospects(game) == (
            [],
            0,
            {
                "new": 0,
                "contacted": 0,
                "replied": 0,
                "access_shared": 0,
                "covered": 0,
                "not_pursuing": 0,
            },
        )

    def test_same_game_multiple_sessions_no_inflation(
        self, db_path, game_service, registered_user
    ):
        """Playing the same game multiple times does not inflate tag counts."""
        game = game_service.create_game(
            user_id=registered_user.user_id,
            name="TestGame",
            summary="Test scoring.",
            description="Test.",
            website_url=None,
            igdb_genre_ids=[12],
        )
        _insert_igdb_game(
            db_path,
            100,
            "Only Game",
            "only-game",
            genre_tags=[(12, "Strategy")],
        )
        _insert_creator(db_path, "c1", "twitch", "OneGameAndy")
        # Even if observation_count is high, it's still 1 distinct game
        with get_connection(db_path) as conn:
            conn.execute(
                """
                INSERT INTO creator_games_played (
                    account_id, game_name_raw, game_name_key, platform,
                    first_seen_at, last_seen_at, observation_count, igdb_game_id
                ) VALUES (?, ?, ?, ?, datetime('now'), datetime('now'), 50, ?)
                """,
                ("c1", "Only Game", "only game", "twitch", 100),
            )

        service = ProspectRankingService(db_path)
        prospects, total, _ = service.rank_prospects(game)
        assert len(prospects) == 1
        # One matching distinct game gives strong but not complete evidence.
        assert prospects[0].coverage_score == pytest.approx(0.93, abs=0.01)

    def test_keyword_derived_tags_count_as_genre_theme_and_mechanic(
        self, db_path, game_service, registered_user
    ):
        game = game_service.create_game(
            user_id=registered_user.user_id,
            name="Keyword Fusion",
            summary="A cozy roguelike with crafting.",
            description="A cozy roguelike with crafting.",
            website_url=None,
            igdb_genre_ids=[12],
            igdb_theme_ids=[18],
            igdb_keyword_ids=["roguelike", "cozy", "crafting"],
        )
        _insert_igdb_game(
            db_path,
            100,
            "Keyword Match",
            "keyword-match",
            genre_tags=[(12, "Role-playing (RPG)")],
            theme_tags=[(18, "Science fiction")],
            extra_tags=[
                ("genre", "roguelike", "Roguelike"),
                ("theme", "cozy", "Cozy"),
                ("mechanic", "crafting", "Crafting"),
            ],
        )
        _insert_creator(db_path, "bucketed", "twitch", "BucketedTags")
        _insert_game_play(db_path, "bucketed", "Keyword Match", 100)

        prospects, total, _ = ProspectRankingService(db_path).rank_prospects(
            game
        )

        assert len(prospects) == 1
        assert prospects[0].overlap_tags == (
            ("genre", 12),
            ("genre", "roguelike"),
            ("mechanic", "crafting"),
            ("theme", 18),
            ("theme", "cozy"),
        )
        assert prospects[0].coverage_score == pytest.approx(0.93, abs=0.01)

    def test_rank_prospects_applies_reach_and_overlap_filters(
        self, db_path, game_service, registered_user
    ):
        game = game_service.create_game(
            user_id=registered_user.user_id,
            name="Filtered Game",
            summary="Turn-based strategy",
            description="Turn-based strategy",
            website_url=None,
            igdb_genre_ids=[12],
        )
        _insert_igdb_game(
            db_path,
            100,
            "Strong Match A",
            "strong-match-a",
            genre_tags=[(12, "Role-playing (RPG)")],
        )
        _insert_igdb_game(
            db_path,
            101,
            "Strong Match B",
            "strong-match-b",
            genre_tags=[(12, "Role-playing (RPG)")],
        )
        _insert_creator(
            db_path,
            "strong",
            "twitch",
            "Strong Creator",
            followers=5000,
            avg_viewers=200,
        )
        _insert_game_play(db_path, "strong", "Strong Match A", 100)
        _insert_game_play(db_path, "strong", "Strong Match B", 101)

        _insert_creator(
            db_path,
            "weak",
            "twitch",
            "Weak Creator",
            followers=500,
            avg_viewers=80,
        )
        _insert_game_play(db_path, "weak", "Strong Match A", 100)

        prospects, total, _ = ProspectRankingService(db_path).rank_prospects(
            game,
            min_reach=1000,
            max_reach=10000,
            min_overlap_score=0.95,
            max_overlap_score=1.0,
        )

        assert total == 1
        assert len(prospects) == 1
        assert prospects[0].profile.account_id == "strong"
        assert prospects[0].coverage_score == pytest.approx(0.967, abs=0.01)

    def test_rank_prospects_applies_reach_and_overlap_max_filters(
        self, db_path, game_service, registered_user
    ):
        game = game_service.create_game(
            user_id=registered_user.user_id,
            name="Strategy Match",
            summary="Strategy match summary",
            description="Strategy match description",
            website_url=None,
            igdb_genre_ids=[12],
        )
        _insert_igdb_game(
            db_path,
            200,
            "Max Match A",
            "max-match-a",
            genre_tags=[(12, "Role-playing (RPG)")],
        )
        _insert_igdb_game(
            db_path,
            201,
            "Max Match B",
            "max-match-b",
            genre_tags=[(12, "Role-playing (RPG)")],
        )
        _insert_creator(
            db_path,
            "high-reach",
            "twitch",
            "High Reach Creator",
            followers=500_000,
            avg_viewers=200,
        )
        _insert_game_play(db_path, "high-reach", "Max Match A", 200)
        _insert_game_play(db_path, "high-reach", "Max Match B", 201)
        _insert_creator(
            db_path,
            "mid-reach",
            "twitch",
            "Mid Reach Creator",
            followers=50_000,
            avg_viewers=120,
        )
        _insert_game_play(db_path, "mid-reach", "Max Match A", 200)

        prospects, total, _ = ProspectRankingService(db_path).rank_prospects(
            game,
            max_reach=100_000,
            min_overlap_score=0.0,
            max_overlap_score=0.95,
        )

        assert total == 1
        assert len(prospects) == 1
        assert prospects[0].profile.account_id == "mid-reach"

    def test_rank_prospects_applies_min_relevant_games_filter(
        self, db_path, game_service, registered_user
    ):
        game = game_service.create_game(
            user_id=registered_user.user_id,
            name="Relevant Count Game",
            summary="Sci-fi tactics",
            description="Sci-fi tactics",
            website_url=None,
            igdb_genre_ids=[12],
            igdb_theme_ids=[18],
        )
        _insert_igdb_game(
            db_path,
            300,
            "Match One",
            "match-one",
            genre_tags=[(12, "Role-playing (RPG)")],
        )
        _insert_igdb_game(
            db_path,
            301,
            "Match Two",
            "match-two",
            theme_tags=[(18, "Science fiction")],
        )
        _insert_creator(db_path, "one-game", "twitch", "OneGame")
        _insert_creator(db_path, "two-games", "twitch", "TwoGames")
        _insert_game_play(db_path, "one-game", "Match One", 300)
        _insert_game_play(db_path, "two-games", "Match One", 300)
        _insert_game_play(db_path, "two-games", "Match Two", 301)

        prospects, total, _ = ProspectRankingService(db_path).rank_prospects(
            game,
            min_relevant_games=2,
        )

        assert total == 1
        assert len(prospects) == 1
        assert prospects[0].profile.account_id == "two-games"
        assert prospects[0].relevant_game_count == 2

    def test_rank_prospects_applies_reachable_via_filter_with_or_semantics(
        self, db_path, game_service, registered_user
    ):
        game = game_service.create_game(
            user_id=registered_user.user_id,
            name="Contact Filter Game",
            summary="Sci-fi tactics",
            description="Sci-fi tactics",
            website_url=None,
            igdb_genre_ids=[12],
        )
        _insert_igdb_game(
            db_path,
            400,
            "Shared Match",
            "shared-match",
            genre_tags=[(12, "Role-playing (RPG)")],
        )
        _insert_creator(db_path, "email-creator", "twitch", "EmailCreator")
        _insert_creator(db_path, "discord-creator", "twitch", "DiscordCreator")
        _insert_game_play(db_path, "email-creator", "Shared Match", 400)
        _insert_game_play(db_path, "discord-creator", "Shared Match", 400)
        _insert_contact_point(
            db_path,
            "email-creator",
            "email",
            "creator@example.com",
        )
        _insert_contact_point(
            db_path,
            "discord-creator",
            "discord",
            "https://discord.gg/example",
        )

        prospects, total, _ = ProspectRankingService(db_path).rank_prospects(
            game,
            contact_methods=("email", "discord"),
        )

        assert total == 2
        assert len(prospects) == 2
        assert {prospect.profile.account_id for prospect in prospects} == {
            "email-creator",
            "discord-creator",
        }

    def test_rank_prospects_applies_max_relevant_games_filter(
        self, db_path, game_service, registered_user
    ):
        game = game_service.create_game(
            user_id=registered_user.user_id,
            name="Max Relevant Count Game",
            summary="Sci-fi tactics",
            description="Sci-fi tactics",
            website_url=None,
            igdb_genre_ids=[12],
            igdb_theme_ids=[18],
        )
        _insert_igdb_game(
            db_path,
            500,
            "Relevant One",
            "relevant-one",
            genre_tags=[(12, "Role-playing (RPG)")],
        )
        _insert_igdb_game(
            db_path,
            501,
            "Relevant Two",
            "relevant-two",
            theme_tags=[(18, "Science fiction")],
        )
        _insert_creator(db_path, "one-game-max", "twitch", "OneGameMax")
        _insert_creator(db_path, "two-games-max", "twitch", "TwoGamesMax")
        _insert_game_play(db_path, "one-game-max", "Relevant One", 500)
        _insert_game_play(db_path, "two-games-max", "Relevant One", 500)
        _insert_game_play(db_path, "two-games-max", "Relevant Two", 501)

        prospects, total, _ = ProspectRankingService(db_path).rank_prospects(
            game,
            max_relevant_games=1,
        )

        assert total == 1
        assert len(prospects) == 1
        assert prospects[0].profile.account_id == "one-game-max"
        assert prospects[0].relevant_game_count == 1

    def test_rank_prospects_excludes_not_pursuing_from_all(
        self, db_path, game_service, registered_user
    ):
        game = game_service.create_game(
            user_id=registered_user.user_id,
            name="Workflow Prospect Game",
            summary="Tactical RPG",
            description="Tactical RPG",
            website_url=None,
            igdb_genre_ids=[12],
        )
        _insert_igdb_game(
            db_path,
            900,
            "Workflow Match",
            "workflow-match",
            genre_tags=[(12, "Role-playing (RPG)")],
        )
        _insert_creator(
            db_path, "creator-visible", "twitch", "Visible Creator"
        )
        _insert_creator(db_path, "creator-hidden", "twitch", "Hidden Creator")
        _insert_game_play(db_path, "creator-visible", "Workflow Match", 900)
        _insert_game_play(db_path, "creator-hidden", "Workflow Match", 900)
        _insert_prospect_status(
            db_path,
            game.customer_game_id,
            "creator-hidden",
            "not_pursuing",
        )

        prospects, total, status_counts = ProspectRankingService(
            db_path
        ).rank_prospects(game)

        assert total == 1
        assert [p.profile.account_id for p in prospects] == ["creator-visible"]
        assert status_counts["new"] == 1
        assert status_counts["not_pursuing"] == 1

    def test_rank_prospects_filters_by_status(
        self, db_path, game_service, registered_user
    ):
        game = game_service.create_game(
            user_id=registered_user.user_id,
            name="Workflow Status Filter Game",
            summary="Tactical RPG",
            description="Tactical RPG",
            website_url=None,
            igdb_genre_ids=[12],
        )
        _insert_igdb_game(
            db_path,
            901,
            "Workflow Status Match",
            "workflow-status-match",
            genre_tags=[(12, "Role-playing (RPG)")],
        )
        _insert_creator(db_path, "creator-new", "twitch", "New Creator")
        _insert_creator(
            db_path, "creator-contacted", "twitch", "Contacted Creator"
        )
        _insert_game_play(db_path, "creator-new", "Workflow Status Match", 901)
        _insert_game_play(
            db_path, "creator-contacted", "Workflow Status Match", 901
        )
        _insert_prospect_status(
            db_path,
            game.customer_game_id,
            "creator-contacted",
            "contacted",
        )

        prospects, total, status_counts = ProspectRankingService(
            db_path
        ).rank_prospects(game, status_filter="contacted")

        assert total == 1
        assert [p.profile.account_id for p in prospects] == [
            "creator-contacted"
        ]
        assert prospects[0].workflow.status == "contacted"
        assert status_counts["new"] == 1
        assert status_counts["contacted"] == 1
