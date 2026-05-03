"""Local developer CLI for seeding and maintenance tasks."""

from __future__ import annotations

import argparse

from app.config import Settings
from app.devtools.bootstrap import DEV_EMAIL

# Re-export all command functions so existing imports continue to work.
from app.devtools.commands.accounts import (
    run_activate_sub,
    run_expire_sub,
    run_free_account,
    run_grant_admin,
    run_grant_comp,
    run_mint_session,
)
from app.devtools.commands.games import (
    run_forgetting_hour,
    run_seed_test_user,
    run_snapshot_game_preset,
    run_strife_of_stars,
    run_volgarr_the_viking_ii,
    run_wikiquests,
)
from app.devtools.utils import PRESET_KEYS, CommandResult

__all__ = [
    "CommandResult",
    "PRESET_KEYS",
    "build_parser",
    "main",
    "run_activate_sub",
    "run_expire_sub",
    "run_forgetting_hour",
    "run_free_account",
    "run_grant_admin",
    "run_grant_comp",
    "run_mint_session",
    "run_seed_test_user",
    "run_snapshot_game_preset",
    "run_strife_of_stars",
    "run_volgarr_the_viking_ii",
    "run_wikiquests",
]


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
    mint_session = subparsers.add_parser(
        "mint-session",
        help="Create a fresh session_id for an existing user.",
    )
    mint_session.add_argument(
        "email",
        help="Email address of the user to authenticate.",
    )

    return parser


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
    elif args.command == "mint-session":
        result = run_mint_session(args.db_path, args.email)
    else:
        raise ValueError(f"Unsupported command: {args.command}")

    print(result.message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
