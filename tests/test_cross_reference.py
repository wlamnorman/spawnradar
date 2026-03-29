import os
import sqlite3
import tempfile
import uuid
from unittest.mock import AsyncMock

import pytest

from app.creator_index.cross_reference import (
    CrossReferenceService,
    _canonical_account_pair,
    extract_youtube_urls,
)
from app.database import initialize_database


def test_extract_standard_url():
    assert "https://youtube.com/@mychannel" in extract_youtube_urls(
        "See https://youtube.com/@mychannel for more"
    )


def test_extract_deduplicates():
    assert (
        len(
            extract_youtube_urls(
                "https://youtube.com/@foo https://youtube.com/@foo"
            )
        )
        == 1
    )


def test_extract_none():
    assert extract_youtube_urls("no links") == []


def test_canonical_account_pair_is_sorted_and_rejects_self_links():
    assert _canonical_account_pair("sa_yt1", "sa_t1") == ("sa_t1", "sa_yt1")
    assert _canonical_account_pair("sa_t1", "sa_t1") is None


def _make_db(description: str) -> str:
    db = tempfile.mktemp(suffix=".sqlite3")
    initialize_database(db)
    con = sqlite3.connect(db)
    con.execute(
        """INSERT INTO source_accounts
           (account_id, platform, external_id, handle_current, display_name_current,
            canonical_url, account_type, status, first_seen_at, last_seen_at,
            created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "sa_t1", "twitch", "tw_123", "streamer1", "Streamer",
            "https://twitch.tv/streamer1", "creator", "active",
            "2026-01-01", "2026-01-01", "2026-01-01", "2026-01-01",
        ),
    )
    con.execute(
        """INSERT INTO twitch_profiles_latest
           (account_id, broadcaster_id, login, display_name, description,
            fetched_at, expires_at)
           VALUES (?,?,?,?,?,?,?)""",
        (
            "sa_t1", "tw_123", "streamer1", "Streamer", description,
            "2026-01-01", "2026-12-31",
        ),
    )
    con.commit()
    con.close()
    return db


@pytest.mark.anyio
async def test_creates_link_when_youtube_url_found():
    db = _make_db("Watch https://youtube.com/@streamer1 too")
    try:
        # The lookup returns an account_id — that account must exist in source_accounts
        con = sqlite3.connect(db)
        con.execute(
            """INSERT INTO source_accounts
               (account_id, platform, external_id, handle_current, display_name_current,
                canonical_url, account_type, status, first_seen_at, last_seen_at,
                created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "sa_yt1", "youtube", "yt_abc", "streamer1", "Streamer1",
                "https://youtube.com/@streamer1", "creator", "active",
                "2026-01-01", "2026-01-01", "2026-01-01", "2026-01-01",
            ),
        )
        con.commit()
        con.close()
        svc = CrossReferenceService(
            db_path=db,
            youtube_channel_lookup=AsyncMock(return_value="sa_yt1"),
        )
        assert await svc.run_pass(limit=10) == 1
        con = sqlite3.connect(db)
        assert len(con.execute("SELECT 1 FROM identity_links").fetchall()) == 1
        con.close()
    finally:
        os.unlink(db)


@pytest.mark.anyio
async def test_skips_account_without_youtube_url():
    db = _make_db("just streaming games")
    try:
        lookup = AsyncMock(return_value=None)
        svc = CrossReferenceService(db_path=db, youtube_channel_lookup=lookup)
        assert await svc.run_pass(limit=10) == 0
        lookup.assert_not_called()
    finally:
        os.unlink(db)


@pytest.mark.anyio
async def test_does_not_double_link():
    db = _make_db("https://youtube.com/@streamer1")
    try:
        con = sqlite3.connect(db)
        con.execute(
            """INSERT INTO source_accounts
               (account_id, platform, external_id, handle_current, display_name_current,
                canonical_url, account_type, status, first_seen_at, last_seen_at,
                created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "sa_yt1", "youtube", "yt_abc", "s1", "S",
                "https://youtube.com/@s1", "creator", "active",
                "2026-01-01", "2026-01-01", "2026-01-01", "2026-01-01",
            ),
        )
        con.execute(
            """INSERT INTO identity_links
               (link_id, account_id_a, account_id_b, link_type,
                evidence_json, created_at)
               VALUES (?,?,?,?,?,?)""",
            (
                str(uuid.uuid4()), "sa_t1", "sa_yt1",
                "social_link", "{}", "2026-01-01",
            ),
        )
        con.commit()
        con.close()
        svc = CrossReferenceService(
            db_path=db,
            youtube_channel_lookup=AsyncMock(return_value="sa_yt1"),
        )
        assert await svc.run_pass(limit=10) == 0
    finally:
        os.unlink(db)


@pytest.mark.anyio
async def test_does_not_double_link_when_existing_row_is_reversed():
    db = _make_db("https://youtube.com/@streamer1")
    try:
        con = sqlite3.connect(db)
        con.execute(
            """INSERT INTO source_accounts
               (account_id, platform, external_id, handle_current, display_name_current,
                canonical_url, account_type, status, first_seen_at, last_seen_at,
                created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "sa_yt1", "youtube", "yt_abc", "s1", "S",
                "https://youtube.com/@s1", "creator", "active",
                "2026-01-01", "2026-01-01", "2026-01-01", "2026-01-01",
            ),
        )
        con.execute(
            """INSERT INTO identity_links
               (link_id, account_id_a, account_id_b, link_type,
                evidence_json, created_at)
               VALUES (?,?,?,?,?,?)""",
            (
                str(uuid.uuid4()), "sa_yt1", "sa_t1",
                "social_link", "{}", "2026-01-01",
            ),
        )
        con.commit()
        con.close()
        svc = CrossReferenceService(
            db_path=db,
            youtube_channel_lookup=AsyncMock(return_value="sa_yt1"),
        )
        assert await svc.run_pass(limit=10) == 0
    finally:
        os.unlink(db)
