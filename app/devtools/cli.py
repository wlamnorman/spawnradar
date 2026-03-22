"""Local developer CLI for seeding and maintenance tasks."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from app.auth.repository import PasswordResetTokenRepository, UserRepository
from app.auth.service import AuthService
from app.billing.repository import (
    DiscoveryRunRepository,
    SubscriptionRepository,
)
from app.billing.service import BillingService
from app.config import Settings
from app.database import get_connection, initialize_database
from app.devtools.bootstrap import DEV_EMAIL, ensure_dev_user
from app.devtools.game_presets import load_game_presets, save_game_presets
from app.email.service import EmailService
from app.games.repository import (
    AssetRepository,
    GameRepository,
    MessageTemplateRepository,
)
from app.games.service import GameService

PRESET_KEYS = ("wikiquests", "strife-of-stars", "forgetting-hour")


@dataclass(frozen=True)
class CommandResult:
    """Structured command result for printing and testing."""

    message: str
    created: bool | None = None
    deleted_count: int | None = None


def _load_preset(preset_key: str, preset_path: str | Path | None = None) -> dict[str, object]:
    presets = load_game_presets(preset_path)
    try:
        preset = presets[preset_key]
    except KeyError as exc:
        choices = ", ".join(sorted(presets))
        raise ValueError(
            f"Unknown game preset '{preset_key}'. Expected one of: {choices}."
        ) from exc
    return dict(preset)


def _find_dev_game(
    db_path: str, game_ref: str | None, *, fallback_name: str
):
    user = ensure_dev_user(db_path)
    games = GameRepository(db_path).list_by_user(user.user_id)
    target = (game_ref or fallback_name).strip()
    for game in games:
        if game.slug == target or game.name == target:
            return game
    raise ValueError(
        f"No dev game found matching '{target}'. Save the game first, then retry."
    )


def _snapshot_payload_for_game(game) -> dict[str, object]:
    audience_tags = game.audience_primary_tags or game.ordered_audience_tags()
    mechanics_tags = game.mechanics_primary_tags or game.ordered_mechanics_tags()
    tone_tags = game.tone_primary_tags or game.ordered_tone_tags()
    return {
        "name": game.name,
        "summary": game.summary or "",
        "description": game.description,
        "genre_tags_raw": ", ".join(game.genre_tags),
        "genre_primary_tags_raw": ", ".join(game.genre_primary_tags),
        "genre_secondary_tags_raw": ", ".join(game.genre_secondary_tags),
        "audience_tags_raw": ", ".join(game.audience_tags),
        "audience_primary_tags_raw": ", ".join(audience_tags),
        "mechanics_primary_tags_raw": ", ".join(mechanics_tags),
        "tone_primary_tags_raw": ", ".join(tone_tags),
        "platform_tags": list(game.platform_tags),
        "website_url": game.website_url,
    }


def _seed_preset_game(
    db_path: str, preset_key: str, preset_path: str | Path | None = None
) -> CommandResult:
    preset = _load_preset(preset_key, preset_path)
    return _seed_game(
        db_path,
        name=str(preset["name"]),
        summary=str(preset.get("summary", "")),
        description=str(preset["description"]),
        genre_tags_raw=str(preset.get("genre_tags_raw", "")),
        genre_primary_tags_raw=str(preset.get("genre_primary_tags_raw", "")),
        genre_secondary_tags_raw=str(preset.get("genre_secondary_tags_raw", "")),
        audience_tags_raw=str(preset.get("audience_tags_raw", "")),
        audience_primary_tags_raw=str(preset.get("audience_primary_tags_raw", "")),
        mechanics_primary_tags_raw=str(preset.get("mechanics_primary_tags_raw", "")),
        tone_primary_tags_raw=str(preset.get("tone_primary_tags_raw", "")),
        platform_tags=list(cast(list[str], preset.get("platform_tags", []))),
        website_url=cast(str | None, preset.get("website_url")),
    )


def build_parser() -> argparse.ArgumentParser:
    """Create the top-level parser for the `sr` CLI."""
    parser = argparse.ArgumentParser(prog="sr")
    parser.add_argument(
        "--db-path",
        default=Settings.from_env().db_path,
        help="SQLite database path. Defaults to DB_PATH or the local dev DB.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)
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
    snapshot_game_preset = subparsers.add_parser(
        "snapshot-game-preset",
        help="Overwrite a built-in dev game preset from the current local DB state.",
    )
    snapshot_game_preset.add_argument(
        "preset_key",
        choices=PRESET_KEYS,
        help="Preset to update from the saved game in your local DB.",
    )
    snapshot_game_preset.add_argument(
        "--game",
        help="Game slug or exact name to snapshot. Defaults to the preset's game name.",
    )
    subparsers.add_parser(
        "clear-queues",
        help="Delete all draft queue items and their outcomes from the database.",
    )
    subparsers.add_parser(
        "rm-db",
        help="Delete the local SQLite database file and related WAL/SHM files.",
    )
    subparsers.add_parser(
        "activate-sub",
        help="Give the dev account an active paid subscription (skips Paddle).",
    )
    subparsers.add_parser(
        "activate-trial",
        help="Reset the dev account to an active 3-day trial (clears any subscription).",
    )
    subparsers.add_parser(
        "expire-trial",
        help="Expire the dev account's trial so it appears to have run out.",
    )
    subparsers.add_parser(
        "expire-sub",
        help="Cancel the dev account's subscription so it appears lapsed.",
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
    reset_discovery_runs = subparsers.add_parser(
        "reset-discovery-runs",
        help="Delete recorded discovery runs for a local user so rate limits reset.",
    )
    reset_discovery_runs.add_argument(
        "email",
        nargs="?",
        default=DEV_EMAIL,
        help=(
            "Email address whose recorded discovery runs should be deleted. "
            f"Defaults to {DEV_EMAIL}."
        ),
    )
    return parser


def _seed_game(
    db_path: str,
    *,
    name: str,
    summary: str = "",
    description: str,
    genre_tags_raw: str = "",
    genre_primary_tags_raw: str = "",
    genre_secondary_tags_raw: str = "",
    audience_tags_raw: str = "",
    audience_primary_tags_raw: str = "",
    mechanics_primary_tags_raw: str = "",
    tone_primary_tags_raw: str = "",
    platform_tags: list[str],
    website_url: str | None,
) -> CommandResult:
    """Create or update a game under the local dev account."""
    initialize_database(db_path)
    user = ensure_dev_user(db_path)
    game_repo = GameRepository(db_path)
    service = GameService(
        game_repo,
        AssetRepository(db_path),
        MessageTemplateRepository(db_path),
    )

    existing = next(
        (
            game
            for game in game_repo.list_by_user(user.user_id)
            if game.name == name
        ),
        None,
    )
    payload = {
        "name": name,
        "summary": summary,
        "description": description,
        "genre_tags_raw": genre_tags_raw,
        "genre_primary_tags_raw": genre_primary_tags_raw,
        "genre_secondary_tags_raw": genre_secondary_tags_raw,
        "audience_tags_raw": audience_tags_raw,
        "audience_primary_tags_raw": audience_primary_tags_raw,
        "mechanics_primary_tags_raw": mechanics_primary_tags_raw,
        "tone_primary_tags_raw": tone_primary_tags_raw,
        "platform_tags": platform_tags,
        "website_url": website_url,
    }

    if existing is None:
        game = service.create_game(user_id=user.user_id, **payload)
        return CommandResult(
            message=(
                f"Created {name} for {DEV_EMAIL} "
                f"({game.game_id}) at {game.website_url or 'no website'}"
            ),
            created=True,
        )

    game = service.update_game(
        game_id=existing.game_id,
        user_id=user.user_id,
        **payload,
    )
    return CommandResult(
        message=(
            f"Updated {name} for {DEV_EMAIL} "
            f"({game.game_id}) at {game.website_url or 'no website'}"
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


def run_clear_queues(db_path: str) -> CommandResult:
    """Delete all queued draft data from the local database."""
    initialize_database(db_path)
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS count FROM draft_items"
        ).fetchone()
        deleted_count = row["count"] if row is not None else 0
        conn.execute("DELETE FROM draft_items")
    suffix = "item" if deleted_count == 1 else "items"
    return CommandResult(
        message=f"Cleared {deleted_count} queued draft {suffix}.",
        deleted_count=deleted_count,
    )


def run_activate_sub(db_path: str) -> CommandResult:
    """Give the dev account a fake active paid subscription."""
    initialize_database(db_path)
    user = ensure_dev_user(db_path)
    sub_repo = SubscriptionRepository(db_path)
    billing = BillingService(sub_repo, GameRepository(db_path))
    billing.get_or_create_subscription(user.user_id)
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


def run_start_trial(db_path: str) -> CommandResult:
    """Reset the dev account to an active trial subscription."""
    initialize_database(db_path)
    user = ensure_dev_user(db_path)
    trial_ends_at = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    now = datetime.now(UTC).isoformat()
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE subscriptions SET status = 'active', trial_ends_at = ?, "
            "paddle_customer_id = NULL, paddle_subscription_id = NULL, updated_at = ? "
            "WHERE user_id = ?",
            (trial_ends_at, now, user.user_id),
        )
        if conn.execute("SELECT changes()").fetchone()[0] == 0:
            # No existing subscription — create one
            sub_repo = SubscriptionRepository(db_path)
            BillingService(
                sub_repo, GameRepository(db_path)
            ).get_or_create_subscription(user.user_id)
    return CommandResult(
        message=f"Trial started for {DEV_EMAIL} (expires in 3 days).",
    )


def run_expire_trial(db_path: str) -> CommandResult:
    """Set the dev account's trial end date to the past so it appears expired."""
    initialize_database(db_path)
    user = ensure_dev_user(db_path)
    sub_repo = SubscriptionRepository(db_path)
    billing = BillingService(sub_repo, GameRepository(db_path))
    billing.get_or_create_subscription(user.user_id)
    expired_at = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE subscriptions SET trial_ends_at = ?, status = 'active', "
            "paddle_customer_id = NULL, paddle_subscription_id = NULL, updated_at = ? "
            "WHERE user_id = ?",
            (expired_at, datetime.now(UTC).isoformat(), user.user_id),
        )
    return CommandResult(
        message=f"Trial expired for {DEV_EMAIL} (trial_ends_at set to yesterday).",
    )


