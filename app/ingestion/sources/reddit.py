"""Reddit community and thread discovery via public JSON API.

Uses Reddit's public .json endpoints — no authentication required for
publicly accessible subreddits and posts.
"""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import quote_plus

import httpx

from app.games.models import Game
from app.ingestion.base import CandidateRecord, CandidateSource
from app.ingestion.query_builder import build_basic_queries
from app.ingestion.raw_data import RedditSubredditData, RedditThreadData
from app.ingestion.registry import Source, register

_REDDIT_BASE = "https://www.reddit.com"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 compatible; Spawnradar/1.0 (marketing prospecting tool)",
    "Accept": "application/json",
}


@register(Source.REDDIT)
class RedditSource(CandidateSource):
    """Discovers Reddit subreddits and relevant threads for a game.

    Searches both subreddits (communities) and posts/threads using the game's
    genre and audience tags.  Subreddits are modelled as prospects you can
    post in; threads show active community conversations.
    """

    def __init__(
        self, delay_seconds: float = 1.0, timeout_seconds: float = 20.0
    ) -> None:
        self._delay = delay_seconds
        self._timeout = timeout_seconds

    async def discover(self, game: Game, limit: int) -> list[CandidateRecord]:
        """Return up to *limit* Reddit prospects (subreddits + threads)."""
        queries = build_basic_queries(game)
        seen_handles: set[str] = set()
        results: list[CandidateRecord] = []

        async with httpx.AsyncClient(
            headers=_HEADERS, timeout=self._timeout
        ) as client:
            for i, query in enumerate(queries):
                if len(results) >= limit:
                    break
                try:
                    subreddits = await self._search_subreddits(client, query)
                    threads = await self._search_threads(client, query)
                    batch = subreddits + threads
                except Exception:
                    continue

                for record in batch:
                    if record.handle not in seen_handles:
                        seen_handles.add(record.handle)
                        results.append(record)
                        if len(results) >= limit:
                            break

                if i < len(queries) - 1:
                    await asyncio.sleep(self._delay)

        return results

    async def _search_subreddits(
        self, client: httpx.AsyncClient, query: str
    ) -> list[CandidateRecord]:
        """Search for subreddits matching *query*."""
        url = f"{_REDDIT_BASE}/subreddits/search.json?q={quote_plus(query)}&limit=25"
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []

        records: list[CandidateRecord] = []
        for child in _iter_children(data):
            record = _parse_subreddit(child)
            if record is not None:
                records.append(record)
        return records

    async def _search_threads(
        self, client: httpx.AsyncClient, query: str
    ) -> list[CandidateRecord]:
        """Search for relevant posts/threads matching *query*."""
        url = (
            f"{_REDDIT_BASE}/search.json"
            f"?q={quote_plus(query)}&sort=relevance&limit=25"
        )
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []

        records: list[CandidateRecord] = []
        for child in _iter_children(data):
            record = _parse_thread(child)
            if record is not None:
                records.append(record)
        return records


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _iter_children(data: Any):
    """Yield each child dict from a Reddit listing response."""
    if not isinstance(data, dict):
        return
    children = data.get("data", {}).get("children", [])
    for child in children:
        if isinstance(child, dict) and "data" in child:
            yield child["data"]


def _parse_subreddit(data: dict) -> CandidateRecord | None:
    """Convert a subreddit data dict into a CandidateRecord."""
    name = str(data.get("display_name", "")).strip()
    if not name:
        return None

    handle = f"r/{name}"
    title = str(data.get("title", name)).strip()
    description = str(
        data.get("public_description", "") or data.get("description", "") or ""
    ).strip()
    subscribers = data.get("subscribers")
    profile_url = f"{_REDDIT_BASE}/r/{name}"

    raw_data = RedditSubredditData(
        subreddit_name=name,
        title=title,
        over18=data.get("over18", False),
    ).model_dump()

    text_signals = [description] if description else []

    return CandidateRecord(
        platform="reddit",
        handle=handle,
        display_name=title,
        profile_url=profile_url,
        contact_channel="reddit_post",
        contact_value=None,
        audience_size=int(subscribers) if subscribers else None,
        engagement_rate=None,
        description=description[:500] if description else None,
        raw_data=raw_data,
        prospect_type="community",
        text_signals=text_signals,
    )


def _parse_thread(data: dict) -> CandidateRecord | None:
    """Convert a Reddit post data dict into a CandidateRecord.

    Threads represent active community conversations that can be commented on.
    """
    post_id = str(data.get("id", "")).strip()
    subreddit = str(data.get("subreddit", "")).strip()
    if not post_id or not subreddit:
        return None

    handle = f"post:{post_id}"
    title = str(data.get("title", "")).strip()
    author = str(data.get("author", "")).strip()
    score = data.get("score", 0)
    num_comments = data.get("num_comments", 0)
    permalink = data.get("permalink", "")
    profile_url = f"{_REDDIT_BASE}{permalink}" if permalink else None

    description = f"Post in r/{subreddit} by u/{author}. Score: {score}, comments: {num_comments}."

    raw_data = RedditThreadData(
        post_id=post_id,
        subreddit=subreddit,
        author=author,
        score=score,
        num_comments=num_comments,
        permalink=permalink,
    ).model_dump()

    text_signals = [s for s in [title, description] if s]

    return CandidateRecord(
        platform="reddit",
        handle=handle,
        display_name=f"{title[:80]}..." if len(title) > 80 else title,
        profile_url=profile_url,
        contact_channel="reddit_comment",
        contact_value=None,
        audience_size=num_comments,  # use comment count as proxy for engagement
        engagement_rate=None,
        description=description,
        raw_data=raw_data,
        prospect_type="community",
        text_signals=text_signals,
    )
