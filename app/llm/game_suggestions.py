"""LLM-powered game suggestion generation.

Calls Claude to produce two tiers of reference games for a CustomerGame:
- **tight**: closest matches to fill gaps in the customer's picks
- **broad**: popular games with partial audience overlap for exploration
"""

from __future__ import annotations

import json
import logging

import anthropic

from app.games.models import CustomerGame

log = logging.getLogger(__name__)

_MIN_TIGHT_TOTAL = 5
_BROAD_MIN = 5
_BROAD_MAX = 10


def _build_prompt(customer_game: CustomerGame) -> str:
    """Build the Claude prompt describing the game and what we need."""
    customer_picks = customer_game.similar_game_names
    tight_needed = max(0, _MIN_TIGHT_TOTAL - len(customer_picks))

    game_desc = (
        f"Game: {customer_game.name}\n"
        f"Summary: {customer_game.summary or customer_game.description}\n"
        f"Genres: {', '.join(customer_game.genre_labels) or 'none'}\n"
        f"Themes: {', '.join(customer_game.theme_labels) or 'none'}\n"
        f"Keywords: {', '.join(customer_game.keyword_labels) or 'none'}\n"
        f"Game modes: {', '.join(customer_game.game_mode_labels) or 'none'}"
    )

    if customer_picks:
        picks_text = (
            f"\n\nThe developer already selected these similar games: "
            f"{', '.join(customer_picks)}"
        )
    else:
        picks_text = "\n\nThe developer has not selected any similar games yet."

    return f"""{game_desc}{picks_text}

Your task: suggest reference games in two tiers.

1. "tight" — Add {tight_needed} games that are the closest matches to this game. Same subgenre, same core mechanics, overlapping streaming audience. These should be games that a fan of the developer's game would definitely also play.{' Return an empty list since the developer already has enough similar games.' if tight_needed == 0 else ''} Do NOT repeat any games the developer already selected.

2. "broad" — List {_BROAD_MIN}-{_BROAD_MAX} popular games whose streaming audience would partially overlap. These should be bigger, more well-known games that share some genre or thematic overlap but aren't necessarily the same subgenre. Think: "if someone watches X, they might also enjoy this developer's game." Do NOT repeat any games from the tight list or the developer's picks.

Requirements:
- Use exact official game names as they would appear on Twitch
- Only include games that have been released and are likely to have a Twitch category
- Prefer games with active streaming communities

Return ONLY valid JSON in this exact format, no other text:
{{"tight": ["Game Name 1", "Game Name 2"], "broad": ["Game Name 3", "Game Name 4"]}}"""


async def generate_game_suggestions(
    customer_game: CustomerGame,
    *,
    api_key: str,
    model: str = "claude-sonnet-4-20250514",
) -> tuple[list[str], list[str]]:
    """Generate tight + broad anchor game names for a CustomerGame.

    Returns ``(tight_anchors, broad_anchors)``.  On failure returns
    ``([], [])``.
    """
    prompt = _build_prompt(customer_game)
    log.info(
        "[%s] Requesting LLM game suggestions (model=%s)",
        customer_game.name, model,
    )

    try:
        client = anthropic.AsyncAnthropic(api_key=api_key)
        response = await client.messages.create(
            model=model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        first_block = response.content[0]
        if not hasattr(first_block, "text"):
            log.warning("[%s] LLM returned non-text block", customer_game.name)
            return [], []
        raw_text = first_block.text.strip()  # type: ignore[union-attr]
    except Exception:
        log.exception("[%s] LLM API call failed", customer_game.name)
        return [], []

    # Parse JSON — handle markdown code blocks
    text = raw_text
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        log.warning(
            "[%s] LLM returned invalid JSON: %s", customer_game.name, raw_text[:200],
        )
        return [], []

    tight = [str(g) for g in data.get("tight", []) if isinstance(g, str)]
    broad = [str(g) for g in data.get("broad", []) if isinstance(g, str)]

    # Deduplicate against customer picks
    customer_lower = {n.lower() for n in customer_game.similar_game_names}
    tight = [g for g in tight if g.lower() not in customer_lower]
    broad_lower = customer_lower | {g.lower() for g in tight}
    broad = [g for g in broad if g.lower() not in broad_lower]

    log.info(
        "[%s] LLM generated %d tight + %d broad anchor games",
        customer_game.name, len(tight), len(broad),
    )
    return tight, broad
