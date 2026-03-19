"""Business logic for draft management: queue actions, status transitions."""
from __future__ import annotations

import uuid

from app.prospects.models import Outcome, ReviewQueueItem
from app.prospects.repository import DraftItemRepository, OutcomeRepository

VALID_ACTIONS = {"approve", "reject", "snooze", "sent"}
ACTION_TO_STATUS = {
    "approve": "approved",
    "reject": "rejected",
    "snooze": "snoozed",
    "sent": "sent",
}


class ProspectService:
    """Manages the review queue and draft item lifecycle."""

    def __init__(
        self,
        draft_repo: DraftItemRepository,
        outcome_repo: OutcomeRepository,
    ) -> None:
        self._drafts = draft_repo
        self._outcomes = outcome_repo

    def get_queue(self, game_id: str) -> list[ReviewQueueItem]:
        """Return queued draft items for a game, ordered by priority score."""
        return self._drafts.list_queued_simple(game_id)

    def apply_action(
        self,
        draft_item_id: str,
        action: str,
        body_text: str | None = None,
        notes: str | None = None,
    ) -> Outcome:
        """Apply a developer action to a draft item.

        Valid actions: approve, reject, snooze, sent.
        Saves any edited body text and records an outcome entry.
        """
        action = action.lower().strip()
        if action not in VALID_ACTIONS:
            raise ValueError(
                f"Invalid action '{action}'. Must be one of: {', '.join(VALID_ACTIONS)}."
            )

        draft = self._drafts.get_by_id(draft_item_id)
        if draft is None:
            raise ValueError(f"Draft item '{draft_item_id}' not found.")

        new_status = ACTION_TO_STATUS[action]
        self._drafts.update_status(draft_item_id, new_status, body_text)

        outcome_id = str(uuid.uuid4())
        return self._outcomes.create(outcome_id, draft_item_id, action, notes)
