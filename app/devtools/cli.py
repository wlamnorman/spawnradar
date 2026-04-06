"""Local developer CLI for seeding and maintenance tasks."""

from __future__ import annotations

import argparse
import asyncio
import re
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import cast

from app.auth.repository import (
    PasswordResetTokenRepository,
    UserRepository,
    WorkspaceRepository,
)
from app.auth.service import AuthService
from app.billing.repository import SubscriptionRepository
from app.billing.service import BillingService
from app.config import Settings
from app.creator_index.enrichment import TwitchEnrichment
from app.creator_index.matching import match_creator_tags_to_game
from app.creator_index.service import CreatorIndexService
from app.creator_index.stream_discovery import TwitchStreamClient
from app.database import get_connection, initialize_database
from app.devtools.bootstrap import (
    DEV_EMAIL,
    DEV_PASSWORD,
    TEST_EMAIL,
    ensure_dev_user,
    ensure_test_user,
)
from app.devtools.game_presets import load_game_presets, save_game_presets
from app.email.service import EmailService
from app.games.repository import CustomerGameRepository
from app.games.service import CustomerGameService
from app.igdb.repository import IGDBRepository
from app.igdb.sync import IGDBSyncService
from app.runtime import SourceRuntime
from app.steam_enrichment.service import SteamTagEnrichmentService

PRESET_KEYS = (
    "wikiquests",
    "strife-of-stars",
    "forgetting-hour",
    "volgarr-the-viking-ii",
)


@dataclass(frozen=True)
class CommandResult:
    """Structured command result for printing and testing."""

    message: str
    created: bool | None = None
    deleted_count: int | None = None


def _format_rows_as_table(
    headers: tuple[str, ...], rows: Sequence[tuple[object | None, ...]]
) -> str:
    """Render simple CLI tables without external dependencies."""
    widths = [len(header) for header in headers]
    rendered_rows: list[tuple[str, ...]] = []
    for row in rows:
        rendered = tuple("" if value is None else str(value) for value in row)
        rendered_rows.append(rendered)
        for index, value in enumerate(rendered):
            widths[index] = max(widths[index], len(value))

    header_line = "  ".join(
        header.ljust(widths[index]) for index, header in enumerate(headers)
    )
    separator_line = "  ".join("-" * width for width in widths)
    body_lines = [
        "  ".join(
            value.ljust(widths[index]) for index, value in enumerate(row)
        )
        for row in rendered_rows
    ]
    return "\n".join([header_line, separator_line, *body_lines])


def _load_preset(
    preset_key: str, preset_path: str | Path | None = None
) -> dict[str, object]:
    presets = load_game_presets(preset_path)
    try:
        preset = presets[preset_key]
    except KeyError as exc:
        choices = ", ".join(sorted(presets))
        raise ValueError(
            f"Unknown game preset '{preset_key}'. Expected one of: {choices}."
        ) from exc
    return dict(preset)


def _find_dev_game(db_path: str, game_ref: str | None, *, fallback_name: str):
    user = ensure_dev_user(db_path)
    games = CustomerGameRepository(db_path).list_by_user(user.user_id)
    target = (game_ref or fallback_name).strip()
    for game in games:
        if game.slug == target or game.name == target:
            return game
    raise ValueError(
        f"No dev game found matching '{target}'. Save the game first, then retry."
    )


def _snapshot_payload_for_game(game) -> dict[str, object]:
    return {
        "name": game.name,
        "summary": game.summary or "",
        "description": game.description,
        "website_url": game.website_url,
        "platforms": game.platforms,
        "igdb_genre_ids": game.igdb_genre_ids,
        "igdb_theme_ids": game.igdb_theme_ids,
        "igdb_keyword_ids": game.igdb_keyword_ids,
        "similar_game_names": game.similar_game_names,
    }


