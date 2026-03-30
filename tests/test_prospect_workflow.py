"""Integration tests for the prospect CRM workflow system.

Tests the full lifecycle: status changes, filtering by status,
notes, sparse storage, status counts, and edge cases.
"""

from __future__ import annotations

from app.database import get_connection
from app.prospects.models import ProspectWorkflowStatus
from app.prospects.repository import ProspectRepository
from app.prospects.service import ProspectRankingService

# ---------------------------------------------------------------------------
# Helpers (reuse pattern from test_prospects.py)
# ---------------------------------------------------------------------------


def _insert_igdb_game(
    db_path: str,
    igdb_id: int,
    name: str,
    genre_tags: list[tuple[int, str]] | None = None,
) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO igdb_games (
                igdb_id, name, slug, summary, first_release_date,
                platform_ids_json, platform_names_json, last_synced_at
            ) VALUES (?, ?, ?, NULL, NULL, '[]', '[]', datetime('now'))
            """,
            (igdb_id, name, name.lower().replace(" ", "-")),
        )
        for tag_id, tag_name in genre_tags or []:
            conn.execute(
                "INSERT INTO igdb_game_tags (igdb_id, tag_type, tag_name, tag_id) "
                "VALUES (?, 'genre', ?, ?)",
                (igdb_id, tag_name, tag_id),
            )


def _insert_creator(
    db_path: str, account_id: str, display_name: str,
    followers: int = 1000,
) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO source_accounts (
                account_id, platform, external_id, handle_current,
                display_name_current, canonical_url,
                first_seen_at, last_seen_at, created_at, updated_at
            ) VALUES (?, 'twitch', ?, ?, ?, ?,
                      datetime('now'), datetime('now'),
                      datetime('now'), datetime('now'))
            """,
            (account_id, f"ext-{account_id}", account_id,
             display_name, f"https://twitch.tv/{account_id}"),
        )
        conn.execute(
            """
            INSERT INTO twitch_profiles_latest (
                account_id, broadcaster_id, login, display_name,
                followers_count, recent_avg_live_viewers,
                fetched_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, 100,
                      datetime('now'), datetime('now', '+1 day'))
            """,
            (account_id, f"bid-{account_id}", account_id,
             display_name, followers),
        )


