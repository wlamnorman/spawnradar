"""Tests for prospect review queue and draft item lifecycle."""

import json
import uuid
from datetime import UTC, datetime

import pytest

from app.database import get_connection
from app.prospects.models import Outcome


def _insert_prospect(db_path, **kwargs):
    """Helper: insert a prospect directly into the DB and return prospect_id."""
    now = datetime.now(UTC).isoformat()
    prospect_id = kwargs.get("prospect_id", str(uuid.uuid4()))
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO prospects
                (prospect_id, platform, handle, display_name, profile_url,
                 contact_channel, contact_value, audience_size, engagement_rate,
                 description, raw_data, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                prospect_id,
                kwargs.get("platform", "youtube"),
                kwargs.get("handle", "testhandle"),
                kwargs.get("display_name", "Test Creator"),
                kwargs.get("profile_url"),
                kwargs.get("contact_channel"),
                kwargs.get("contact_value"),
                kwargs.get("audience_size"),
                kwargs.get("engagement_rate"),
                kwargs.get("description"),
                json.dumps(kwargs.get("raw_data", {})),
                now,
                now,
            ),
        )
    return prospect_id


def _insert_draft_item(db_path, game_id, prospect_id, **kwargs):
    """Helper: insert a draft_item directly into the DB and return draft_item_id."""
    now = datetime.now(UTC).isoformat()
    draft_item_id = kwargs.get("draft_item_id", str(uuid.uuid4()))
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO draft_items
                (draft_item_id, game_id, prospect_id, template_id, subject_line,
                 body_text, status, priority_score, suggested_action, fit_summary,
                 score_breakdown, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                draft_item_id,
                game_id,
                prospect_id,
                kwargs.get("template_id"),
                kwargs.get("subject_line"),
                kwargs.get("body_text", "Hello, check out our game!"),
                kwargs.get("status", "queued"),
                kwargs.get("priority_score", 0.5),
                kwargs.get("suggested_action", "Review"),
                kwargs.get("fit_summary", "Good fit"),
                json.dumps(kwargs.get("score_breakdown", {})),
                now,
                now,
            ),
        )
    return draft_item_id


@pytest.fixture
def seeded_draft(db_path, sample_game):
    """Insert a prospect and queued draft item, returning draft_item_id."""
    prospect_id = _insert_prospect(
        db_path, handle="creator1", display_name="Creator One"
    )
    draft_item_id = _insert_draft_item(
        db_path, sample_game.game_id, prospect_id
    )
    return draft_item_id


def test_apply_action_approve_changes_status(
    prospect_service, draft_repo, seeded_draft
):
    outcome = prospect_service.apply_action(seeded_draft, "approve")
    assert isinstance(outcome, Outcome)
    assert outcome.outcome_type == "approve"
    updated = draft_repo.get_by_id(seeded_draft)
    assert updated.status == "approved"


def test_apply_action_reject_changes_status(
    prospect_service, draft_repo, seeded_draft
):
    prospect_service.apply_action(seeded_draft, "reject")
    updated = draft_repo.get_by_id(seeded_draft)
    assert updated.status == "rejected"


def test_apply_action_snooze_changes_status(
    prospect_service, draft_repo, seeded_draft
):
    prospect_service.apply_action(seeded_draft, "snooze")
    updated = draft_repo.get_by_id(seeded_draft)
    assert updated.status == "snoozed"


def test_apply_action_sent_changes_status(
    prospect_service, draft_repo, seeded_draft
):
    prospect_service.apply_action(seeded_draft, "sent")
    updated = draft_repo.get_by_id(seeded_draft)
    assert updated.status == "sent"


def test_apply_action_with_invalid_action_raises_value_error(
    prospect_service, seeded_draft
):
    with pytest.raises(ValueError, match="Invalid action"):
        prospect_service.apply_action(seeded_draft, "archive")


def test_list_review_queue_returns_only_queued_items(
    prospect_service, draft_repo, db_path, sample_game
):
    # Insert two prospects with draft items
    pid1 = _insert_prospect(
        db_path, handle="queuedcreator", display_name="Queued Creator"
    )
    pid2 = _insert_prospect(
        db_path, handle="approvedcreator", display_name="Approved Creator"
    )

    did1 = _insert_draft_item(
        db_path, sample_game.game_id, pid1, status="queued"
    )
    did2 = _insert_draft_item(
        db_path, sample_game.game_id, pid2, status="approved"
    )

    queue = prospect_service.get_queue(sample_game.game_id)
    draft_ids = [item.draft.draft_item_id for item in queue]

    assert did1 in draft_ids
    assert did2 not in draft_ids


def test_apply_action_records_outcome_with_notes(
    prospect_service, seeded_draft
):
    outcome = prospect_service.apply_action(
        seeded_draft, "reject", notes="Not a good fit"
    )
    assert outcome.notes == "Not a good fit"
    assert outcome.draft_item_id == seeded_draft