def _normalize_game_ref(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _resolve_customer_game(db_path: str, game_ref: str):
    games = CustomerGameRepository(db_path).list_active()
    target = game_ref.strip()
    if not target:
        raise ValueError("Game reference is required.")

    normalized_target = _normalize_game_ref(target)
    exact_matches = [
        game
        for game in games
        if game.slug == target
        or game.name == target
        or _normalize_game_ref(game.slug) == normalized_target
        or _normalize_game_ref(game.name) == normalized_target
    ]
    if len(exact_matches) == 1:
        return exact_matches[0]
    if len(exact_matches) > 1:
        choices = ", ".join(
            f"{game.name} ({game.slug})" for game in exact_matches[:5]
        )
        raise ValueError(
            f"Multiple games matched '{game_ref}': {choices}. Be more specific."
        )

    ranked = sorted(
        (
            (
                max(
                    SequenceMatcher(
                        None, normalized_target, _normalize_game_ref(game.slug)
                    ).ratio(),
                    SequenceMatcher(
                        None, normalized_target, _normalize_game_ref(game.name)
                    ).ratio(),
                ),
                game,
            )
            for game in games
        ),
        key=lambda item: item[0],
        reverse=True,
    )
    if not ranked or ranked[0][0] < 0.55:
        raise ValueError(f"No customer game matched '{game_ref}'.")
    if len(ranked) > 1 and abs(ranked[0][0] - ranked[1][0]) < 0.05:
        choices = ", ".join(
            f"{game.name} ({game.slug})" for _, game in ranked[:5]
        )
        raise ValueError(
            f"Ambiguous game reference '{game_ref}'. Closest matches: {choices}."
        )
    return ranked[0][1]


def _seed_preset_game(
    db_path: str,
    preset_key: str,
    preset_path: str | Path | None = None,
    *,
    user_email: str = DEV_EMAIL,
    ensure_user: object = ensure_dev_user,
) -> CommandResult:
    preset = _load_preset(preset_key, preset_path)
    return _seed_game(
        db_path,
        name=str(preset["name"]),
        summary=str(preset.get("summary", "")),
        description=str(preset["description"]),
        website_url=cast(str | None, preset.get("website_url")),
        platforms=cast(list[str] | None, preset.get("platforms")),
        igdb_genre_ids=cast(list[int] | None, preset.get("igdb_genre_ids")),
        igdb_theme_ids=cast(list[int] | None, preset.get("igdb_theme_ids")),
        igdb_keyword_ids=cast(
            list[str] | None, preset.get("igdb_keyword_ids")
        ),
        similar_game_names=cast(
            list[str] | None, preset.get("similar_game_names")
        ),
        user_email=user_email,
        ensure_user=ensure_user,
    )


def build_parser() -> argparse.ArgumentParser:
    """Create the top-level parser for the `sr` CLI."""
    parser = argparse.ArgumentParser(
        prog="sr", formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--db-path",
        default=Settings.from_env().db_path,
        help="SQLite database path. Defaults to DB_PATH or the local dev DB.",
    )

    subparsers = parser.add_subparsers(
        dest="command", required=True, metavar="command"
    )
    subparsers.add_parser(
        "wikiquests",
        help="Create or update the local WikiQuests game under the dev account.",
    )
    subparsers.add_parser(
        "strife-of-stars",
        help="Create or update the local Strife Of Stars game under the dev account.",
    )
    subparsers.add_parser(
        "forgetting-hour",
        help="Create or update the local The Forgetting Hour game under the dev account.",
    )
    subparsers.add_parser(
        "volgarr-the-viking-ii",
        help="Create or update the local Volgarr the Viking II game under the dev account.",
    )
    subparsers.add_parser(
        "seed-test-user",
        help="Create a test user (vvilliamnorman@gmail.com) with Strife Of Stars.",
    )
    snapshot_game_preset = subparsers.add_parser(
        "snapshot-game-preset",
        help="Overwrite a built-in dev game preset from the current local DB state.",
    )
    snapshot_game_preset.add_argument(
        "preset_key",
        choices=PRESET_KEYS,
        help="Preset to update.",
    )
    snapshot_game_preset.add_argument(
        "--game",
        help="Game slug or exact name to snapshot. Defaults to the preset's game name.",
    )
    subparsers.add_parser(
        "free-account",
        help="Reset the dev account to a free user with no subscription.",
    )
    subparsers.add_parser(
        "activate-sub",
        help="Give the dev account an active paid subscription (skips Paddle).",
    )
    subparsers.add_parser(
        "expire-sub",
        help="Cancel the dev account's subscription so it appears lapsed.",
    )
    grant_admin = subparsers.add_parser(
        "grant-admin",
        help="Grant admin access to a user by email.",
    )
    grant_admin.add_argument(
        "email",
        nargs="?",
        default=DEV_EMAIL,
        help=f"Email address of the user. Defaults to {DEV_EMAIL}.",
    )
    grant_comp = subparsers.add_parser(
        "grant-comp",
        help="Grant complimentary access to one or more users by email.",
    )
    grant_comp.add_argument(
        "emails", nargs="+", help="Email addresses to comp."
    )
    grant_comp.add_argument(
        "--create-missing",
        action="store_true",
        help="Create password-less accounts for emails that do not exist yet.",
    )
    grant_comp.add_argument(
        "--send-reset",
        action="store_true",
        help="Send a password reset email so the user can set their password.",
    )
    sync_steam_tags = subparsers.add_parser(
        "sync-steam-tags",
        help="Resolve Steam links and store Steam tags for cached IGDB games.",
    )
    sync_steam_tags.add_argument(
        "--igdb-id",
        type=int,
        help="Sync one cached IGDB game by IGDB id.",
    )
    sync_steam_tags.add_argument(
        "--limit",
        type=int,
        default=25,
        help="Backfill batch size when syncing multiple games (default: 25).",
    )
    sync_steam_tags.add_argument(
        "--include-no-match",
        action="store_true",
        help="Retry games previously marked as no_match.",
    )
    subparsers.add_parser(
        "customer-ids",
        help="List all active customer game IDs with slug, owner, and name.",
    )
    get_profiles = subparsers.add_parser(
        "ccs-for",
        help="List top creator profiles for a customer game name or slug.",
    )
    get_profiles.add_argument(
        "game_ref", help="Customer game name or slug, matched fuzzily."
    )
    get_profiles.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Maximum profiles to show (default: 5).",
    )
    inspect_twitch = subparsers.add_parser(
        "inspect-twitch-igdb",
        help="Inspect the Twitch IGDB discovery path for one IGDB game ID.",
    )
    inspect_twitch.add_argument("igdb_game_id", type=int)
    inspect_twitch.add_argument(
        "--max-pages",
        type=int,
        default=3,
        help="Maximum Twitch stream pages to follow in discovery (default: 3).",
    )
    inspect_twitch.add_argument(
        "--page-size",
        type=int,
        default=20,
        help="Page size for the direct /streams inspection request (default: 20).",
    )
    inspect_twitch.add_argument(
        "--languages",
        nargs="*",
        default=["en"],
        help="Optional Twitch language filters for discovery (default: en).",
    )
    inspect_twitch.add_argument(
        "--persist",
        action="store_true",
        help="Also run the full persistence step and inspect DB rows.",
    )
    inspect_twitch.add_argument(
        "--persist-limit",
        type=int,
        default=10,
        help="Maximum discovered broadcasters to persist for debug inspection (default: 10).",
    )
    twitch_streams = subparsers.add_parser(
        "twitch-streams",
        help="Fetch one raw Twitch /helix/streams page for a Twitch game/category ID.",
    )
    twitch_streams.add_argument("twitch_game_id")
    twitch_streams.add_argument(
        "--page-size",
        type=int,
        default=20,
        help="Page size for the /streams request (default: 20).",
    )
    twitch_streams.add_argument(
        "--languages",
        nargs="*",
        default=["en"],
        help="Optional Twitch language filters (default: en).",
    )
    twitch_search_categories = subparsers.add_parser(
        "twitch-search-categories",
        help="Search Twitch categories by name to find the real Twitch category ID.",
    )
    twitch_search_categories.add_argument("query")
    twitch_search_categories.add_argument(
        "--page-size",
        type=int,
        default=20,
        help="Page size for the category search request (default: 20).",
    )
    igdb_fetch = subparsers.add_parser(
        "igdb-fetch",
        help="Fetch one IGDB game by ID into the local igdb_games table.",
    )
    igdb_fetch.add_argument("igdb_game_id", type=int)

    return parser


