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
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(schema_sql)
        _ensure_customer_games_compat(conn)
        _ensure_igdb_games_compat(conn)
        conn.commit()


def _column_exists(
    conn: sqlite3.Connection, table_name: str, column_name: str
) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(row[1] == column_name for row in rows)


def _ensure_customer_games_compat(conn: sqlite3.Connection) -> None:
    """Add newly introduced columns for existing local databases."""
    if not _column_exists(conn, "customer_games", "platforms"):
        conn.execute(
            "ALTER TABLE customer_games ADD COLUMN platforms TEXT NOT NULL DEFAULT '[]'"
        )


def _ensure_igdb_games_compat(conn: sqlite3.Connection) -> None:
    """Add newly introduced columns for existing cached IGDB games."""
    if not _column_exists(conn, "igdb_games", "developer_names_json"):
        conn.execute(
            "ALTER TABLE igdb_games ADD COLUMN developer_names_json TEXT NOT NULL DEFAULT '[]'"
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
