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
        _migrate_match_workflow_statuses(conn)
        conn.commit()


def _migrate_match_workflow_statuses(conn: sqlite3.Connection) -> None:
    """Rename legacy stored match workflow statuses to the current values."""
    row = conn.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type = 'table' AND name = 'match_statuses'
        """
    ).fetchone()
    table_sql = str(row["sql"] or "") if row is not None else ""
    if "DEFAULT 'new'" in table_sql:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS match_statuses__migrated (
                customer_game_id TEXT NOT NULL REFERENCES customer_games(customer_game_id) ON DELETE CASCADE,
                account_id       TEXT NOT NULL REFERENCES source_accounts(account_id) ON DELETE CASCADE,
                status           TEXT NOT NULL DEFAULT 'suggested',
                notes            TEXT NOT NULL DEFAULT '',
                updated_at       TEXT NOT NULL,
                PRIMARY KEY (customer_game_id, account_id)
            );

            INSERT INTO match_statuses__migrated (
                customer_game_id, account_id, status, notes, updated_at
            )
            SELECT
                customer_game_id,
                account_id,
                CASE
                    WHEN status = 'new' THEN 'suggested'
                    WHEN status = 'access_shared' THEN 'to_cover'
                    ELSE status
                END,
                notes,
                updated_at
            FROM match_statuses;

            DROP TABLE match_statuses;
            ALTER TABLE match_statuses__migrated RENAME TO match_statuses;

            CREATE INDEX IF NOT EXISTS idx_match_statuses_game_status
                ON match_statuses(customer_game_id, status);
            """
        )
        return

    conn.execute(
        """
        UPDATE match_statuses
        SET status = 'suggested'
        WHERE status = 'new'
        """
    )
    conn.execute(
        """
        UPDATE match_statuses
        SET status = 'to_cover'
        WHERE status = 'access_shared'
        """
    )


@contextmanager
def get_connection(db_path: str) -> Generator[sqlite3.Connection, None, None]:
    """Yield a SQLite connection with row_factory and runtime PRAGMAs set.

    Usage::

        with get_connection(settings.db_path) as conn:
            row = conn.execute("SELECT * FROM users WHERE user_id = ?", (uid,)).fetchone()
    """
    conn = sqlite3.connect(db_path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=15000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA temp_store=MEMORY")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
