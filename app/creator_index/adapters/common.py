"""Shared adapter helpers for source-index platform crawlers."""

from __future__ import annotations

import re
import statistics
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from app.creator_index.adapters.base import ContactPointSeed, ContactType

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
DISCORD_RE = re.compile(
    r"https?://(?:www\.)?discord(?:\.gg|\.com/invite)/[\w-]+",
    re.IGNORECASE,
)


def _deobfuscate(text: str) -> str:
    """Normalise common email obfuscation patterns before regex matching."""
    result = re.sub(r"(?i)\s*\[at\]\s*|\s*\(at\)\s*", "@", text)
    result = re.sub(r"(?i)\s*\[dot\]\s*|\s*\(dot\)\s*", ".", result)
    return result


_HTML_TAG_RE = re.compile(r"<[^>]+>")


def strip_html_tags(text: str) -> str:
    """Remove HTML tags and normalise whitespace to plain text."""
    return _HTML_TAG_RE.sub(" ", text).strip()


def extract_emails(text: str | None) -> list[str]:
    """Return normalized unique emails found in *text*, in order of first appearance.

    Handles common obfuscation patterns such as ``user[at]example.com``.
    """
    if not text:
        return []
    normalized = _deobfuscate(text)
    seen: set[str] = set()
    found: list[str] = []
    for email in EMAIL_RE.findall(normalized):
        lowered = email.lower()
        if lowered not in seen:
            seen.add(lowered)
            found.append(lowered)
    return found


def extract_discord_urls(text: str | None) -> list[str]:
    """Return deduplicated Discord invite URLs found in *text*."""
    if not text:
        return []
    seen: set[str] = set()
    found: list[str] = []
    for url in DISCORD_RE.findall(text):
        lowered = url.lower()
        if lowered not in seen:
            seen.add(lowered)
            found.append(url)
    return found


def collect_text_contacts(
    text: str | None,
    *,
    source_kind: str,
    source_url: str | None,
    seen_emails: set[str],
    seen_discord: set[str],
) -> list[ContactPointSeed]:
    """Extract email and Discord contacts from *text*, skipping already-seen values.

    Mutates *seen_emails* and *seen_discord* in place so callers can chain
    multiple calls with the same seen-sets for cumulative deduplication.
    """
    if not text:
        return []
    contacts: list[ContactPointSeed] = []
    for email in extract_emails(text):
        if email not in seen_emails:
            seen_emails.add(email)
            contacts.append(
                ContactPointSeed(
                    contact_type=ContactType.EMAIL,
                    contact_value=email,
                    source_kind=source_kind,
                    source_url=source_url,
                )
            )
    for discord_url in extract_discord_urls(text):
        if discord_url.lower() not in seen_discord:
            seen_discord.add(discord_url.lower())
            contacts.append(
                ContactPointSeed(
                    contact_type=ContactType.DISCORD,
                    contact_value=discord_url,
                    source_kind=source_kind,
                    source_url=source_url,
                )
            )
    return contacts


def optional_int(value: object) -> int | None:
    """Best-effort int coercion for API payload fields."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if not isinstance(value, str):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def as_list(value: object) -> list[object]:
    """Return *value* if it is already a list, else an empty list."""
    return value if isinstance(value, list) else []


def parse_iso_datetime(value: str | None) -> datetime | None:
    """Parse an ISO timestamp from APIs, accepting a trailing ``Z``."""
    if not value:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def mean_int(values: Sequence[int | None]) -> int | None:
    """Return the integer mean of the non-null values."""
    filtered = [value for value in values if value is not None]
    if not filtered:
        return None
    return int(round(sum(filtered) / len(filtered)))


def median_int(values: Sequence[int | None]) -> int | None:
    """Return the integer median of the non-null values."""
    filtered = [value for value in values if value is not None]
    if not filtered:
        return None
    return int(round(statistics.median(filtered)))


def count_recent_timestamps(
    values: Sequence[str | None], *, days: int, now: datetime | None = None
) -> int:
    """Count timestamps within the last *days* days."""
    reference = now or datetime.now(UTC)
    cutoff = reference - timedelta(days=days)
    count = 0
    for value in values:
        parsed = parse_iso_datetime(value)
        if parsed is not None and parsed >= cutoff:
            count += 1
    return count


def latest_timestamp(values: Sequence[str | None]) -> str | None:
    """Return the most recent ISO timestamp from *values*."""
    parsed_values = [
        parsed for value in values if (parsed := parse_iso_datetime(value))
    ]
    if not parsed_values:
        return None
    return max(parsed_values).isoformat()


def dominant_language(values: Sequence[str | None]) -> str | None:
    """Return the most frequently occurring non-null language code, or None."""
    langs = [v for v in values if v]
    if not langs:
        return None
    return max(set(langs), key=langs.count)


def chunks(values: Sequence[str], size: int) -> list[list[str]]:
    """Split *values* into successive lists of at most *size* items."""
    return [
        list(values[index : index + size])
        for index in range(0, len(values), size)
    ]