def _seed_game(
    db_path: str,
    *,
    name: str,
    summary: str = "",
    description: str,
    website_url: str | None,
    platforms: list[str] | None = None,
    igdb_genre_ids: list[int] | None = None,
    igdb_theme_ids: list[int] | None = None,
    igdb_keyword_ids: list[str] | None = None,
    similar_game_names: list[str] | None = None,
    user_email: str = DEV_EMAIL,
    ensure_user: object = ensure_dev_user,
) -> CommandResult:
    """Create or update a game under the specified user account."""
    initialize_database(db_path)
    user = ensure_user(db_path)  # type: ignore[operator]
    game_repo = CustomerGameRepository(db_path)
    service = CustomerGameService(game_repo)

    existing = next(
        (
            game
            for game in game_repo.list_by_user(user.user_id)
            if game.name == name
        ),
        None,
    )
    payload: dict = {
        "name": name,
        "summary": summary,
        "description": description,
        "website_url": website_url,
        "platforms": platforms,
        "igdb_genre_ids": igdb_genre_ids,
        "igdb_theme_ids": igdb_theme_ids,
        "igdb_keyword_ids": igdb_keyword_ids,
        "similar_game_names": similar_game_names,
    }

    if existing is None:
        game = service.create_game(user_id=user.user_id, **payload)
        return CommandResult(
            message=(
                f"Created {name} for {user_email} "
                f"({game.customer_game_id}) at {game.website_url or 'no website'}"
            ),
            created=True,
        )

    game = service.update_game(
        customer_game_id=existing.customer_game_id,
        user_id=user.user_id,
        **payload,
    )
    return CommandResult(
        message=(
            f"Updated {name} for {user_email} "
            f"({game.customer_game_id}) at {game.website_url or 'no website'}"
        ),
        created=False,
    )


def run_wikiquests(db_path: str) -> CommandResult:
    """Seed or refresh the WikiQuests game for the local dev user."""
    return _seed_preset_game(db_path, "wikiquests")


def run_strife_of_stars(db_path: str) -> CommandResult:
    """Seed or refresh the Strife Of Stars game for the local dev user."""
    return _seed_preset_game(db_path, "strife-of-stars")


def run_forgetting_hour(db_path: str) -> CommandResult:
    """Seed or refresh The Forgetting Hour game for the local dev user."""
    return _seed_preset_game(db_path, "forgetting-hour")


def run_volgarr_the_viking_ii(db_path: str) -> CommandResult:
    """Seed or refresh Volgarr the Viking II for the local dev user."""
    return _seed_preset_game(db_path, "volgarr-the-viking-ii")


def run_seed_test_user(db_path: str) -> CommandResult:
    """Create a test user with Strife Of Stars for non-subscriber testing."""
    return _seed_preset_game(
        db_path,
        "strife-of-stars",
        user_email=TEST_EMAIL,
        ensure_user=ensure_test_user,
    )


def run_snapshot_game_preset(
    db_path: str,
    preset_key: str,
    game_ref: str | None = None,
    *,
    preset_path: str | Path | None = None,
) -> CommandResult:
    """Overwrite a built-in dev-game preset from the saved local DB state."""
    initialize_database(db_path)
    presets = load_game_presets(preset_path)
    if preset_key not in presets:
        choices = ", ".join(sorted(presets))
        raise ValueError(
            f"Unknown game preset '{preset_key}'. Expected one of: {choices}."
        )
    fallback_name = str(presets[preset_key].get("name") or preset_key)
    game = _find_dev_game(db_path, game_ref, fallback_name=fallback_name)
    presets[preset_key] = _snapshot_payload_for_game(game)
    output_path = save_game_presets(presets, preset_path)
    return CommandResult(
        message=(
            f"Snapshotted {game.name} into preset '{preset_key}' at {output_path}."
        ),
        created=False,
    )


def run_free_account(db_path: str) -> CommandResult:
    """Reset the dev account to a free user with no subscription."""
    initialize_database(db_path)
    user = ensure_dev_user(db_path)
    sub_repo = SubscriptionRepository(db_path)
    sub_repo.delete_by_user(user.user_id)
    return CommandResult(
        message=f"Free account ready for {DEV_EMAIL} (password: {DEV_PASSWORD}). No subscription.",
    )


