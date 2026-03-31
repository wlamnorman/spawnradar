"""Read-only SQL queries for the admin dashboard."""

from __future__ import annotations

from app.database import get_connection


def get_dashboard_data(db_path: str) -> dict:
    """Fetch all data needed to render the admin dashboard."""
    with get_connection(db_path) as conn:
        conn.row_factory = _dict_factory

        # Aggregate stats
        stats = conn.execute(
            """
            SELECT
                (SELECT count(*) FROM users) AS total_accounts,
                (SELECT count(*) FROM customer_games) AS total_games,
                (SELECT count(*) FROM subscriptions WHERE status = 'comped') AS comped_accounts,
                (SELECT count(*) FROM subscriptions
                 WHERE status = 'active' AND current_period_end IS NOT NULL) AS paid_accounts
            """
        ).fetchone()

        # All users with subscription info
        users = conn.execute(
            """
            SELECT
                u.user_id,
                u.email,
                u.google_id IS NOT NULL AS signed_up_with_google,
                u.created_at,
                s.status AS sub_status,
                s.trial_ends_at
            FROM users u
            LEFT JOIN subscriptions s ON u.user_id = s.user_id
            WHERE u.is_admin = 0
            ORDER BY u.created_at DESC
            """
        ).fetchall()

        # All games with prospect counts and last prospect view
        games = conn.execute(
            """
            SELECT
                cg.customer_game_id,
                cg.user_id,
                cg.name,
                cg.slug,
                cg.summary,
                cg.description,
                cg.platforms,
                cg.igdb_genre_ids,
                cg.igdb_theme_ids,
                cg.created_at,
                (SELECT count(*)
                 FROM prospect_statuses ps
                 WHERE ps.customer_game_id = cg.customer_game_id) AS prospect_count,
                (SELECT max(me.occurred_at)
                 FROM metric_events me
                 WHERE me.customer_game_id = cg.customer_game_id
                   AND me.metric_key = 'prospect_pages_viewed') AS last_prospect_view
            FROM customer_games cg
            ORDER BY cg.created_at DESC
            """
        ).fetchall()

    # Group games by user_id
    games_by_user: dict[str, list[dict]] = {}
    for g in games:
        games_by_user.setdefault(g["user_id"], []).append(g)

    customers = []
    for u in users:
        customers.append(
            {
                **u,
                "games": games_by_user.get(u["user_id"], []),
            }
        )

    return {
        **stats,
        "customers": customers,
    }


def _dict_factory(cursor, row):
    return {col[0]: row[i] for i, col in enumerate(cursor.description)}
