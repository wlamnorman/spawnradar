"""Remove trial-only subscriptions that have no Paddle subscription.

These were auto-created by the old get_or_create_subscription for every
verified user. After this migration, free users have no subscription row.

Paid/comped subscriptions (with paddle_subscription_id or status='comped')
are preserved.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.database import get_connection


def migrate(db_path: str, *, dry_run: bool = False) -> int:
    """Delete trial-only subscription rows. Returns count deleted."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT subscription_id, user_id, status, trial_ends_at
            FROM subscriptions
            WHERE paddle_subscription_id IS NULL
              AND paddle_customer_id IS NULL
              AND status != 'comped'
            """
        ).fetchall()

        if dry_run:
            print(
                f"[DRY RUN] Would delete {len(rows)} trial-only subscriptions:"
            )
            for row in rows:
                print(
                    f"  user_id={row[1]} status={row[2]} trial_ends_at={row[3]}"
                )
            return len(rows)

        cursor = conn.execute(
            """
            DELETE FROM subscriptions
            WHERE paddle_subscription_id IS NULL
              AND paddle_customer_id IS NULL
              AND status != 'comped'
            """
        )
        deleted = cursor.rowcount
        print(f"Deleted {deleted} trial-only subscriptions.")
        return deleted


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Remove trial-only subscriptions."
    )
    parser.add_argument("db_path", help="Path to SQLite database")
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview without changes"
    )
    args = parser.parse_args()
    migrate(args.db_path, dry_run=args.dry_run)