def run_activate_sub(db_path: str) -> CommandResult:
    """Give the dev account a fake active paid subscription."""
    initialize_database(db_path)
    user = ensure_dev_user(db_path)
    sub_repo = SubscriptionRepository(db_path)
    existing = sub_repo.get_by_user(user.user_id)
    if existing is None:
        import uuid

        from app.billing.models import Tier
        sub_repo.create(str(uuid.uuid4()), user.user_id, Tier.INDIE)
    sub_repo.update_from_paddle(
        user.user_id,
        paddle_customer_id="dev_customer",
        paddle_subscription_id="dev_subscription",
        status="active",
    )
    return CommandResult(
        message=f"Subscription activated for {DEV_EMAIL}.",
        created=True,
    )


def run_expire_sub(db_path: str) -> CommandResult:
    """Cancel the dev account's subscription so it appears lapsed."""
    initialize_database(db_path)
    user = ensure_dev_user(db_path)
    sub_repo = SubscriptionRepository(db_path)
    existing = sub_repo.get_by_user(user.user_id)
    if existing is None:
        return CommandResult(
            message=f"No subscription found for {DEV_EMAIL}.",
        )
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE subscriptions SET status = 'canceled', "
            "updated_at = ? WHERE user_id = ?",
            (datetime.now(UTC).isoformat(), user.user_id),
        )
    return CommandResult(
        message=f"Subscription canceled for {DEV_EMAIL}.",
    )


def run_grant_comp(
    db_path: str,
    emails: list[str],
    *,
    create_missing: bool = False,
    send_reset: bool = False,
) -> CommandResult:
    """Grant complimentary access to users by email."""
    initialize_database(db_path)
    settings = Settings.from_env()
    user_repo = UserRepository(db_path)
    auth = AuthService(
        user_repo,
        session_repo=None,  # type: ignore[arg-type]
        reset_token_repo=PasswordResetTokenRepository(db_path),
        workspace_repo=WorkspaceRepository(db_path),
    )
    billing = BillingService(
        SubscriptionRepository(db_path),
        CustomerGameRepository(db_path),
    )
    email_service = EmailService(
        resend_api_key=settings.resend_api_key,
        from_address=settings.email_from,
    )

    granted: list[str] = []
    created_users: list[str] = []
    reset_sent: list[str] = []
    missing: list[str] = []

    for email in emails:
        user = user_repo.get_by_email(email)
        if user is None and create_missing:
            user = auth.create_email_only_user(email)
            created_users.append(user.email)

        if user is None:
            missing.append(email)
            continue

        billing.grant_comped_access(user.user_id)
        granted.append(user.email)

        if send_reset and email_service.is_configured:
            auth.request_password_reset(
                user.email, email_service, settings.base_url
            )
            reset_sent.append(user.email)

    parts: list[str] = []
    if granted:
        parts.append(f"Granted complimentary access to: {', '.join(granted)}.")
    if created_users:
        parts.append(f"Created accounts for: {', '.join(created_users)}.")
    if send_reset:
        if reset_sent:
            parts.append(
                f"Sent password setup/reset email to: {', '.join(reset_sent)}."
            )
        elif not email_service.is_configured:
            parts.append(
                "Email is not configured, so no password setup emails were sent."
            )
    if missing:
        parts.append(f"No account found for: {', '.join(missing)}.")
    if not parts:
        parts.append("No changes made.")
    return CommandResult(
        message=" ".join(parts), created=bool(granted or created_users)
    )


def run_grant_admin(db_path: str, email: str = DEV_EMAIL) -> CommandResult:
    """Grant admin access to a user by email."""
    initialize_database(db_path)
    if email == DEV_EMAIL:
        ensure_dev_user(db_path)
    user_repo = UserRepository(db_path)
    user = user_repo.get_by_email(email)
    if user is None:
        return CommandResult(message=f"No account found for {email}.")
    if user.is_admin:
        return CommandResult(message=f"{email} is already an admin.")
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE users SET is_admin = 1 WHERE user_id = ?",
            (user.user_id,),
        )
    return CommandResult(message=f"Granted admin access to {email}.")


def run_customer_ids(db_path: str) -> CommandResult:
    """List active customer games across the product."""
    initialize_database(db_path)
    games = CustomerGameRepository(db_path).list_active()
    if not games:
        return CommandResult(message="No active customer games found.")

    rows = [
        (game.customer_game_id, game.slug, game.user_id, game.name)
        for game in games
    ]
    table = _format_rows_as_table(
        ("customer_game_id", "slug", "user_id", "name"),
        rows,
    )
    return CommandResult(
        message=f"Active customer games: {len(games)}\n{table}"
    )


