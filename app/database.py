"""SQLite database connection and schema initialization."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path


def initialize_database(db_path: str) -> None:
    """Create the database file and apply the current schema.

    All table definitions live in ``app/sql/schema.sql``.  There is no
    migration system — the schema file is the single source of truth.
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    schema_path = Path(__file__).resolve().parent / "sql" / "schema.sql"
    schema_sql = schema_path.read_text(encoding="utf-8")

    with sqlite3.connect(str(path)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(schema_sql)
        _migrate_schema(conn)
        conn.commit()


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Apply additive schema fixes for existing SQLite databases.

    This project still uses schema.sql as the primary schema definition, but
    existing SQLite tables are not altered by ``CREATE TABLE IF NOT EXISTS``.
    This helper performs the small additive migrations needed when new columns
    are introduced on live tables.
    """
    _migrate_bluesky_post_drafts(conn)


def _table_columns(
    conn: sqlite3.Connection, table_name: str
) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row[1]) for row in rows}


def _migrate_bluesky_post_drafts(conn: sqlite3.Connection) -> None:
    tables = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if "bluesky_post_drafts" not in tables:
        return

    columns = _table_columns(conn, "bluesky_post_drafts")

    if "creator_summary" not in columns:
        conn.execute(
            "ALTER TABLE bluesky_post_drafts ADD COLUMN creator_summary TEXT NOT NULL DEFAULT ''"
        )
        conn.execute(
            """
            UPDATE bluesky_post_drafts
            SET creator_summary = body
            WHERE creator_summary = ''
            """
        )
        columns.add("creator_summary")

    if "source_game_slug" not in columns:
        conn.execute(
            "ALTER TABLE bluesky_post_drafts ADD COLUMN source_game_slug TEXT"
        )
        conn.execute(
            """
            UPDATE bluesky_post_drafts
            SET source_game_slug = (
                SELECT cg.slug
                FROM customer_games cg
                WHERE cg.customer_game_id = bluesky_post_drafts.customer_game_id
            )
            WHERE source_game_slug IS NULL OR source_game_slug = ''
            """
        )

    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_bluesky_post_drafts_source_game_slug
        ON bluesky_post_drafts(source_game_slug)
        WHERE source_game_slug IS NOT NULL AND source_game_slug != ''
        """
    )


@contextmanager
def get_connection(db_path: str) -> Generator[sqlite3.Connection, None, None]:
    """Yield a SQLite connection with row_factory and WAL mode enabled.

    Usage::

        with get_connection(settings.db_path) as conn:
            row = conn.execute("SELECT * FROM users WHERE user_id = ?", (uid,)).fetchone()
    """
    conn = sqlite3.connect(db_path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=15000")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
