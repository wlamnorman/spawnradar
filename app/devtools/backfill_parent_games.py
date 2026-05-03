"""One-shot script: backfill IGDB parent_game_id.

Usage:
    python -m app.devtools.backfill_parent_games [--db-path PATH]
"""

from __future__ import annotations

import argparse
import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


async def _run(db_path: str) -> int:
    # Lazy imports to avoid circular import issues when run as a script.
    from app.config import Settings
    from app.database import initialize_database

    settings = Settings.from_env()
    resolved_db = db_path or settings.db_path

    # Ensure new columns exist before writing to them.
    initialize_database(resolved_db)

    from app.igdb.sync import IGDBSyncService

    svc = IGDBSyncService(
        db_path=resolved_db,
        client_id=settings.twitch_client_id,
        client_secret=settings.twitch_client_secret,
    )
    return await svc.backfill_parent_games()


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill IGDB parent games")
    parser.add_argument(
        "--db-path", default="", help="SQLite path (defaults to DB_PATH env)"
    )
    args = parser.parse_args()
    updated = asyncio.run(_run(args.db_path))
    print(f"Done — updated {updated} rows.")


if __name__ == "__main__":
    main()
