"""LLM-based channel fit scoring using Claude Haiku.

Replaces the keyword-based genre_fit and vibe_fit with a semantic
evaluation by Claude and adds format_fit (does their content style suit this
game type?) and why_selected (a plain-English explanation for the queue UI).

Cost (claude-haiku-4-5):
  ~600 input + ~200 output tokens per channel ≈ $0.0016/channel
  80–110 channels/run ≈ $0.13–$0.18/run.

All channels in a run are scored concurrently (asyncio.gather), so the
LLM step adds roughly one API call's latency, not N.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass

import anthropic

from app.games.models import Game
from app.prospects.models import Prospect

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class LLMFitScores:
    genre_fit: float  # 0.0–1.0: does this channel cover this genre?
    vibe_fit: float  # 0.0–1.0: does their content vibe match the game's feel?
    format_fit: (
        float  # 0.0–1.0: does their content format suit this game type?
    )
    platform_fit: (
        float  # 0.0–1.0: does this channel cover the game's platform(s)?
    )
    fit_summary: str  # one sentence explaining the overall fit
    why_selected: str  # plain-English reason shown in the review queue


_CONCURRENCY = 3  # max simultaneous Haiku requests (free-tier safe)


async def llm_score_batch(
    game: Game,
    prospects: list[Prospect],
    api_key: str,
) -> dict[str, LLMFitScores]:
    """Score all prospects concurrently. Returns prospect_id → scores.

    Prospects that fail (API error, bad JSON, etc.) are omitted so the
    caller can fall back to keyword scoring for them.
    """
    client = anthropic.AsyncAnthropic(api_key=api_key)
    sem = asyncio.Semaphore(_CONCURRENCY)

    async def _guarded(prospect: Prospect):
        async with sem:
            return await _score_one(client, game, prospect)

    tasks = [asyncio.create_task(_guarded(prospect)) for prospect in prospects]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    scores: dict[str, LLMFitScores] = {}
    for prospect, result in zip(prospects, results, strict=False):
        if isinstance(result, LLMFitScores):
            scores[prospect.prospect_id] = result
            log.debug(
                "  %-35s  genre=%.2f  vibe=%.2f  format=%.2f",
                prospect.display_name[:35],
                result.genre_fit,
                result.vibe_fit,
                result.format_fit,
            )
        else:
            log.warning(
                "  LLM scoring failed for %s: %s",
                prospect.display_name,
                result,
            )

    return scores


async def _score_one(
    client: anthropic.AsyncAnthropic,
    game: Game,
    prospect: Prospect,
) -> LLMFitScores:
    """Ask Haiku to rate one channel across genre, vibe and format fit."""
    # text_signals is the normalized field (video titles, recent posts, etc.).
    # Fall back to recent_video_titles for prospects ingested before this field.
    text_signals = prospect.raw_data.get(
        "text_signals"
    ) or prospect.raw_data.get("recent_video_titles", [])
    signals_text = (
        "\n".join(f"- {t}" for t in text_signals[:5])
        if text_signals
        else "Not available"
    )
    description = (prospect.description or "No description provided.").strip()

    summary_line = f"\nSummary: {game.summary}" if game.summary else ""
    prompt = f"""You are evaluating whether a content creator or community is a good outreach target for an indie game.

GAME
Name: {game.name}{summary_line}
Platforms: {", ".join(game.platform_tags) or "none"}
Genre tags: {", ".join(game.genre_tags) or "none"}
Vibe tags: {", ".join(game.ordered_vibe_tags()) or "none"}

PROSPECT
Platform: {prospect.platform}
Name: {prospect.display_name}
Description: {description}
Recent content:
{signals_text}

Return a JSON object with exactly these fields:
- "genre_fit": float 0.0–1.0 — does this channel cover games in this genre or adjacent ones?
- "vibe_fit": float 0.0–1.0 — does this channel's content aesthetic and vibe match the game's tone and feel?
- "format_fit": float 0.0–1.0 — does their content format suit this type of game? (e.g. "I tried this weird browser game" formats score high for small indie games; deep 45-min critiques of AAA titles score low; for Reddit communities return 0.5)
- "platform_fit": float 0.0–1.0 — does this creator or community cover the game's target platform(s)? Game platform tags may include: PC, Nintendo Switch, PlayStation, Xbox, VR, mobile, browser, board game. A channel that covers the matching platform(s) scores 1.0; a channel focused on different platforms scores 0.1–0.3; a broad channel with no clear platform focus scores 0.5. If no platform tags are specified, return 0.5.
- "fit_summary": string — one sentence explaining the overall fit
- "why_selected": string — plain-English reason why this creator is (or isn't) worth reaching out to, e.g. "Covers browser puzzle games weekly, active community, posts business email in description"

Respond with only the JSON object, no markdown or other text."""

    response = await client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )

    text = next((b.text for b in response.content if b.type == "text"), "")
    data = _parse_json(text)

    return LLMFitScores(
        genre_fit=_clamp(data.get("genre_fit", 0.0)),
        vibe_fit=_clamp(data.get("vibe_fit", 0.0)),
        format_fit=_clamp(data.get("format_fit", 0.5)),
        platform_fit=_clamp(data.get("platform_fit", 0.5)),
        fit_summary=str(data.get("fit_summary", "")).strip(),
        why_selected=str(data.get("why_selected", "")).strip(),
    )


def _clamp(value) -> float:
    return max(0.0, min(1.0, float(value)))


def _parse_json(text: str) -> dict:
    """Parse JSON from the model response, stripping any markdown code fences."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return json.loads(text)
