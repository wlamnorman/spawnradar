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
                (SELECT count(*)
                 FROM workspaces w
                 LEFT JOIN users u ON u.user_id = w.owner_user_id
                 WHERE COALESCE(u.is_admin, 0) = 0) AS total_workspaces,
                (SELECT count(*) FROM users WHERE is_admin = 0) AS total_accounts,
                (SELECT count(*)
                 FROM workspaces w
                 LEFT JOIN users u ON u.user_id = w.owner_user_id
                 WHERE w.workspace_type = 'guest'
                   AND COALESCE(u.is_admin, 0) = 0) AS guest_workspaces,
                (SELECT count(*) FROM customer_games) AS total_games,
                (SELECT count(*)
                 FROM subscriptions s
                 JOIN workspaces w ON w.workspace_id = s.workspace_id
                 LEFT JOIN users u ON u.user_id = w.owner_user_id
                 WHERE COALESCE(u.is_admin, 0) = 0
                   AND s.status = 'comped') AS comped_workspaces,
                (SELECT count(*)
                 FROM subscriptions s
                 JOIN workspaces w ON w.workspace_id = s.workspace_id
                 LEFT JOIN users u ON u.user_id = w.owner_user_id
                 WHERE COALESCE(u.is_admin, 0) = 0
                   AND s.status = 'active'
                   AND s.current_period_end IS NOT NULL) AS paid_workspaces
            """
        ).fetchone()

        # All non-admin workspaces with owner/guest/subscription info.
        workspaces = conn.execute(
            """
            SELECT
                w.workspace_id,
                w.workspace_type,
                w.owner_user_id,
                w.guest_id,
                w.created_at,
                w.updated_at,
                u.email,
                u.google_id IS NOT NULL AS signed_up_with_google,
                g.claimed_by_user_id,
                g.first_path,
                g.first_seen_at,
                s.status AS sub_status
            FROM workspaces w
            LEFT JOIN users u ON u.user_id = w.owner_user_id
            LEFT JOIN guest_identities g ON g.guest_id = w.guest_id
            LEFT JOIN subscriptions s ON s.workspace_id = w.workspace_id
            WHERE COALESCE(u.is_admin, 0) = 0
            ORDER BY COALESCE(g.first_seen_at, w.created_at) DESC
            """
        ).fetchall()

        # All games with prospect counts and last prospect view
        games = conn.execute(
            """
            SELECT
                cg.customer_game_id,
                cg.workspace_id,
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

    # Group games by workspace_id (personal workspaces are keyed by user_id).
    games_by_workspace: dict[str, list[dict]] = {}
    for g in games:
        games_by_workspace.setdefault(g["workspace_id"], []).append(g)

    workspace_cards = []
    for workspace in workspaces:
        is_guest = workspace["workspace_type"] == "guest"
        workspace_cards.append(
            {
                **workspace,
                "is_anonymous": is_guest,
                "display_name": workspace["email"]
                or workspace["guest_id"]
                or workspace["workspace_id"],
                "display_created_at": workspace["first_seen_at"]
                or workspace["created_at"],
                "games": games_by_workspace.get(workspace["workspace_id"], []),
            }
        )

    return {
        **stats,
        "workspaces": workspace_cards,
    }


def _dict_factory(cursor, row):
    return {col[0]: row[i] for i, col in enumerate(cursor.description)}
