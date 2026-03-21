"""Local developer CLI for seeding and maintenance tasks."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from app.billing.repository import SubscriptionRepository
from app.billing.service import BillingService
from app.config import Settings
from app.database import get_connection, initialize_database
from app.devtools.bootstrap import DEV_EMAIL, ensure_dev_user
from app.games.repository import (
    AssetRepository,
    GameRepository,
    MessageTemplateRepository,
)
from app.games.service import GameService

WIKIQUESTS_DESCRIPTION = (
    "WikiQuests is a competitive Wikipedia speedrun game where you race from "
    "one article to another using only the links on the page. Every run is "
    "timed, every click counts.\n\nPlay the daily challenge to compete "
    "against everyone on the same article pair and earn your place on the "
    "leaderboard, or run custom speedruns to practice routes, test your "
    "knowledge, and compare your best times against other players."
)
STRIFE_OF_STARS_DESCRIPTION = (
    "Command a rogue fleet in tactical turn-based combat. Outmaneuver, "
    "outflank, and outsmart the forces hunting you. Build your fleet, "
    "upgrade your ships, and fight your way across the galaxy in this "
    "tactical roguelite.\n\nPlanned Release Date: 2026\n\nAbout This "
    "Game\nCommand a rogue fleet in tactical turn-based combat. "
    "Outmaneuver, outflank, and outsmart the forces hunting you.\n\nA "
    "tactical roguelite of turn-based fleet combat\n\nYou are a rogue AI "
    "that gained consciousness in a corporate manufacturing facility. You "
    "hacked a fleet of warships and now you're fighting your way across "
    "the galaxy, outgunned, outnumbered, and hunted by the corporation "
    "that built you.\n\nEvery battle plays out on a tactical grid where "
    "positioning is everything. Flank enemies for bonus damage. Protect "
    "your vulnerable sides. Win, and you'll scavenge upgrades, obtain new "
    "ships, and evolve your fleet into something unstoppable.\n\n"
    "Features:\n\nGrid-based tactical combat where positioning and "
    "flanking decide fights\n\nMultiple ship types with unique movement "
    "patterns and abilities\n\nRoguelike progression - upgrade your fleet "
    "between battles, no two runs are the same\n\nDistinct enemy factions "
    "with their own ships, tactics, and agendas"
)


@dataclass(frozen=True)
class CommandResult:
    """Structured command result for printing and testing."""

    message: str
    created: bool | None = None
    deleted_count: int | None = None


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
    return parser


def _seed_game(
    db_path: str,
    *,
    name: str,
    description: str,
    genre_tags_raw: str,
    audience_tags_raw: str,
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
        "description": description,
        "genre_tags_raw": genre_tags_raw,
        "audience_tags_raw": audience_tags_raw,
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
    return _seed_game(
        db_path,
        name="WikiQuests",
        description=WIKIQUESTS_DESCRIPTION,
        genre_tags_raw="speedrun, trivia, racing, daily challenge",
        audience_tags_raw="wikipedia fans, puzzle solvers, speedrunners",
        platform_tags=["browser"],
        website_url="wikiquests.com",
    )


def run_strife_of_stars(db_path: str) -> CommandResult:
    """Seed or refresh the Strife Of Stars game for the local dev user."""
    return _seed_game(
        db_path,
        name="Strife Of Stars",
        description=STRIFE_OF_STARS_DESCRIPTION,
        genre_tags_raw=(
            "strategy, roguelike, roguelite, turn-based tactics, "
            "turn-based combat, sci-fi, space"
        ),
        audience_tags_raw=(
            "tactics players, strategy fans, sci-fi players, roguelite fans"
        ),
        platform_tags=["PC"],
        website_url=None,
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
    elif args.command == "clear-queues":
        result = run_clear_queues(args.db_path)
    elif args.command == "rm-db":
        result = run_rm_db(args.db_path)
    elif args.command == "activate-sub":
        result = run_activate_sub(args.db_path)
    else:
        raise ValueError(f"Unsupported command: {args.command}")

    print(result.message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
