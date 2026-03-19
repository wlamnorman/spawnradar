"""Seed a dev account for local development. Not for production use."""

from __future__ import annotations

import sys

from app.devtools.bootstrap import DEV_EMAIL, DEV_PASSWORD, ensure_dev_user


def seed_dev_account(db_path: str) -> None:
    """Ensure the local dev account exists and print its credentials."""
    ensure_dev_user(db_path)
    print(f"Dev account ready: {DEV_EMAIL} / {DEV_PASSWORD}")


if __name__ == "__main__":
    seed_dev_account(
        sys.argv[1] if len(sys.argv) > 1 else "data/spawnradar.sqlite3"
    )
