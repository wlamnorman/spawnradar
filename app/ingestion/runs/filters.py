"""Cheap pre-LLM candidate filtering for discovery runs."""

from __future__ import annotations

import logging
from collections import defaultdict

from app.games.models import Game
from app.prospects.models import Prospect
from app.scoring.engine import ScoreBreakdown

log = logging.getLogger("app.ingestion.pipeline")

_OFFICIAL_ACCOUNT_MARKERS = (
    " official",
    "official ",
    "official account",
    "official channel",
    "official page",
"official discord",
    "verified official",
)
_BLUESKY_CREATOR_HARD_MIN_FOLLOWERS = 50
_BLUESKY_CREATOR_SOFT_MIN_FOLLOWERS = 100


def prefilter_prospects(
    game: Game,
    prospects: list[Prospect],
    base_scores: dict[str, ScoreBreakdown],
) -> list[Prospect]:
    """Drop obvious junk before spending LLM work."""
    filtered: list[Prospect] = []
    dropped: dict[str, int] = defaultdict(int)

    for prospect in prospects:
        score = base_scores[prospect.prospect_id]
        reason = prefilter_reason(prospect, score)
        if reason is None:
            filtered.append(prospect)
            continue
        dropped[reason] += 1
        log.debug(
            "[%s] %-35s  prefilter drop: %s",
            game.name,
            prospect.display_name[:35],
            reason,
        )

    if dropped:
        log.info(
            "[%s] Prefilter dropped %d candidates before LLM (%s)",
            game.name,
            sum(dropped.values()),
            ", ".join(
                f"{count} {reason}"
                for reason, count in sorted(dropped.items())
            ),
        )

    return filtered


def prefilter_reason(
    prospect: Prospect,
    score: ScoreBreakdown,
) -> str | None:
    """Return a drop reason when the prospect is clearly a poor fit."""
    if looks_official_account(prospect):
        return "official account"

    bluesky_reason = _bluesky_creator_size_reason(prospect, score)
    if bluesky_reason is not None:
        return bluesky_reason

    raw = prospect.raw_data
    last_active = raw.get("last_active_days")
    if last_active is None:
        last_active = raw.get("last_upload_days_ago")
    if (
        isinstance(last_active, (int, float))
        and last_active > 30
        and score.audience_size_score <= 0.2
    ):
        return "stale and tiny"

    if (
        score.genre_fit <= 0.0
        and score.vibe_fit <= 0.0
        and score.platform_fit <= 0.0
    ):
        return "no core match"

    return None


def _bluesky_creator_size_reason(
    prospect: Prospect,
    score: ScoreBreakdown,
) -> str | None:
    """Filter very small Bluesky creators before the LLM sees them."""
    if prospect.platform != "bluesky":
        return None

    prospect_type = str(prospect.raw_data.get("prospect_type", "creator"))
    if prospect_type != "creator":
        return None

    followers = _prospect_followers(prospect)
    if followers is None:
        return None

    if followers < _BLUESKY_CREATOR_HARD_MIN_FOLLOWERS:
        return "bluesky creator under 50 followers"

    if (
        followers < _BLUESKY_CREATOR_SOFT_MIN_FOLLOWERS
        and not _has_exceptional_bluesky_creator_signals(score)
    ):
        return "bluesky creator under 100 followers"

    return None


def _prospect_followers(prospect: Prospect) -> int | None:
    """Return the best available follower count for a prospect."""
    if isinstance(prospect.audience_size, int):
        return prospect.audience_size

    raw_followers = prospect.raw_data.get("followers_count")
    if isinstance(raw_followers, int):
        return raw_followers
    return None


def _has_exceptional_bluesky_creator_signals(
    score: ScoreBreakdown,
) -> bool:
    """Allow a narrow 50-99 follower band only for unusually strong fits."""
    return (
        score.genre_fit >= 0.85
        and score.activity_score >= 0.8
        and (score.platform_fit >= 0.5 or score.vibe_fit >= 0.5)
    )


def looks_official_account(prospect: Prospect) -> bool:
    """Detect obvious official / owned accounts that are poor outreach targets."""
    haystack = " ".join(
        part
        for part in [
            prospect.display_name,
            prospect.handle,
            prospect.description or "",
        ]
        if part
    ).lower()
    return any(marker in haystack for marker in _OFFICIAL_ACCOUNT_MARKERS)