def run_expire_sub(db_path: str) -> CommandResult:
    """Cancel the dev account's subscription so it appears lapsed."""
    initialize_database(db_path)
    user = ensure_dev_user(db_path)
    sub_repo = SubscriptionRepository(db_path)
    billing = BillingService(sub_repo, GameRepository(db_path))
    billing.get_or_create_subscription(user.user_id)
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE subscriptions SET status = 'canceled', trial_ends_at = NULL, "
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
    )
    billing = BillingService(
        SubscriptionRepository(db_path),
        GameRepository(db_path),
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


def run_reset_discovery_runs(
    db_path: str, email: str = DEV_EMAIL
) -> CommandResult:
    """Delete recorded discovery runs for a local user."""
    initialize_database(db_path)
    user = UserRepository(db_path).get_by_email(email)
    if user is None:
        return CommandResult(message=f"No account found for {email}.")

    deleted_count = DiscoveryRunRepository(db_path).delete_for_user(
        user.user_id
    )
    suffix = "run" if deleted_count == 1 else "runs"
    return CommandResult(
        message=(
            f"Reset discovery usage for {email}. "
            f"Deleted {deleted_count} recorded {suffix}."
        ),
        deleted_count=deleted_count,
    )


def run_rm_db(db_path: str) -> CommandResult:
    """Delete the local SQLite database file and sidecar files."""
    removed = 0
    db_file = Path(db_path)
    for path in (db_file, Path(f"{db_path}-shm"), Path(f"{db_path}-wal")):
        if path.exists():
            path.unlink()
            removed += 1
    if removed == 0:
        return CommandResult(message=f"No database files found at {db_path}.")
    suffix = "file" if removed == 1 else "files"
    return CommandResult(
        message=f"Removed {removed} database {suffix} for {db_path}.",
        deleted_count=removed,
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
    elif args.command == "snapshot-game-preset":
        result = run_snapshot_game_preset(
            args.db_path, args.preset_key, game_ref=args.game
        )
    elif args.command == "clear-queues":
        result = run_clear_queues(args.db_path)
    elif args.command == "rm-db":
        result = run_rm_db(args.db_path)
    elif args.command == "activate-sub":
        result = run_activate_sub(args.db_path)
    elif args.command == "activate-trial":
        result = run_start_trial(args.db_path)
    elif args.command == "expire-trial":
        result = run_expire_trial(args.db_path)
    elif args.command == "expire-sub":
        result = run_expire_sub(args.db_path)
    elif args.command == "grant-comp":
        result = run_grant_comp(
            args.db_path,
            args.emails,
            create_missing=args.create_missing,
            send_reset=args.send_reset,
        )
    elif args.command == "reset-discovery-runs":
        result = run_reset_discovery_runs(args.db_path, args.email)
    else:
        raise ValueError(f"Unsupported command: {args.command}")

    print(result.message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
