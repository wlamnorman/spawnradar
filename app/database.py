"""SQLite database connection and schema initialization."""
from __future__ import annotations

import re
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path


def initialize_database(db_path: str) -> None:
    """Create the database file and apply the schema if tables do not exist.

    Safe to call on every startup — uses IF NOT EXISTS guards in SQL.
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    schema_path = Path(__file__).resolve().parent.parent / "sql" / "schema.sql"
    schema_sql = schema_path.read_text(encoding="utf-8")

    with sqlite3.connect(str(path)) as conn:
        conn.executescript(schema_sql)
        conn.commit()

        # Migration: add slug column to existing databases
        try:
            conn.execute("ALTER TABLE games ADD COLUMN slug TEXT")
        except sqlite3.OperationalError:
            pass  # Column already exists

        # Backfill slugs for any games that don't have one yet
        rows = conn.execute(
            "SELECT game_id, name FROM games WHERE slug IS NULL"
        ).fetchall()
        for row in rows:
            game_id, name = row[0], row[1]
            slug_name = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
            slug = f"{slug_name}-{game_id[:8]}"
            conn.execute(
                "UPDATE games SET slug = ? WHERE game_id = ?", (slug, game_id)
            )
        conn.commit()



@contextmanager
def get_connection(db_path: str) -> Generator[sqlite3.Connection, None, None]:
    """Yield a SQLite connection with row_factory and WAL mode enabled.

    Usage::

        with get_connection(settings.db_path) as conn:
            row = conn.execute("SELECT * FROM users WHERE user_id = ?", (uid,)).fetchone()
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
