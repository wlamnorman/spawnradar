import os
import sqlite3
import tempfile

from app.database import initialize_database


def test_igdb_tables_and_identity_links_exist():
    with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as f:
        db_path = f.name
    try:
        initialize_database(db_path)
        con = sqlite3.connect(db_path)
        try:
            tables = {
                r[0]
                for r in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            assert "igdb_games" in tables
            assert "igdb_game_tags" in tables
            assert "identity_links" in tables
        finally:
            con.close()
    finally:
        os.unlink(db_path)


def test_initialize_database_migrates_existing_bluesky_drafts_table():
    with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as f:
        db_path = f.name
    try:
        con = sqlite3.connect(db_path)
        try:
            con.executescript(
                """
                CREATE TABLE customer_games (
                    customer_game_id TEXT PRIMARY KEY,
                    slug TEXT UNIQUE
                );

                INSERT INTO customer_games (customer_game_id, slug)
                VALUES ('game-1', 'old-game-slug');

                CREATE TABLE bluesky_post_drafts (
                    draft_id TEXT PRIMARY KEY,
                    customer_game_id TEXT NOT NULL UNIQUE,
                    workspace_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'draft',
                    body TEXT NOT NULL,
                    hashtags TEXT NOT NULL DEFAULT '[]',
                    creator_handle TEXT,
                    image_filename TEXT,
                    image_media_type TEXT,
                    image_bytes BLOB,
                    image_alt_text TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                    reviewed_at TEXT,
                    approved_at TEXT,
                    rejected_at TEXT
                );

                INSERT INTO bluesky_post_drafts (
                    draft_id, customer_game_id, workspace_id, body
                )
                VALUES ('draft-1', 'game-1', 'ws-1', 'Existing body');
                """
            )
            con.commit()
        finally:
            con.close()

        initialize_database(db_path)

        con = sqlite3.connect(db_path)
        try:
            columns = {
                row[1]
                for row in con.execute(
                    "PRAGMA table_info(bluesky_post_drafts)"
                ).fetchall()
            }
            assert "creator_summary" in columns
            assert "source_game_slug" in columns

            row = con.execute(
                """
                SELECT creator_summary, source_game_slug
                FROM bluesky_post_drafts
                WHERE draft_id = 'draft-1'
                """
            ).fetchone()
            assert row is not None
            assert row[0] == "Existing body"
            assert row[1] == "old-game-slug"
        finally:
            con.close()
    finally:
        os.unlink(db_path)
