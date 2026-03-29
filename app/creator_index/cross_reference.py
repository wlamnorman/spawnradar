"""Cross-reference service: scan Twitch bios for YouTube URLs → identity_links."""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from app.database import get_connection

log = logging.getLogger(__name__)

_YT_PATTERN = re.compile(
    r"https?://(?:www\.)?youtube\.com/(?:@[\w.-]+|channel/[\w-]+|c/[\w-]+)",
    re.IGNORECASE,
)

YouTubeChannelLookupFn = Callable[[str], Awaitable[str | None]]


def extract_youtube_urls(text: str) -> list[str]:
    """Return deduplicated YouTube channel URLs found in *text*."""
    return list(dict.fromkeys(_YT_PATTERN.findall(text)))


def _canonical_account_pair(
    account_id_a: str, account_id_b: str
) -> tuple[str, str] | None:
    if account_id_a == account_id_b:
        return None
    if account_id_a <= account_id_b:
        return (account_id_a, account_id_b)
    return (account_id_b, account_id_a)


class CrossReferenceService:
    def __init__(
        self,
        *,
        db_path: str,
        youtube_channel_lookup: YouTubeChannelLookupFn,
    ) -> None:
        self._db_path = db_path
        self._yt_lookup = youtube_channel_lookup

    async def run_pass(self, *, limit: int = 500) -> int:
        """Scan up to *limit* unlinked Twitch accounts for YouTube URLs.

        Returns the number of new identity_links created.
        """
        candidates = self._load_unlinked_twitch_accounts(limit)
        links = 0
        for twitch_id, description in candidates:
            for url in extract_youtube_urls(description or ""):
                yt_id = await self._yt_lookup(url)
                if yt_id and self._write_link(twitch_id, yt_id, url):
                    links += 1
        log.info(
            "Cross-ref pass: %d candidates, %d new links",
            len(candidates),
            links,
        )
        return links

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_unlinked_twitch_accounts(
        self, limit: int
    ) -> list[tuple[str, str | None]]:
        with get_connection(self._db_path) as con:
            return con.execute(
                """SELECT p.account_id, p.description
                   FROM twitch_profiles_latest p
                   WHERE p.description LIKE '%youtube.com%'
                     AND NOT EXISTS (
                         SELECT 1 FROM identity_links l
                         WHERE l.account_id_a = p.account_id
                            OR l.account_id_b = p.account_id
                     )
                   LIMIT ?""",
                (limit,),
            ).fetchall()

    def _write_link(
        self, account_id_a: str, account_id_b: str, url: str
    ) -> bool:
        pair = _canonical_account_pair(account_id_a, account_id_b)
        if pair is None:
            return False
        left_id, right_id = pair
        with get_connection(self._db_path) as con:
            cur = con.execute(
                """INSERT OR IGNORE INTO identity_links
                   (link_id, account_id_a, account_id_b, link_type,
                    evidence_json, created_at)
                   VALUES (?, ?, ?, 'social_link', ?, ?)""",
                (
                    str(uuid.uuid4()),
                    left_id,
                    right_id,
                    json.dumps({"url": url, "source": "twitch_description"}),
                    datetime.now(UTC).isoformat(),
                ),
            )
            return cur.rowcount > 0