def run_get_profiles(
    db_path: str, game_ref: str, *, limit: int = 5
) -> CommandResult:
    """List top creator profiles for one customer game."""
    initialize_database(db_path)
    if limit <= 0:
        raise ValueError("--limit must be greater than 0.")

    game = _resolve_customer_game(db_path, game_ref)

    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            WITH creator_tag_counts AS (
                SELECT
                    cgp.account_id AS account_id,
                    igt.tag_type AS tag_type,
                    igt.tag_id AS tag_id,
                    COUNT(DISTINCT cgp.igdb_game_id) AS tag_count
                FROM creator_games_played cgp
                JOIN igdb_game_tags igt
                  ON igt.igdb_id = cgp.igdb_game_id
                WHERE cgp.igdb_game_id IS NOT NULL
                GROUP BY cgp.account_id, igt.tag_type, igt.tag_id
            )
            SELECT
                sa.account_id AS account_id,
                sa.platform AS platform,
                COALESCE(
                    sa.display_name_current,
                    tp.display_name,
                    yc.display_name
                ) AS display_name,
                sa.handle_current AS handle,
                sa.canonical_url AS url,
                cpf.summary_text AS summary_text,
                COALESCE(
                    tp.recent_avg_live_viewers,
                    tp.viewer_count,
                    tp.recent_avg_vod_views,
                    yc.recent_avg_views,
                    0
                ) AS recent_audience,
                COALESCE(
                    tp.followers_count,
                    yc.subscriber_count,
                    0
                ) AS reach,
                cpf.last_activity_at AS last_active_at,
                ctc.tag_type AS tag_type,
                ctc.tag_id AS tag_id,
                ctc.tag_count AS tag_count
            FROM source_accounts sa
            JOIN creator_tag_counts ctc
              ON ctc.account_id = sa.account_id
            LEFT JOIN creator_profile_facets_latest cpf
              ON cpf.account_id = sa.account_id
            LEFT JOIN twitch_profiles_latest tp
              ON tp.account_id = sa.account_id
             AND sa.platform = 'twitch'
            LEFT JOIN youtube_channels_latest yc
              ON yc.account_id = sa.account_id
             AND sa.platform = 'youtube'
            WHERE cpf.platform = sa.platform OR cpf.platform IS NULL
            """,
        ).fetchall()

    accounts: dict[str, dict[str, object]] = {}
    for row in rows:
        account_id = str(row["account_id"])
        if account_id not in accounts:
            accounts[account_id] = {
                "row": row,
                "tag_counts": {},
            }
        tag_counts = accounts[account_id]["tag_counts"]
        assert isinstance(tag_counts, dict)
        tag_counts[(str(row["tag_type"]), int(row["tag_id"]))] = int(
            row["tag_count"]
        )

    scored_rows: list[
        tuple[float, tuple[tuple[str, int | str], ...], sqlite3.Row]
    ] = []
    for payload in accounts.values():
        row = payload["row"]
        assert isinstance(row, sqlite3.Row)
        tag_counts = payload["tag_counts"]
        assert isinstance(tag_counts, dict)
        match = match_creator_tags_to_game(
            game,
            creator_tag_counts=tag_counts,
        )
        if match.coverage_score <= 0:
            continue
        scored_rows.append((match.coverage_score, match.overlap_tags, row))

    scored_rows.sort(
        key=lambda item: (
            item[0],
            int(item[2]["recent_audience"] or 0),
            int(item[2]["reach"] or 0),
            str(item[2]["last_active_at"] or ""),
        ),
        reverse=True,
    )
    scored_rows = scored_rows[:limit]

    if not scored_rows:
        return CommandResult(
            message=(
                f"No matched creator profiles found for {game.name} "
                f"({game.customer_game_id})."
            )
        )

    table = _format_rows_as_table(
        (
            "coverage",
            "overlap_tags",
            "platform",
            "display_name",
            "handle",
            "recent_audience",
            "reach",
            "last_active_at",
            "url",
        ),
        [
            (
                f"{score:.3f}",
                ", ".join(
                    f"{tag_type}:{tag_id}"
                    for tag_type, tag_id in overlap_labels
                ),
                row["platform"],
                row["display_name"],
                row["handle"],
                row["recent_audience"],
                row["reach"],
                row["last_active_at"],
                row["url"],
            )
            for score, overlap_labels, row in scored_rows
        ],
    )
    return CommandResult(
        message=(
            f"Top matched creator profiles for {game.name} ({game.customer_game_id}):\n"
            f"{table}"
        )
    )


async def _run_inspect_twitch_igdb_async(
    db_path: str,
    *,
    igdb_game_id: int,
    max_pages: int,
    page_size: int,
    languages: Sequence[str],
    persist: bool,
    persist_limit: int,
) -> CommandResult:
    initialize_database(db_path)
    settings = Settings.from_env()
    if not settings.twitch_client_id or not settings.twitch_client_secret:
        raise ValueError(
            "TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET are required."
        )

    normalized_languages = tuple(
        language.strip() for language in languages if language.strip()
    )
    runtime = SourceRuntime(
        youtube_api_key=settings.youtube_api_key,
        youtube_cache_dir=settings.youtube_cache_dir,
        twitch_client_id=settings.twitch_client_id,
        twitch_client_secret=settings.twitch_client_secret,
    )
    client = TwitchStreamClient.from_runtime(runtime)
    enrichment = TwitchEnrichment(
        settings.twitch_client_id, settings.twitch_client_secret
    )
    service = CreatorIndexService(db_path=db_path, source_runtime=runtime)
    igdb_repo = IGDBRepository(db_path)
    igdb_game = igdb_repo.get(igdb_game_id)
    parts: list[str] = []
    if igdb_game is None:
        await IGDBSyncService(
            db_path=db_path,
            client_id=settings.twitch_client_id,
            client_secret=settings.twitch_client_secret,
        ).fetch_game(igdb_game_id)
        igdb_game = igdb_repo.get(igdb_game_id)
    if igdb_game is None:
        return CommandResult(
            message=(
                "Stage 0: Twitch category resolution\n"
                f"igdb_game_id={igdb_game_id} local_igdb_game=no\n"
                "resolved_category=<none>"
            )
        )

    game_name = igdb_game["name"]
    page0 = await client.get_games(igdb_game_ids=(igdb_game_id,))
    twitch_category = page0.data[0] if page0.data else None
    if twitch_category is None:
        return CommandResult(
            message=(
                "Stage 0: Twitch category resolution\n"
                f"igdb_game_id={igdb_game_id} local_igdb_game=yes "
                f"igdb_name={game_name!r} twitch_get_games_returned={len(page0.data)}\n"
                "resolved_category=<none>"
            )
        )

    page = await client.get_streams(
        game_ids=(twitch_category.twitch_game_id,),
        languages=normalized_languages,
        first=page_size,
    )
    channels = await client.get_channel_info(
        [stream.user_id for stream in page.data]
    )
    # Collect broadcaster IDs from streams
    batch_broadcaster_ids: list[str] = []
    cursor: str | None = None
    for _ in range(max_pages):
        streams_page = await client.get_streams(
            game_ids=(twitch_category.twitch_game_id,),
            languages=normalized_languages,
            first=100,
            after=cursor,
        )
        if not streams_page.data:
            break
        for stream in streams_page.data:
            if stream.user_id not in batch_broadcaster_ids:
                batch_broadcaster_ids.append(stream.user_id)
        cursor = streams_page.pagination.cursor
        if not cursor:
            break

    parts.append(
        "Stage 0: Twitch category resolution\n"
        f"igdb_game_id={igdb_game_id} local_igdb_game=yes "
        f"igdb_name={game_name!r} "
        f"twitch_get_games_returned={len(page0.data)} "
        f"twitch_category_id={twitch_category.twitch_game_id} "
        f"name={twitch_category.name!r}\n"
        f"box_art_url={twitch_category.box_art_url or '<none>'}"
    )
    stream_rows = [
        (
            stream.user_id,
            stream.user_login,
            stream.user_name,
            stream.twitch_game_id,
            stream.language,
            stream.viewer_count,
            stream.stream_title,
        )
        for stream in page.data
    ]
    stream_table = _format_rows_as_table(
        (
            "user_id",
            "user_login",
            "user_name",
            "twitch_game_id",
            "language",
            "viewer_count",
            "stream_title",
        ),
        stream_rows,
    )
    parts.append(
        "Stage 1: /helix/streams\n"
        f"filters: twitch_game_id={twitch_category.twitch_game_id} languages={list(normalized_languages) or ['<none>']} first={page_size}\n"
        f"returned_streams={len(page.data)} next_cursor={page.pagination.cursor or '<none>'}\n"
        f"{stream_table}"
    )

    channel_rows = [
        (
            channel.broadcaster_id,
            channel.broadcaster_login,
            channel.broadcaster_name,
            channel.broadcaster_language,
            channel.twitch_game_id,
            channel.game_name,
            ", ".join(channel.tags[:4]) if channel.tags else None,
            channel.title,
            channel.description,
        )
        for channel in channels.data
    ]
    channel_table = _format_rows_as_table(
        (
            "broadcaster_id",
            "login",
            "name",
            "language",
            "twitch_game_id",
            "game_name",
            "tags",
            "title",
            "description",
        ),
        channel_rows,
    )
    parts.append(
        "Stage 2: /helix/channels\n"
        f"requested_broadcasters={len(page.data)} returned_channels={len(channels.data)}\n"
        f"{channel_table}"
    )

    parts.append(
        "Stage 3: stream crawl\n"
        f"max_pages={max_pages} collected_broadcasters={len(batch_broadcaster_ids)}"
    )

    if persist:
        selected_broadcaster_ids = list(
            dict.fromkeys(batch_broadcaster_ids[: max(0, persist_limit)])
        )
        bundles_list = []
        for bid in selected_broadcaster_ids:
            bundle = await enrichment.enrich_broadcaster(bid)
            if bundle is not None:
                bundles_list.append(bundle)
        (
            persisted_accounts,
            _persisted_samples,
            _persisted_contacts,
        ) = await service._persist_bundles("twitch", bundles_list)
        with get_connection(db_path) as conn:
            if not selected_broadcaster_ids:
                rows: list[sqlite3.Row] = []
                linked_rows: list[sqlite3.Row] = []
            else:
                placeholders = ",".join("?" for _ in selected_broadcaster_ids)
                rows = conn.execute(
                    f"""
                    SELECT
                        sa.account_id,
                        sa.external_id,
                        sa.handle_current,
                        tp.display_name,
                        tp.followers_count,
                        COUNT(DISTINCT cgp.game_name_key) AS creator_games_played,
                        COUNT(DISTINCT cs.sample_id) AS content_samples,
                        COUNT(DISTINCT cp.contact_point_id) AS contact_points
                    FROM source_accounts sa
                    LEFT JOIN twitch_profiles_latest tp
                      ON tp.account_id = sa.account_id
                    LEFT JOIN creator_games_played cgp
                      ON cgp.account_id = sa.account_id
                    LEFT JOIN content_samples_latest cs
                      ON cs.account_id = sa.account_id
                    LEFT JOIN contact_points cp
                      ON cp.account_id = sa.account_id
                    WHERE sa.platform = 'twitch'
                      AND sa.external_id IN ({placeholders})
                    GROUP BY
                        sa.account_id,
                        sa.external_id,
                        sa.handle_current,
                        tp.display_name,
                        tp.followers_count
                    ORDER BY tp.followers_count DESC, sa.external_id ASC
                    LIMIT 20
                    """,
                    tuple(selected_broadcaster_ids),
                ).fetchall()
                linked_rows = conn.execute(
                    f"""
                    SELECT
                        sa.external_id,
                        sa.handle_current,
                        cgp.game_name_raw,
                        cgp.igdb_game_id,
                        cgp.observation_count
                    FROM creator_games_played cgp
                    JOIN source_accounts sa
                      ON sa.account_id = cgp.account_id
                    WHERE sa.platform = 'twitch'
                      AND sa.external_id IN ({placeholders})
                    ORDER BY sa.external_id ASC, cgp.game_name_key ASC
                    LIMIT 50
                    """,
                    tuple(selected_broadcaster_ids),
                ).fetchall()
        persisted_table = _format_rows_as_table(
            (
                "account_id",
                "external_id",
                "handle",
                "display_name",
                "followers",
                "creator_games_played",
                "content_samples",
                "contact_points",
            ),
            [
                (
                    row["account_id"],
                    row["external_id"],
                    row["handle_current"],
                    row["display_name"],
                    row["followers_count"],
                    row["creator_games_played"],
                    row["content_samples"],
                    row["contact_points"],
                )
                for row in rows
            ],
        )
        parts.append(
            "Stage 4: persisted rows\n"
            f"requested_persist_broadcasters={len(selected_broadcaster_ids)} persisted_accounts={persisted_accounts}\n"
            f"{persisted_table}"
        )
        linked_table = _format_rows_as_table(
            (
                "external_id",
                "handle",
                "game_name_raw",
                "igdb_game_id",
                "observation_count",
            ),
            [
                (
                    row["external_id"],
                    row["handle_current"],
                    row["game_name_raw"],
                    row["igdb_game_id"],
                    row["observation_count"],
                )
                for row in linked_rows
            ],
        )
        parts.append(f"Stage 5: linked creator games\n{linked_table}")

    return CommandResult(message="\n\n".join(parts))


def run_inspect_twitch_igdb(
    db_path: str,
    *,
    igdb_game_id: int,
    max_pages: int = 3,
    page_size: int = 20,
    languages: Sequence[str] = ("en",),
    persist: bool = False,
    persist_limit: int = 10,
) -> CommandResult:
    return asyncio.run(
        _run_inspect_twitch_igdb_async(
            db_path,
            igdb_game_id=igdb_game_id,
            max_pages=max_pages,
            page_size=page_size,
            languages=languages,
            persist=persist,
            persist_limit=persist_limit,
        )
    )


async def _run_twitch_streams_async(
    *,
    twitch_game_id: str,
    page_size: int,
    languages: Sequence[str],
) -> CommandResult:
    settings = Settings.from_env()
    if not settings.twitch_client_id or not settings.twitch_client_secret:
        raise ValueError(
            "TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET are required."
        )

    normalized_languages = tuple(
        language.strip() for language in languages if language.strip()
    )
    runtime = SourceRuntime(
        youtube_api_key=settings.youtube_api_key,
        youtube_cache_dir=settings.youtube_cache_dir,
        twitch_client_id=settings.twitch_client_id,
        twitch_client_secret=settings.twitch_client_secret,
    )
    client = TwitchStreamClient.from_runtime(runtime)
    page = await client.get_streams(
        game_ids=(twitch_game_id,),
        languages=normalized_languages,
        first=page_size,
    )
    rows = [
        (
            stream.user_id,
            stream.user_login,
            stream.user_name,
            stream.twitch_game_id,
            stream.language,
            stream.viewer_count,
            stream.stream_title,
        )
        for stream in page.data
    ]
    table = _format_rows_as_table(
        (
            "user_id",
            "user_login",
            "user_name",
            "twitch_game_id",
            "language",
            "viewer_count",
            "stream_title",
        ),
        rows,
    )
    return CommandResult(
        message=(
            f"Twitch /helix/streams for game_id={twitch_game_id} "
            f"languages={list(normalized_languages) or ['<none>']} "
            f"first={page_size}\n"
            f"returned_streams={len(page.data)} "
            f"next_cursor={page.pagination.cursor or '<none>'}\n"
            f"{table}"
        )
    )


def run_twitch_streams(
    *,
    twitch_game_id: str,
    page_size: int = 20,
    languages: Sequence[str] = ("en",),
) -> CommandResult:
    return asyncio.run(
        _run_twitch_streams_async(
            twitch_game_id=twitch_game_id,
            page_size=page_size,
            languages=languages,
        )
    )


async def _run_twitch_search_categories_async(
    *,
    query: str,
    page_size: int,
) -> CommandResult:
    settings = Settings.from_env()
    if not settings.twitch_client_id or not settings.twitch_client_secret:
        raise ValueError(
            "TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET are required."
        )

    runtime = SourceRuntime(
        youtube_api_key=settings.youtube_api_key,
        youtube_cache_dir=settings.youtube_cache_dir,
        twitch_client_id=settings.twitch_client_id,
        twitch_client_secret=settings.twitch_client_secret,
    )
    client = TwitchStreamClient.from_runtime(runtime)
    page = await client.search_categories(query=query, first=page_size)
    rows = [
        (category.category_id, category.name, category.box_art_url)
        for category in page.data
    ]
    table = _format_rows_as_table(
        ("category_id", "name", "box_art_url"),
        rows,
    )
    return CommandResult(
        message=(
            f"Twitch /helix/search/categories for query={query!r} "
            f"first={page_size}\n"
            f"returned_categories={len(page.data)} "
            f"next_cursor={page.pagination.cursor or '<none>'}\n"
            f"{table}"
        )
    )


def run_twitch_search_categories(
    *,
    query: str,
    page_size: int = 20,
) -> CommandResult:
    return asyncio.run(
        _run_twitch_search_categories_async(
            query=query,
            page_size=page_size,
        )
    )


async def _run_igdb_fetch_async(
    db_path: str,
    *,
    igdb_game_id: int,
) -> CommandResult:
    initialize_database(db_path)
    settings = Settings.from_env()
    if not settings.twitch_client_id or not settings.twitch_client_secret:
        raise ValueError(
            "TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET are required."
        )

    service = IGDBSyncService(
        db_path=db_path,
        client_id=settings.twitch_client_id,
        client_secret=settings.twitch_client_secret,
    )
    fetched = await service.fetch_game(igdb_game_id)
    if not fetched:
        return CommandResult(
            message=f"No IGDB game found for id={igdb_game_id}.",
            created=False,
        )

    row = IGDBRepository(db_path).get(igdb_game_id)
    if row is None:
        raise ValueError("Fetched IGDB game was not persisted.")
    return CommandResult(
        message=(
            f"Fetched IGDB game {row['name']} ({row['igdb_id']}) "
            f"slug={row['slug']}"
        ),
        created=True,
    )


def run_igdb_fetch(
    db_path: str,
    *,
    igdb_game_id: int,
) -> CommandResult:
    return asyncio.run(
        _run_igdb_fetch_async(
            db_path,
            igdb_game_id=igdb_game_id,
        )
    )


async def _run_sync_steam_tags_async(
    db_path: str,
    *,
    igdb_id: int | None,
    limit: int,
    include_no_match: bool,
) -> CommandResult:
    initialize_database(db_path)
    service = SteamTagEnrichmentService(db_path=db_path)
    if igdb_id is not None:
        result = await service.enrich_igdb_game(igdb_id)
        if result.status == "linked" and result.resolved_link is not None:
            return CommandResult(
                message=(
                    f"Linked igdb_id={igdb_id} to steam_app_id="
                    f"{result.resolved_link.steam_app_id} "
                    f"via {result.resolved_link.match_method}; "
                    f"stored {len(result.raw_tags)} raw tags and "
                    f"{len(result.mapped_tags)} mapped tags."
                ),
                created=True,
            )
        if result.status == "no_match":
            return CommandResult(
                message=(
                    f"No Steam match accepted for igdb_id={igdb_id} "
                    f"({result.rejection_reason or 'unresolved'})."
                ),
                created=False,
            )
        return CommandResult(
            message=(
                f"Steam sync failed for igdb_id={igdb_id}: "
                f"{'; '.join(result.errors) or 'unknown error'}"
            ),
            created=False,
        )

    summary = await service.backfill(
        limit=limit,
        include_no_match=include_no_match,
    )
    return CommandResult(
        message=(
            "Steam tag backfill: "
            f"attempted={summary.attempted} linked={summary.linked} "
            f"no_match={summary.no_match} errored={summary.errored}"
        ),
        created=summary.linked > 0,
    )


def run_sync_steam_tags(
    db_path: str,
    *,
    igdb_id: int | None = None,
    limit: int = 25,
    include_no_match: bool = False,
) -> CommandResult:
    return asyncio.run(
        _run_sync_steam_tags_async(
            db_path,
            igdb_id=igdb_id,
            limit=limit,
            include_no_match=include_no_match,
        )
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    args = build_parser().parse_args(argv)
    if args.command == "wikiquests":
        result = run_wikiquests(args.db_path)
    elif args.command == "strife-of-stars":
        result = run_strife_of_stars(args.db_path)
    elif args.command == "forgetting-hour":
        result = run_forgetting_hour(args.db_path)
    elif args.command == "volgarr-the-viking-ii":
        result = run_volgarr_the_viking_ii(args.db_path)
    elif args.command == "seed-test-user":
        result = run_seed_test_user(args.db_path)
    elif args.command == "snapshot-game-preset":
        result = run_snapshot_game_preset(
            args.db_path, args.preset_key, game_ref=args.game
        )
    elif args.command == "free-account":
        result = run_free_account(args.db_path)
    elif args.command == "activate-sub":
        result = run_activate_sub(args.db_path)
    elif args.command == "expire-sub":
        result = run_expire_sub(args.db_path)
    elif args.command == "grant-admin":
        result = run_grant_admin(args.db_path, args.email)
    elif args.command == "grant-comp":
        result = run_grant_comp(
            args.db_path,
            args.emails,
            create_missing=args.create_missing,
            send_reset=args.send_reset,
        )
    elif args.command == "sync-steam-tags":
        result = run_sync_steam_tags(
            args.db_path,
            igdb_id=args.igdb_id,
            limit=args.limit,
            include_no_match=args.include_no_match,
        )
    elif args.command == "customer-ids":
        result = run_customer_ids(args.db_path)
    elif args.command == "ccs-for":
        result = run_get_profiles(
            args.db_path, args.game_ref, limit=args.limit
        )
    elif args.command == "inspect-twitch-igdb":
        result = run_inspect_twitch_igdb(
            args.db_path,
            igdb_game_id=args.igdb_game_id,
            max_pages=args.max_pages,
            page_size=args.page_size,
            languages=tuple(args.languages),
            persist=args.persist,
            persist_limit=args.persist_limit,
        )
    elif args.command == "twitch-streams":
        result = run_twitch_streams(
            twitch_game_id=args.twitch_game_id,
            page_size=args.page_size,
            languages=tuple(args.languages),
        )
    elif args.command == "twitch-search-categories":
        result = run_twitch_search_categories(
            query=args.query,
            page_size=args.page_size,
        )
    elif args.command == "igdb-fetch":
        result = run_igdb_fetch(
            args.db_path,
            igdb_game_id=args.igdb_game_id,
        )
    else:
        raise ValueError(f"Unsupported command: {args.command}")

    print(result.message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
