"""SQLite database connection and schema initialization."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager, suppress
from pathlib import Path

_EMPTY_TAG_PROFILE = '{"primary":[],"secondary":[],"custom":[]}'

_MIGRATIONS = [
    # Add mechanics and tone tag profile columns (safe to re-run; ignored if column exists)
    f"ALTER TABLE games ADD COLUMN mechanics_tag_profile TEXT NOT NULL DEFAULT '{_EMPTY_TAG_PROFILE}'",
    f"ALTER TABLE games ADD COLUMN tone_tag_profile TEXT NOT NULL DEFAULT '{_EMPTY_TAG_PROFILE}'",
    # Add search cursor table for progressive pagination across discovery runs
    """CREATE TABLE IF NOT EXISTS game_search_cursors (
        game_id    TEXT NOT NULL,
        source     TEXT NOT NULL,
        cursors    TEXT NOT NULL DEFAULT '{}',
        updated_at TEXT NOT NULL,
        PRIMARY KEY (game_id, source),
        FOREIGN KEY (game_id) REFERENCES games(game_id) ON DELETE CASCADE
    )""",
    # Add 1-2 line summary used in LLM scoring and game list cards
    "ALTER TABLE games ADD COLUMN summary TEXT",
    # Add main game description field for game setup and cards
    "ALTER TABLE games ADD COLUMN description TEXT NOT NULL DEFAULT ''",
    # Track public and auth request events for coarse rate limiting
    """CREATE TABLE IF NOT EXISTS request_rate_limits (
        event_id    TEXT PRIMARY KEY,
        scope       TEXT NOT NULL,
        key_hash    TEXT NOT NULL,
        created_at  TEXT NOT NULL DEFAULT (datetime('now'))
    )""",
    "CREATE INDEX IF NOT EXISTS idx_request_rate_limits_scope_key_created ON request_rate_limits(scope, key_hash, created_at)",
    "ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0",
    """CREATE TABLE IF NOT EXISTS email_verification_tokens (
    token_id    TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    expires_at  TEXT NOT NULL,
    used_at     TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
)""",
    """CREATE TABLE IF NOT EXISTS metric_events (
        event_id    TEXT PRIMARY KEY,
        metric_key  TEXT NOT NULL,
        user_id     TEXT REFERENCES users(user_id) ON DELETE SET NULL,
        game_id     TEXT REFERENCES games(game_id) ON DELETE SET NULL,
        occurred_at TEXT NOT NULL,
        value       REAL NOT NULL DEFAULT 1,
        dedupe_key  TEXT UNIQUE,
        metadata    TEXT NOT NULL DEFAULT '{}'
    )""",
    """CREATE TABLE IF NOT EXISTS discovery_run_facts (
        run_id            TEXT PRIMARY KEY,
        user_id           TEXT NOT NULL,
        game_id           TEXT NOT NULL,
        started_at        TEXT NOT NULL,
        completed_at      TEXT,
        status            TEXT NOT NULL DEFAULT 'started',
        discovered_count  INTEGER NOT NULL DEFAULT 0,
        scored_count      INTEGER NOT NULL DEFAULT 0,
        queued_count      INTEGER NOT NULL DEFAULT 0,
        error_message     TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS prospect_score_observations (
        observation_id TEXT PRIMARY KEY,
        run_id         TEXT NOT NULL,
        user_id        TEXT NOT NULL,
        game_id        TEXT NOT NULL,
        score          REAL NOT NULL,
        queued         INTEGER NOT NULL DEFAULT 0,
        occurred_at    TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_metric_events_key_occurred ON metric_events(metric_key, occurred_at)",
    "CREATE INDEX IF NOT EXISTS idx_metric_events_user_key_occurred ON metric_events(user_id, metric_key, occurred_at)",
    "CREATE INDEX IF NOT EXISTS idx_discovery_run_facts_status_started ON discovery_run_facts(status, started_at)",
    "CREATE INDEX IF NOT EXISTS idx_discovery_run_facts_user_started ON discovery_run_facts(user_id, started_at)",
    "CREATE INDEX IF NOT EXISTS idx_prospect_score_observations_occurred ON prospect_score_observations(occurred_at)",
    "CREATE INDEX IF NOT EXISTS idx_prospect_score_observations_queued ON prospect_score_observations(queued, occurred_at)",
]


def initialize_database(db_path: str) -> None:
    """Create the database file and apply the current schema, then migrate."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    schema_path = Path(__file__).resolve().parent / "sql" / "schema.sql"
    schema_sql = schema_path.read_text(encoding="utf-8")

    with sqlite3.connect(str(path)) as conn:
        conn.executescript(schema_sql)
        conn.commit()

    _run_migrations(db_path)


def _run_migrations(db_path: str) -> None:
    """Apply additive schema migrations that are safe to re-run."""
    with sqlite3.connect(db_path) as conn:
        for sql in _MIGRATIONS:
            with suppress(
                sqlite3.OperationalError
            ):  # column/table already exists
                conn.execute(sql)
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
