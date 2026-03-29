"""Unit tests for creator_index/adapters/common.py helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.creator_index.adapters.common import (
    as_list,
    chunks,
    count_recent_timestamps,
    dominant_language,
    extract_discord_urls,
    extract_emails,
    latest_timestamp,
    mean_int,
    median_int,
    optional_int,
    parse_iso_datetime,
    strip_html_tags,
)

# ---------------------------------------------------------------------------
# extract_emails
# ---------------------------------------------------------------------------


def test_extract_emails_finds_single_email():
    assert extract_emails("Contact me at hello@example.com") == [
        "hello@example.com"
    ]


def test_extract_emails_deduplicates_case_insensitively():
    assert extract_emails("A@Example.COM and a@example.com") == [
        "a@example.com"
    ]


def test_extract_emails_preserves_first_appearance_order():
    text = "first@example.com second@example.com first@example.com"
    assert extract_emails(text) == ["first@example.com", "second@example.com"]


def test_extract_emails_returns_empty_for_none():
    assert extract_emails(None) == []


def test_extract_emails_returns_empty_for_no_match():
    assert extract_emails("no email here") == []


# ---------------------------------------------------------------------------
# extract_discord_urls
# ---------------------------------------------------------------------------


def test_extract_discord_urls_finds_discord_gg():
    assert extract_discord_urls("Join us at https://discord.gg/abc123") == [
        "https://discord.gg/abc123"
    ]


def test_extract_discord_urls_finds_discord_com_invite():
    assert extract_discord_urls(
        "Link: https://discord.com/invite/my-server"
    ) == ["https://discord.com/invite/my-server"]


def test_extract_discord_urls_deduplicates_case_insensitively():
    text = "https://Discord.GG/ABC and https://discord.gg/abc"
    result = extract_discord_urls(text)
    assert len(result) == 1


def test_extract_discord_urls_finds_multiple():
    text = "https://discord.gg/one and https://discord.gg/two"
    assert extract_discord_urls(text) == [
        "https://discord.gg/one",
        "https://discord.gg/two",
    ]


def test_extract_discord_urls_returns_empty_for_none():
    assert extract_discord_urls(None) == []


def test_extract_discord_urls_returns_empty_for_no_match():
    assert extract_discord_urls("no discord here") == []


def test_extract_discord_urls_handles_www_prefix():
    assert extract_discord_urls("https://www.discord.gg/test") == [
        "https://www.discord.gg/test"
    ]


# ---------------------------------------------------------------------------
# dominant_language
# ---------------------------------------------------------------------------


def test_dominant_language_returns_majority():
    assert dominant_language(["en", "en", "de"]) == "en"


def test_dominant_language_returns_none_for_all_none():
    assert dominant_language([None, None]) is None


def test_dominant_language_returns_none_for_empty():
    assert dominant_language([]) is None


def test_dominant_language_ignores_none_values():
    assert dominant_language([None, "fr", None, "fr"]) == "fr"


def test_dominant_language_handles_single_value():
    assert dominant_language(["ja"]) == "ja"


# ---------------------------------------------------------------------------
# chunks
# ---------------------------------------------------------------------------


def test_chunks_splits_evenly():
    assert chunks(["a", "b", "c", "d"], 2) == [["a", "b"], ["c", "d"]]


def test_chunks_handles_remainder():
    assert chunks(["a", "b", "c"], 2) == [["a", "b"], ["c"]]


def test_chunks_returns_empty_for_empty_input():
    assert chunks([], 5) == []


def test_chunks_size_larger_than_input():
    assert chunks(["x", "y"], 10) == [["x", "y"]]


# ---------------------------------------------------------------------------
# mean_int / median_int
# ---------------------------------------------------------------------------


def test_mean_int_basic():
    assert mean_int([10, 20, 30]) == 20


def test_mean_int_rounds():
    assert mean_int([1, 2]) == 2  # 1.5 rounds to 2


def test_mean_int_ignores_none():
    assert mean_int([None, 100, None]) == 100


def test_mean_int_returns_none_for_all_none():
    assert mean_int([None, None]) is None


def test_median_int_basic():
    assert median_int([1, 3, 2]) == 2


def test_median_int_even_count():
    assert median_int([1, 2, 3, 4]) == 2  # median of 2,3 = 2.5 → 2


def test_median_int_ignores_none():
    assert median_int([None, 50, None]) == 50


def test_median_int_returns_none_for_all_none():
    assert median_int([None]) is None


# ---------------------------------------------------------------------------
# optional_int
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [
        (42, 42),
        ("42", 42),
        (3.9, 3),
        ("0", 0),
        (None, None),
        ("", None),
        ("abc", None),
        ({}, None),
        (True, 1),
        (False, 0),
    ],
)
def test_optional_int(value, expected):
    assert optional_int(value) == expected


# ---------------------------------------------------------------------------
# as_list
# ---------------------------------------------------------------------------


def test_as_list_returns_list_unchanged():
    lst = [1, 2, 3]
    assert as_list(lst) is lst


def test_as_list_returns_empty_for_non_list():
    assert as_list({"key": "value"}) == []
    assert as_list(None) == []
    assert as_list("string") == []


# ---------------------------------------------------------------------------
# parse_iso_datetime
# ---------------------------------------------------------------------------


def test_parse_iso_datetime_with_z_suffix():
    dt = parse_iso_datetime("2026-03-24T10:00:00Z")
    assert dt is not None
    assert dt.tzinfo is not None
    assert dt == datetime(2026, 3, 24, 10, 0, 0, tzinfo=UTC)


def test_parse_iso_datetime_with_offset():
    dt = parse_iso_datetime("2026-03-24T10:00:00+00:00")
    assert dt is not None
    assert dt == datetime(2026, 3, 24, 10, 0, 0, tzinfo=UTC)


def test_parse_iso_datetime_returns_none_for_garbage():
    assert parse_iso_datetime("not-a-date") is None


def test_parse_iso_datetime_returns_none_for_none():
    assert parse_iso_datetime(None) is None


def test_parse_iso_datetime_returns_none_for_empty():
    assert parse_iso_datetime("") is None


# ---------------------------------------------------------------------------
# count_recent_timestamps
# ---------------------------------------------------------------------------


def test_count_recent_timestamps_counts_within_window():
    now = datetime(2026, 3, 24, tzinfo=UTC)
    recent = (now - timedelta(days=5)).isoformat()
    old = (now - timedelta(days=40)).isoformat()
    assert count_recent_timestamps([recent, old, None], days=30, now=now) == 1


def test_count_recent_timestamps_returns_zero_for_empty():
    assert count_recent_timestamps([], days=30) == 0


# ---------------------------------------------------------------------------
# latest_timestamp
# ---------------------------------------------------------------------------


def test_latest_timestamp_returns_max():
    older = "2026-03-20T10:00:00+00:00"
    newer = "2026-03-24T10:00:00+00:00"
    assert latest_timestamp([older, newer, None]) == newer


def test_latest_timestamp_returns_none_for_all_none():
    assert latest_timestamp([None, None]) is None


def test_latest_timestamp_returns_none_for_empty():
    assert latest_timestamp([]) is None


# ---------------------------------------------------------------------------
# strip_html_tags
# ---------------------------------------------------------------------------


def test_strip_html_tags_removes_tags():
    assert strip_html_tags("<b>bold</b> text") == "bold  text"


def test_strip_html_tags_handles_nested():
    assert "hello" in strip_html_tags("<div><p>hello</p></div>")


def test_strip_html_tags_preserves_plain_text():
    assert strip_html_tags("no tags here") == "no tags here"


def test_strip_html_tags_handles_links():
    html = '<a href="https://example.com">click</a>'
    result = strip_html_tags(html)
    assert "click" in result
    assert "<a" not in result