def _insert_game_play(
    db_path: str, account_id: str, game_name: str, igdb_game_id: int,
) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO creator_games_played (
                account_id, game_name_raw, game_name_key, platform,
                first_seen_at, last_seen_at, observation_count, igdb_game_id
            ) VALUES (?, ?, ?, 'twitch', datetime('now'), datetime('now'), 1, ?)
            """,
            (account_id, game_name, game_name.lower(), igdb_game_id),
        )


def _setup_game_with_creators(
    db_path: str, game_service, registered_user, *, num_creators: int = 5
):
    """Create a game and N creators that match it."""
    game = game_service.create_game(
        user_id=registered_user.user_id,
        name="Workflow Test Game",
        summary="A tactical RPG for testing.",
        description="A tactical RPG for testing workflows.",
        website_url=None,
        igdb_genre_ids=[12],  # RPG
    )
    _insert_igdb_game(db_path, 800, "RPG Match", genre_tags=[(12, "RPG")])

    creator_ids = []
    for i in range(num_creators):
        cid = f"creator-{i}"
        _insert_creator(db_path, cid, f"Creator {i}", followers=1000 + i * 100)
        _insert_game_play(db_path, cid, "RPG Match", 800)
        creator_ids.append(cid)

    return game, creator_ids


# ---------------------------------------------------------------------------
# Repository tests
# ---------------------------------------------------------------------------


class TestProspectWorkflowRepository:
    """Test the prospect_statuses table operations."""

    def test_default_state_for_unknown_prospect(self, db_path):
        """Prospects without a row are implicitly 'new'."""
        repo = ProspectRepository(db_path)
        states = repo.get_prospect_workflow_states(
            customer_game_id="nonexistent",
            account_ids=("nonexistent-creator",),
        )
        assert "nonexistent-creator" not in states

    def test_upsert_creates_new_status(self, db_path, game_service, registered_user):
        game, creator_ids = _setup_game_with_creators(
            db_path, game_service, registered_user, num_creators=1,
        )
        repo = ProspectRepository(db_path)

        result = repo.upsert_prospect_workflow_state(
            customer_game_id=game.customer_game_id,
            account_id=creator_ids[0],
            status="contacted",
            notes="",
        )

        assert result.status == "contacted"
        assert result.notes == ""

    def test_upsert_updates_existing_status(self, db_path, game_service, registered_user):
        game, creator_ids = _setup_game_with_creators(
            db_path, game_service, registered_user, num_creators=1,
        )
        repo = ProspectRepository(db_path)

        repo.upsert_prospect_workflow_state(
            customer_game_id=game.customer_game_id,
            account_id=creator_ids[0],
            status="contacted",
            notes="",
        )
        result = repo.upsert_prospect_workflow_state(
            customer_game_id=game.customer_game_id,
            account_id=creator_ids[0],
            status="replied",
            notes="They said yes!",
        )

        assert result.status == "replied"
        assert result.notes == "They said yes!"

    def test_upsert_back_to_new_deletes_row(self, db_path, game_service, registered_user):
        """Setting status back to 'new' with no notes removes the row (sparse storage)."""
        game, creator_ids = _setup_game_with_creators(
            db_path, game_service, registered_user, num_creators=1,
        )
        repo = ProspectRepository(db_path)

        repo.upsert_prospect_workflow_state(
            customer_game_id=game.customer_game_id,
            account_id=creator_ids[0],
            status="contacted",
            notes="",
        )
        repo.upsert_prospect_workflow_state(
            customer_game_id=game.customer_game_id,
            account_id=creator_ids[0],
            status="new",
            notes="",
        )

        states = repo.get_prospect_workflow_states(
            customer_game_id=game.customer_game_id,
            account_ids=(creator_ids[0],),
        )
        # Row deleted — not in states dict
        assert creator_ids[0] not in states

    def test_upsert_new_with_notes_keeps_row(self, db_path, game_service, registered_user):
        """Status 'new' but with notes should keep the row."""
        game, creator_ids = _setup_game_with_creators(
            db_path, game_service, registered_user, num_creators=1,
        )
        repo = ProspectRepository(db_path)

        result = repo.upsert_prospect_workflow_state(
            customer_game_id=game.customer_game_id,
            account_id=creator_ids[0],
            status="new",
            notes="Interesting creator",
        )

        assert result.status == "new"
        assert result.notes == "Interesting creator"

        states = repo.get_prospect_workflow_states(
            customer_game_id=game.customer_game_id,
            account_ids=(creator_ids[0],),
        )
        assert creator_ids[0] in states

    def test_get_states_batch(self, db_path, game_service, registered_user):
        """Batch fetch returns only stored states."""
        game, creator_ids = _setup_game_with_creators(
            db_path, game_service, registered_user, num_creators=3,
        )
        repo = ProspectRepository(db_path)

        repo.upsert_prospect_workflow_state(
            customer_game_id=game.customer_game_id,
            account_id=creator_ids[0],
            status="contacted",
            notes="",
        )
        repo.upsert_prospect_workflow_state(
            customer_game_id=game.customer_game_id,
            account_id=creator_ids[2],
            status="replied",
            notes="Great fit",
        )

        states = repo.get_prospect_workflow_states(
            customer_game_id=game.customer_game_id,
            account_ids=tuple(creator_ids),
        )

        assert states[creator_ids[0]].status == "contacted"
        assert states[creator_ids[2]].status == "replied"
        assert states[creator_ids[2]].notes == "Great fit"
        # creator_ids[1] has no row — not in states
        assert creator_ids[1] not in states

    def test_count_workflow_statuses(self, db_path, game_service, registered_user):
        game, creator_ids = _setup_game_with_creators(
            db_path, game_service, registered_user, num_creators=5,
        )
        repo = ProspectRepository(db_path)

        repo.upsert_prospect_workflow_state(
            customer_game_id=game.customer_game_id,
            account_id=creator_ids[0],
            status="contacted",
            notes="",
        )
        repo.upsert_prospect_workflow_state(
            customer_game_id=game.customer_game_id,
            account_id=creator_ids[1],
            status="contacted",
            notes="",
        )
        repo.upsert_prospect_workflow_state(
            customer_game_id=game.customer_game_id,
            account_id=creator_ids[2],
            status="replied",
            notes="",
        )

        counts = repo.count_workflow_statuses(
            customer_game_id=game.customer_game_id,
            account_ids=tuple(creator_ids),
        )

        assert counts["contacted"] == 2
        assert counts["replied"] == 1
        # Other statuses should be 0 or absent
        assert counts.get("covered", 0) == 0


# ---------------------------------------------------------------------------
# Service-level tests
# ---------------------------------------------------------------------------


class TestProspectWorkflowService:
    """Test workflow operations through ProspectRankingService."""

    def test_prospects_include_workflow_state(
        self, db_path, game_service, registered_user,
    ):
        """Each prospect in the ranked list includes its workflow state."""
        game, creator_ids = _setup_game_with_creators(
            db_path, game_service, registered_user, num_creators=2,
        )
        repo = ProspectRepository(db_path)
        repo.upsert_prospect_workflow_state(
            customer_game_id=game.customer_game_id,
            account_id=creator_ids[0],
            status="contacted",
            notes="Emailed Tuesday",
        )

        service = ProspectRankingService(db_path)
        prospects, total, status_counts = service.rank_prospects(game)

        contacted = [p for p in prospects if p.workflow.status == "contacted"]
        new = [p for p in prospects if p.workflow.status == "new"]

        assert len(contacted) == 1
        assert contacted[0].workflow.notes == "Emailed Tuesday"
        assert len(new) == 1

    def test_status_filter_all_excludes_not_pursuing(
        self, db_path, game_service, registered_user,
    ):
        """The 'all' filter hides 'not_pursuing' prospects."""
        game, creator_ids = _setup_game_with_creators(
            db_path, game_service, registered_user, num_creators=3,
        )
        repo = ProspectRepository(db_path)
        repo.upsert_prospect_workflow_state(
            customer_game_id=game.customer_game_id,
            account_id=creator_ids[0],
            status="not_pursuing",
            notes="",
        )

        service = ProspectRankingService(db_path)
        prospects, total, status_counts = service.rank_prospects(
            game, status_filter="all",
        )

        ids = [p.profile.account_id for p in prospects]
        assert creator_ids[0] not in ids
        assert total == 2  # 3 total minus 1 not_pursuing

    def test_status_filter_not_pursuing_shows_only_hidden(
        self, db_path, game_service, registered_user,
    ):
        """Explicitly filtering 'not_pursuing' shows only those."""
        game, creator_ids = _setup_game_with_creators(
            db_path, game_service, registered_user, num_creators=3,
        )
        repo = ProspectRepository(db_path)
        repo.upsert_prospect_workflow_state(
            customer_game_id=game.customer_game_id,
            account_id=creator_ids[0],
            status="not_pursuing",
            notes="",
        )

        service = ProspectRankingService(db_path)
        prospects, total, status_counts = service.rank_prospects(
            game, status_filter="not_pursuing",
        )

        assert total == 1
        assert prospects[0].profile.account_id == creator_ids[0]

    def test_status_filter_specific_status(
        self, db_path, game_service, registered_user,
    ):
        """Filtering by a specific status shows only matching prospects."""
        game, creator_ids = _setup_game_with_creators(
            db_path, game_service, registered_user, num_creators=4,
        )
        repo = ProspectRepository(db_path)
        repo.upsert_prospect_workflow_state(
            customer_game_id=game.customer_game_id,
            account_id=creator_ids[0],
            status="contacted",
            notes="",
        )
        repo.upsert_prospect_workflow_state(
            customer_game_id=game.customer_game_id,
            account_id=creator_ids[1],
            status="contacted",
            notes="",
        )
        repo.upsert_prospect_workflow_state(
            customer_game_id=game.customer_game_id,
            account_id=creator_ids[2],
            status="replied",
            notes="",
        )

        service = ProspectRankingService(db_path)
        prospects, total, status_counts = service.rank_prospects(
            game, status_filter="contacted",
        )

        assert total == 2
        assert all(p.workflow.status == "contacted" for p in prospects)

    def test_status_counts_reflect_all_prospects(
        self, db_path, game_service, registered_user,
    ):
        """Status counts should cover all matching prospects, not just the current page."""
        game, creator_ids = _setup_game_with_creators(
            db_path, game_service, registered_user, num_creators=5,
        )
        repo = ProspectRepository(db_path)
        repo.upsert_prospect_workflow_state(
            customer_game_id=game.customer_game_id,
            account_id=creator_ids[0],
            status="contacted",
            notes="",
        )
        repo.upsert_prospect_workflow_state(
            customer_game_id=game.customer_game_id,
            account_id=creator_ids[1],
            status="replied",
            notes="",
        )
        repo.upsert_prospect_workflow_state(
            customer_game_id=game.customer_game_id,
            account_id=creator_ids[2],
            status="covered",
            notes="",
        )

        service = ProspectRankingService(db_path)
        _prospects, _total, status_counts = service.rank_prospects(game)

        assert status_counts["new"] == 2
        assert status_counts["contacted"] == 1
        assert status_counts["replied"] == 1
        assert status_counts["covered"] == 1
        assert status_counts.get("not_pursuing", 0) == 0

    def test_workflow_state_persists_across_queries(
        self, db_path, game_service, registered_user,
    ):
        """Status set via repository is visible in subsequent rank_prospects calls."""
        game, creator_ids = _setup_game_with_creators(
            db_path, game_service, registered_user, num_creators=1,
        )
        repo = ProspectRepository(db_path)

        # First query: new
        service = ProspectRankingService(db_path)
        prospects1, _, _ = service.rank_prospects(game)
        assert prospects1[0].workflow.status == "new"

        # Update status
        repo.upsert_prospect_workflow_state(
            customer_game_id=game.customer_game_id,
            account_id=creator_ids[0],
            status="contacted",
            notes="",
        )

        # Second query: contacted
        prospects2, _, _ = service.rank_prospects(game)
        assert prospects2[0].workflow.status == "contacted"

    def test_workflow_full_lifecycle(
        self, db_path, game_service, registered_user,
    ):
        """Walk a prospect through the full status lifecycle."""
        game, creator_ids = _setup_game_with_creators(
            db_path, game_service, registered_user, num_creators=1,
        )
        repo = ProspectRepository(db_path)
        cid = creator_ids[0]
        gid = game.customer_game_id

        lifecycle: list[ProspectWorkflowStatus] = [
            "contacted", "replied", "access_shared", "covered",
        ]
        for status in lifecycle:
            repo.upsert_prospect_workflow_state(
                customer_game_id=gid, account_id=cid, status=status, notes="",
            )
            states = repo.get_prospect_workflow_states(
                customer_game_id=gid, account_ids=(cid,),
            )
            assert states[cid].status == status

    def test_different_games_have_independent_statuses(
        self, db_path, game_service, registered_user,
    ):
        """The same creator can have different statuses for different games."""
        game1 = game_service.create_game(
            user_id=registered_user.user_id,
            name="Game One",
            summary="First game.",
            description="First game.",
            website_url=None,
            igdb_genre_ids=[12],
        )
        game2 = game_service.create_game(
            user_id=registered_user.user_id,
            name="Game Two",
            summary="Second game.",
            description="Second game.",
            website_url=None,
            igdb_genre_ids=[12],
        )
        _insert_igdb_game(db_path, 900, "Shared Game", genre_tags=[(12, "RPG")])
        _insert_creator(db_path, "shared-creator", "Shared Creator")
        _insert_game_play(db_path, "shared-creator", "Shared Game", 900)

        repo = ProspectRepository(db_path)
        repo.upsert_prospect_workflow_state(
            customer_game_id=game1.customer_game_id,
            account_id="shared-creator",
            status="contacted",
            notes="",
        )
        repo.upsert_prospect_workflow_state(
            customer_game_id=game2.customer_game_id,
            account_id="shared-creator",
            status="covered",
            notes="",
        )

        states1 = repo.get_prospect_workflow_states(
            customer_game_id=game1.customer_game_id,
            account_ids=("shared-creator",),
        )
        states2 = repo.get_prospect_workflow_states(
            customer_game_id=game2.customer_game_id,
            account_ids=("shared-creator",),
        )

        assert states1["shared-creator"].status == "contacted"
        assert states2["shared-creator"].status == "covered"
