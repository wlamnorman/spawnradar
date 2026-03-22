"""Tag-driven scoring engine.

Computes how well a prospect matches a game's audience profile across seven
dimensions. LLM-computed overrides replace keyword-based calculations when
available.

Weights vary by prospect_type (read from raw_data) so that Reddit communities
and Bluesky developers are judged on dimensions that are meaningful for them,
rather than against a model designed for YouTube channels.

creator  (YouTube channels, default)
  genre_fit       0.25  — does this channel cover this genre?
  audience_fit    0.20  — does their audience match our players?
  format_fit      0.15  — does their format suit this type of game? (LLM only)
  activity_score  0.15  — how recently/frequently do they upload?
  contactability  0.10  — can we actually reach them?
  audience_size   0.10  — are they in the indie outreach sweet spot?
  platform_fit    0.05  — do platform tags appear in their content?

community  (Reddit subreddits/threads)
  genre_fit       0.35  — is this community about the right topic?
  audience_fit    0.25  — do members match the game's target players?
  format_fit      0.00  — N/A: communities have no content format
  activity_score  0.05  — hard to measure; low weight
  contactability  0.05  — always high for Reddit; barely discriminates
  audience_size   0.20  — bigger community = more reach
  platform_fit    0.10  — PC/mobile/etc. community focus matters

developer  (Bluesky indie devs)
  genre_fit       0.30  — do they make/discuss similar games?
  audience_fit    0.15  — their audience is mostly other devs
  format_fit      0.10  — devlogs are relevant but not primary signal
  activity_score  0.25  — active posters are better cross-promo targets
  contactability  0.15  — can we actually reach them?
  audience_size   0.00  — most devs have tiny followings; not useful
  platform_fit    0.05  — platform relevance

Type modifiers are then applied after the weighted score so developer peers
remain discoverable internally without outranking creators or communities in
the main outreach queue.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.games.tags import WeightedTag

if TYPE_CHECKING:
    from app.games.models import Game
    from app.prospects.models import Prospect

# ---------------------------------------------------------------------------
# Per-prospect-type weight tables (each must sum to 1.0)
# ---------------------------------------------------------------------------

_WEIGHTS: dict[str, dict[str, float]] = {
    "creator": {
        "genre": 0.25,
        "audience": 0.20,
        "format": 0.15,
        "activity": 0.15,
        "contactability": 0.10,
        "audience_size": 0.10,
        "platform": 0.05,
    },
    "community": {
        "genre": 0.35,
        "audience": 0.25,
        "format": 0.00,
        "activity": 0.05,
        "contactability": 0.05,
        "audience_size": 0.20,
        "platform": 0.10,
    },
    "developer": {
        "genre": 0.30,
        "audience": 0.15,
        "format": 0.10,
        "activity": 0.25,
        "contactability": 0.15,
        "audience_size": 0.00,
        "platform": 0.05,
    },
}

_TYPE_SCORE_MULTIPLIER: dict[str, float] = {
    "creator": 1.0,
    "community": 1.0,
    "developer": 0.55,
}


@dataclass(frozen=True)
class ScoreBreakdown:
    """Per-dimension scores and an overall score for a prospect/game pair."""

    genre_fit: float  # 0–1: how well prospect matches game's genre_tags
    audience_fit: float  # 0–1: how well prospect matches game's audience_tags
    format_fit: float  # 0–1: does their content format suit this game type?
    activity_score: float  # 0–1: how recently/frequently they upload
    platform_fit: float  # 0–1: platform match
    contactability: float  # 0–1: how reachable this prospect is
    audience_size_score: float  # 0–1: normalized audience size
    final_score: float  # weighted combination of the above
    fit_summary: str  # human-readable sentence
    why_selected: str  # specific reason this channel was picked
    reasons: list[str] = field(default_factory=list)  # matching signal details


def score_prospect(
    game: Game,
    prospect: Prospect,
    *,
    genre_fit_override: float | None = None,
    audience_fit_override: float | None = None,
    format_fit_override: float | None = None,
    platform_fit_override: float | None = None,
    fit_summary_override: str | None = None,
    why_selected_override: str | None = None,
) -> ScoreBreakdown:
    """Compute a ScoreBreakdown for a prospect against a game's tag profile.

    LLM overrides (genre_fit, audience_fit, format_fit, platform_fit,
    fit_summary, why_selected) replace the keyword/heuristic calculations
    when provided. All other dimensions are always computed locally.

    Weights are selected based on the prospect's type (creator / community /
    developer) stored in raw_data, so Reddit communities and Bluesky devs
    are scored against dimensions that are meaningful for their format.
    """
    raw = prospect.raw_data

    # Select weight table based on prospect type (default: creator/YouTube)
    prospect_type = str(raw.get("prospect_type", "creator"))
    w = _WEIGHTS.get(prospect_type, _WEIGHTS["creator"])

    # Build a rich text corpus: profile text + source-specific content signals
    # text_signals is the normalized field; fall back to recent_video_titles for
    # prospects ingested before this field was introduced.
    signals = raw.get("text_signals") or raw.get("recent_video_titles", [])
    signal_text = " ".join(signals)
    search_text = " ".join(
        filter(
            None,
            [
                prospect.display_name,
                prospect.handle,
                prospect.description or "",
                signal_text,
            ],
        )
    ).lower()

    # Tags matched implicitly via the search query that discovered this channel
    source_genre_tag = raw.get("source_genre_tag") or ""
    source_audience_tag = raw.get("source_audience_tag") or ""
    source_mechanics_tag = raw.get("source_mechanics_tag") or ""
    source_tone_tag = raw.get("source_tone_tag") or ""

    reasons: list[str] = []

    # -----------------------------------------------------------------------
    # Genre fit — LLM override when available, else keyword matching.
    # Mechanics and tone tags are folded in here: they describe what the game
    # is like and generate their own search queries, so they contribute to the
    # same fit dimension.
    # -----------------------------------------------------------------------
    if genre_fit_override is not None:
        genre_fit = genre_fit_override
    else:
        genre_context = {
            t
            for t in [source_genre_tag, source_mechanics_tag, source_tone_tag]
            if t
        }
        all_genre_like_tags = (
            game.weighted_genre_tags()
            + game.weighted_mechanics_tags()
            + game.weighted_tone_tags()
        )
        genre_fit = _tag_match_score(
            all_genre_like_tags,
            search_text,
            genre_context,
            reasons,
            "genre",
        )

    # -----------------------------------------------------------------------
    # Audience fit — LLM override when available, else keyword matching
    # -----------------------------------------------------------------------
    if audience_fit_override is not None:
        audience_fit = audience_fit_override
    else:
        audience_fit = _tag_match_score(
            game.weighted_audience_tags(),
            search_text,
            {source_audience_tag} if source_audience_tag else set(),
            reasons,
            "audience",
        )

    # -----------------------------------------------------------------------
    # Format fit — LLM only; defaults to 0.5 (neutral) when not available
    # -----------------------------------------------------------------------
    format_fit = (
        format_fit_override if format_fit_override is not None else 0.5
    )

    # -----------------------------------------------------------------------
    # Activity score — derived from last_active_days (normalized cross-source)
    # Falls back to last_upload_days_ago for prospects ingested before this field.
    # -----------------------------------------------------------------------
    last_active = (
        raw.get("last_active_days")
        if raw.get("last_active_days") is not None
        else raw.get("last_upload_days_ago")
    )
    activity_score = _score_activity(last_active)

    # -----------------------------------------------------------------------
    # Platform fit — LLM override when available, else keyword matching
    # -----------------------------------------------------------------------
    if platform_fit_override is not None:
        platform_fit = platform_fit_override
    else:
        platform_fit = _tag_match_score(
            _weighted_plain_tags(game.platform_tags),
            search_text,
            set(),
            reasons,
            "platform",
        )

    # -----------------------------------------------------------------------
    # Contactability
    # -----------------------------------------------------------------------
    contactability = 0.3  # base score just for being discoverable
    if prospect.contact_channel:
        contactability += 0.3
    if prospect.contact_value:
        contactability += 0.2
    if prospect.profile_url:
        contactability += 0.2
    contactability = min(contactability, 1.0)

    # -----------------------------------------------------------------------
    # Audience size score — peaks in the indie outreach sweet spot (5K–500K)
    # -----------------------------------------------------------------------
    audience_size_score = _normalize_audience_size(
        prospect.audience_size, prospect.platform
    )

    # -----------------------------------------------------------------------
    # Weighted final score (weights selected by prospect_type)
    # -----------------------------------------------------------------------
    base_score = (
        genre_fit * w["genre"]
        + audience_fit * w["audience"]
        + format_fit * w["format"]
        + activity_score * w["activity"]
        + contactability * w["contactability"]
        + audience_size_score * w["audience_size"]
        + platform_fit * w["platform"]
    )
    type_multiplier = _TYPE_SCORE_MULTIPLIER.get(prospect_type, 1.0)
    final_score = round(min(base_score * type_multiplier, 1.0), 4)

    fit_summary = fit_summary_override or _build_summary(
        game, prospect, genre_fit, audience_fit, final_score
    )
    why_selected = why_selected_override or ""

    return ScoreBreakdown(
        genre_fit=round(genre_fit, 4),
        audience_fit=round(audience_fit, 4),
        format_fit=round(format_fit, 4),
        activity_score=round(activity_score, 4),
        platform_fit=round(platform_fit, 4),
        contactability=round(contactability, 4),
        audience_size_score=round(audience_size_score, 4),
        final_score=final_score,
        fit_summary=fit_summary,
        why_selected=why_selected,
        reasons=reasons,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _score_activity(last_upload_days_ago: int | None) -> float:
    """Convert upload recency to an activity score.

    - Unknown (None): 0.4 — benefit of the doubt, but penalised
    - 0–7 days:       1.0 — very active
    - 7–30 days:      0.8 — active
    - 30–60 days:     0.6 — moderate
    - 60–90 days:     0.4 — slow (still within our MAX_INACTIVE_DAYS filter)
    - >90 days:       0.1 — shouldn't reach here after hard filter, but handled
    """
    if last_upload_days_ago is None:
        return 0.4
    if last_upload_days_ago <= 7:
        return 1.0
    if last_upload_days_ago <= 30:
        return 0.8
    if last_upload_days_ago <= 60:
        return 0.6
    if last_upload_days_ago <= 90:
        return 0.4
    return 0.1


def _tag_match_score(
    tags: Sequence[WeightedTag],
    search_text: str,
    query_tags: set[str],
    reasons: list[str],
    dimension: str,
) -> float:
    """Score how well a tag list matches the available evidence.

    Two evidence sources, in strength order:
    1. Text match — every word in the tag appears in search_text (display
       name + handle + description + video titles).  Full credit.
    2. Search context — the channel was returned by a YouTube query built
       from this exact tag.  Strong (0.85) credit.

    Returns the fraction of tags that matched by either method, capped at 1.0.
    """
    if not tags:
        return 0.0

    query_tags_lower = {t.lower() for t in query_tags}
    matched_weight = 0.0
    total_weight = sum(tag.weight for tag in tags)
    if total_weight <= 0:
        return 0.0

    for tag in tags:
        tag_lower = tag.name.lower()
        tag_words = tag_lower.split()

        if all(word in search_text for word in tag_words):
            matched_weight += tag.weight
            reasons.append(f"{dimension.capitalize()} match: '{tag.name}'")
        elif tag_lower in query_tags_lower:
            matched_weight += 0.85 * tag.weight
            reasons.append(
                f"{dimension.capitalize()} (search context): '{tag.name}'"
            )

    return min(matched_weight / total_weight, 1.0)


def _normalize_audience_size(
    size: int | None, platform: str | None = None
) -> float:
    """Score audience size for indie game outreach fit.

    For Twitch, audience_size is live viewer count (not followers), so uses
    viewer-appropriate thresholds: sweet spot is 20–5K concurrent viewers.

    For all other platforms (follower/subscriber counts):
    - Under 1K: 0.0 (too small to drive meaningful attention)
    - 1K–500K:  log-scaled 0.2 → 1.0
    - 500K–5M:  gradual decay 1.0 → 0.3 (reachable but unlikely to respond)
    """
    if not size:
        return 0.0
    if platform == "twitch":
        # Live viewer count thresholds: 5 minimum, sweet spot 20–5K
        if size < 5:
            return 0.0
        if size <= 5_000:
            return 0.2 + 0.8 * math.log(size / 5) / math.log(1_000)
        else:
            return max(1.0 - 0.7 * math.log(size / 5_000) / math.log(10), 0.2)
    if size < 1_000:
        return 0.0
    if size <= 500_000:
        return 0.2 + 0.8 * math.log(size / 1_000) / math.log(500)
    else:
        return max(1.0 - 0.7 * math.log(size / 500_000) / math.log(10), 0.2)


def _weighted_plain_tags(tags: list[str]) -> list[WeightedTag]:
    return [WeightedTag(name=tag, weight=1.0, label="primary") for tag in tags]


def _build_summary(
    game: Game,
    prospect: Prospect,
    genre_fit: float,
    audience_fit: float,
    final_score: float,
) -> str:
    """Generate a one-sentence human-readable fit summary."""
    score_pct = int(final_score * 100)

    if final_score >= 0.65:
        quality = "strong"
    elif final_score >= 0.45:
        quality = "moderate"
    else:
        quality = "weak"

    genre_note = (
        f"with genre alignment at {int(genre_fit * 100)}%"
        if genre_fit > 0
        else "with no genre tag matches"
    )
    audience_note = (
        f"and audience fit at {int(audience_fit * 100)}%"
        if audience_fit > 0
        else "and no audience tag matches"
    )

    return (
        f"{prospect.display_name} is a {quality} match for {game.name} "
        f"(overall {score_pct}%), {genre_note} {audience_note}."
    )
