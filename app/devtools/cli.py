"""Local developer CLI for seeding and maintenance tasks."""

from __future__ import annotations

import argparse
import json
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
from app.config import Settings, _load_dotenv
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
    mechanics_tags = game.mechanics_primary_tags or game.ordered_mechanics_tags()
    vibe_tags = game.vibe_primary_tags or game.ordered_vibe_tags()
    kindred_tags = game.kindred_primary_tags or game.ordered_kindred_tags()
    return {
        "name": game.name,
        "summary": game.summary or "",
        "description": game.description,
        "genre_tags_raw": ", ".join(game.genre_tags),
        "genre_primary_tags_raw": ", ".join(game.genre_primary_tags),
        "genre_secondary_tags_raw": ", ".join(game.genre_secondary_tags),
        "mechanics_primary_tags_raw": ", ".join(mechanics_tags),
        "vibe_primary_tags_raw": ", ".join(vibe_tags),
        "kindred_primary_tags_raw": ", ".join(kindred_tags),
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
        mechanics_primary_tags_raw=str(preset.get("mechanics_primary_tags_raw", "")),
        vibe_primary_tags_raw=str(preset.get("vibe_primary_tags_raw", "")),
        kindred_primary_tags_raw=str(preset.get("kindred_primary_tags_raw", "")),
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
        nargs="?",
        choices=PRESET_KEYS,
        default=PRESET_KEYS[0],
        help=f"Preset to update (default: {PRESET_KEYS[0]}).",
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
    gen_tag_graph = subparsers.add_parser(
        "gen-tag-graph",
        help="Generate app/games/tag_graph.json via a one-time Sonnet call.",
    )
    gen_tag_graph.add_argument(
        "--output",
        default="app/games/tag_graph.json",
        help="Output path for the JSON graph. Default: app/games/tag_graph.json",
    )
    viz_tag_graph = subparsers.add_parser(
        "viz-tag-graph",
        help="Open an interactive browser visualisation of app/games/tag_graph.json.",
    )
    viz_tag_graph.add_argument(
        "--input",
        default="app/games/tag_graph.json",
        help="Path to the tag graph JSON. Default: app/games/tag_graph.json",
    )
    viz_tag_graph.add_argument(
        "--output",
        default=None,
        help="Write the HTML to this path instead of a temp file.",
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
    mechanics_primary_tags_raw: str = "",
    vibe_primary_tags_raw: str = "",
    kindred_primary_tags_raw: str = "",
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
        "mechanics_primary_tags_raw": mechanics_primary_tags_raw,
        "vibe_primary_tags_raw": vibe_primary_tags_raw,
        "kindred_primary_tags_raw": kindred_primary_tags_raw,
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


_TAG_GRAPH_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>SpawnRadar Tag Similarity Graph</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0f1117; color: #e2e8f0; font-family: system-ui, sans-serif; overflow: hidden; }

  #canvas { width: 100vw; height: 100vh; }

  .link { stroke-opacity: 0.5; }
  .node circle { stroke: #0f1117; stroke-width: 1.5px; cursor: pointer; }
  .node text {
    font-size: 10px; fill: #cbd5e1; pointer-events: none;
    text-anchor: middle; dominant-baseline: central;
    text-shadow: 0 0 3px #0f1117, 0 0 3px #0f1117;
  }
  .node.highlighted circle { stroke: #fff; stroke-width: 2.5px; }
  .node.faded circle { opacity: 0.15; }
  .node.faded text { opacity: 0.08; }
  .link.faded { opacity: 0.04; }
  .link.highlighted { stroke-opacity: 0.9; }

  #panel {
    position: fixed; top: 16px; left: 16px; width: 220px;
    background: rgba(15,17,23,0.92); border: 1px solid #2d3748;
    border-radius: 10px; padding: 14px; backdrop-filter: blur(4px);
  }
  #panel h1 { font-size: 13px; font-weight: 600; color: #f8fafc; margin-bottom: 10px; }
  #stats { font-size: 11px; color: #94a3b8; margin-bottom: 12px; line-height: 1.7; }
  #legend { margin-bottom: 12px; }
  .legend-row { display: flex; align-items: center; gap: 7px; font-size: 11px; color: #94a3b8; margin-bottom: 5px; cursor: pointer; user-select: none; }
  .legend-swatch { width: 11px; height: 11px; border-radius: 50%; flex-shrink: 0; }
  .legend-row.dim-off { opacity: 0.35; }
  #search-wrap { position: relative; }
  #search { width: 100%; background: #1e2533; border: 1px solid #374151; border-radius: 6px;
    padding: 6px 8px; font-size: 11px; color: #e2e8f0; outline: none; }
  #search:focus { border-color: #6366f1; }
  #search::placeholder { color: #475569; }
  #tooltip {
    position: fixed; pointer-events: none; background: rgba(15,17,23,0.95);
    border: 1px solid #374151; border-radius: 8px; padding: 10px 12px;
    font-size: 11px; line-height: 1.8; display: none; z-index: 10; max-width: 240px;
  }
  #tooltip .tt-tag { font-weight: 600; font-size: 12px; color: #f8fafc; margin-bottom: 4px; }
  #tooltip .tt-dim { color: #94a3b8; font-size: 10px; margin-bottom: 8px; }
  #tooltip .tt-neighbor { color: #cbd5e1; }
  #tooltip .tt-weight { color: #64748b; font-size: 10px; margin-left: 4px; }
  #hint { position: fixed; bottom: 14px; left: 50%; transform: translateX(-50%);
    font-size: 10px; color: #475569; pointer-events: none; }
</style>
</head>
<body>
<svg id="canvas"></svg>

<div id="panel">
  <h1>Tag Similarity Graph</h1>
  <div id="stats"></div>
  <div id="legend"></div>
  <div id="search-wrap">
    <input id="search" type="text" placeholder="Search tags…" autocomplete="off">
  </div>
</div>

<div id="tooltip"></div>
<div id="hint">scroll to zoom &nbsp;·&nbsp; drag to pan &nbsp;·&nbsp; click node to focus</div>

<script src="https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js"></script>
<script>
const GRAPH = /*GRAPH_DATA*/;

const DIM_COLOR = {
  genre:     "#6366f1",
  mechanics: "#f59e0b",
  vibe:      "#ec4899",
  kindred:   "#f97316",
};
const DIM_LABEL = { genre: "Genre", mechanics: "Mechanics", vibe: "Vibe", kindred: "Kindred" };

// Build node index from edges
const nodeMap = new Map();
GRAPH.forEach(e => {
  if (!nodeMap.has(e.from)) nodeMap.set(e.from, { id: e.from, dim: e.from_dim, degree: 0 });
  if (!nodeMap.has(e.to))   nodeMap.set(e.to,   { id: e.to,   dim: e.to_dim,   degree: 0 });
  nodeMap.get(e.from).degree++;
  nodeMap.get(e.to).degree++;
});
const nodes = Array.from(nodeMap.values());
const links = GRAPH.map(e => ({ source: e.from, target: e.to, weight: e.weight, from_dim: e.from_dim, to_dim: e.to_dim }));

// Stats
const dimCounts = {};
nodes.forEach(n => { dimCounts[n.dim] = (dimCounts[n.dim] || 0) + 1; });

document.getElementById("stats").innerHTML =
  `${nodes.length} tags &nbsp;·&nbsp; ${links.length} edges<br>` +
  Object.entries(dimCounts).map(([d, c]) => `<span style="color:${DIM_COLOR[d]}">${DIM_LABEL[d]}</span>: ${c}`).join(" &nbsp; ");

// Legend with toggle
const activeDims = new Set(Object.keys(DIM_COLOR));
const legend = document.getElementById("legend");
Object.entries(DIM_COLOR).forEach(([dim, color]) => {
  const row = document.createElement("div");
  row.className = "legend-row";
  row.dataset.dim = dim;
  row.innerHTML = `<span class="legend-swatch" style="background:${color}"></span>${DIM_LABEL[dim]}`;
  row.addEventListener("click", () => {
    if (activeDims.has(dim)) activeDims.delete(dim); else activeDims.add(dim);
    row.classList.toggle("dim-off");
    applyDimFilter();
  });
  legend.appendChild(row);
});

const svg = d3.select("#canvas");
const width = window.innerWidth, height = window.innerHeight;
svg.attr("viewBox", [0, 0, width, height]);

const g = svg.append("g");

// Zoom
svg.call(d3.zoom().scaleExtent([0.15, 4]).on("zoom", e => g.attr("transform", e.transform)));

const radiusScale = d3.scaleSqrt().domain([1, d3.max(nodes, n => n.degree)]).range([4, 14]);

const simulation = d3.forceSimulation(nodes)
  .force("link", d3.forceLink(links).id(d => d.id).distance(d => 60 + (1 - d.weight) * 80).strength(d => d.weight * 0.6))
  .force("charge", d3.forceManyBody().strength(-120))
  .force("center", d3.forceCenter(width / 2, height / 2))
  .force("collision", d3.forceCollide().radius(d => radiusScale(d.degree) + 6));

const linkEl = g.append("g").selectAll("line")
  .data(links).join("line")
  .attr("class", "link")
  .attr("stroke", d => DIM_COLOR[d.from_dim] || "#64748b")
  .attr("stroke-width", d => Math.max(0.5, d.weight * 3));

const nodeEl = g.append("g").selectAll("g.node")
  .data(nodes).join("g")
  .attr("class", "node")
  .call(d3.drag()
    .on("start", (e, d) => { if (!e.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
    .on("drag",  (e, d) => { d.fx = e.x; d.fy = e.y; })
    .on("end",   (e, d) => { if (!e.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; }))
  .on("click", (e, d) => { e.stopPropagation(); focusNode(d); })
  .on("mouseover", (e, d) => showTooltip(e, d))
  .on("mousemove", moveTooltip)
  .on("mouseout",  hideTooltip);

nodeEl.append("circle")
  .attr("r", d => radiusScale(d.degree))
  .attr("fill", d => DIM_COLOR[d.dim] || "#64748b");

nodeEl.append("text")
  .text(d => d.id)
  .attr("dy", d => radiusScale(d.degree) + 9)
  .style("font-size", d => Math.max(8, Math.min(11, radiusScale(d.degree) * 0.9)) + "px");

svg.on("click", clearFocus);

simulation.on("tick", () => {
  linkEl.attr("x1", d => d.source.x).attr("y1", d => d.source.y)
        .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
  nodeEl.attr("transform", d => `translate(${d.x},${d.y})`);
});

// Neighbour map for focus
const neighborMap = new Map();
nodes.forEach(n => neighborMap.set(n.id, new Set()));
links.forEach(l => {
  neighborMap.get(l.source.id || l.source).add(l.target.id || l.target);
  neighborMap.get(l.target.id || l.target).add(l.source.id || l.source);
});

let focused = null;

function focusNode(d) {
  if (focused === d.id) { clearFocus(); return; }
  focused = d.id;
  const neighbors = neighborMap.get(d.id) || new Set();
  nodeEl.classed("highlighted", n => n.id === d.id || neighbors.has(n.id))
        .classed("faded", n => n.id !== d.id && !neighbors.has(n.id));
  linkEl.classed("highlighted", l => (l.source.id||l.source) === d.id || (l.target.id||l.target) === d.id)
        .classed("faded", l => (l.source.id||l.source) !== d.id && (l.target.id||l.target) !== d.id);
}

function clearFocus() {
  focused = null;
  nodeEl.classed("highlighted", false).classed("faded", false);
  linkEl.classed("highlighted", false).classed("faded", false);
}

function applyDimFilter() {
  nodeEl.classed("faded", n => !activeDims.has(n.dim));
  linkEl.classed("faded", l => !activeDims.has(l.from_dim) && !activeDims.has(l.to_dim));
}

// Search
document.getElementById("search").addEventListener("input", function() {
  const q = this.value.trim().toLowerCase();
  if (!q) { clearFocus(); return; }
  const match = nodes.find(n => n.id.toLowerCase().includes(q));
  if (match) focusNode(match);
});

// Tooltip
const tip = document.getElementById("tooltip");
function showTooltip(e, d) {
  const neighbors = neighborMap.get(d.id) || new Set();
  const nearby = links
    .filter(l => (l.source.id||l.source) === d.id || (l.target.id||l.target) === d.id)
    .sort((a, b) => b.weight - a.weight)
    .slice(0, 8)
    .map(l => {
      const other = (l.source.id||l.source) === d.id ? (l.target.id||l.target) : (l.source.id||l.source);
      return `<div class="tt-neighbor">→ ${other}<span class="tt-weight">${l.weight.toFixed(2)}</span></div>`;
    }).join("");
  tip.innerHTML = `<div class="tt-tag">${d.id}</div><div class="tt-dim">${DIM_LABEL[d.dim]} · ${neighbors.size} connections</div>${nearby}`;
  tip.style.display = "block";
  moveTooltip(e);
}
function moveTooltip(e) {
  const x = e.clientX + 14, y = e.clientY - 10;
  tip.style.left = Math.min(x, window.innerWidth - 260) + "px";
  tip.style.top  = Math.max(y, 8) + "px";
}
function hideTooltip() { tip.style.display = "none"; }

window.addEventListener("resize", () => {
  const w = window.innerWidth, h = window.innerHeight;
  svg.attr("viewBox", [0, 0, w, h]);
  simulation.force("center", d3.forceCenter(w / 2, h / 2)).alpha(0.2).restart();
});
</script>
</body>
</html>
"""


_TAG_GRAPH_SYSTEM = (
    "You are an expert on indie game communities and content creators. "
    "Output ONLY a JSON array — no prose, no markdown fences. Each element: "
    '{"from":"<tag>","to":"<tag>","weight":<0.55-1.0>,"from_dim":"<genre|mechanics|vibe|kindred>","to_dim":"<genre|mechanics|vibe|kindred>"}. '
    "Include an edge when two tags share a meaningfully overlapping creator/viewer audience. "
    "Cross-dimension edges (genre↔kindred especially) are encouraged. "
    "Omit edges below 0.55. Be selective — only strong, real overlaps."
)


def run_gen_tag_graph(output: str = "app/games/tag_graph.json") -> CommandResult:
    """Generate a tag similarity graph via a one-time Claude Sonnet call."""
    import os

    import anthropic

    from app.games.tags import (
        GENRE_TAG_CATALOG,
        KINDRED_TAG_CATALOG,
        MECHANICS_TAG_CATALOG,
        VIBE_TAG_CATALOG,
    )

    _load_dotenv()
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY is not set (checked env and .env)")

    catalog_lines = [
        "GENRE tags:", *[f"  {t}" for t in GENRE_TAG_CATALOG], "",
        "MECHANICS tags:", *[f"  {t}" for t in MECHANICS_TAG_CATALOG], "",
        "VIBE tags:", *[f"  {t}" for t in VIBE_TAG_CATALOG], "",
        "KINDRED tags:", *[f"  {t}" for t in KINDRED_TAG_CATALOG],
    ]
    catalog_block = "\n".join(catalog_lines)
    total_tags = (
        len(GENRE_TAG_CATALOG) + len(MECHANICS_TAG_CATALOG)
        + len(VIBE_TAG_CATALOG) + len(KINDRED_TAG_CATALOG)
    )

    print(f"Catalog: {total_tags} tags across 4 dimensions")
    print("Model:   claude-sonnet-4-6")
    print(f"Output:  {output}")
    print("Calling API...", flush=True)

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=32000,
        system=_TAG_GRAPH_SYSTEM,
        messages=[{
            "role": "user",
            "content": f"Tag catalog:\n\n{catalog_block}\n\nReturn the JSON array.",
        }],
    )

    first_block = message.content[0]
    if not isinstance(first_block, anthropic.types.TextBlock):
        raise ValueError(f"Unexpected response block type: {type(first_block)}")
    raw = first_block.text.strip()
    if raw.startswith("```"):
        raw = "\n".join(
            line for line in raw.splitlines() if not line.startswith("```")
        ).strip()

    try:
        edges = json.loads(raw)
    except json.JSONDecodeError as e:
        raw_path = Path(output).with_name("tag_graph_raw.txt")
        raw_path.write_text(raw)
        raise ValueError(
            f"Failed to parse JSON response: {e}. Raw output saved to {raw_path}"
        ) from e

    edges.sort(key=lambda e: (-e["weight"], e["from"], e["to"]))
    Path(output).write_text(json.dumps(edges, indent=2) + "\n")

    input_tokens = message.usage.input_tokens
    output_tokens = message.usage.output_tokens
    cost = (input_tokens / 1_000_000 * 3.0) + (output_tokens / 1_000_000 * 15.0)

    by_dim: dict[str, int] = {}
    for e in edges:
        key = f"{e['from_dim']} → {e['to_dim']}"
        by_dim[key] = by_dim.get(key, 0) + 1

    print(f"\nTokens: {input_tokens} in / {output_tokens} out  (est. ${cost:.3f})")
    print("\nEdges by dimension pair:")
    for k, v in sorted(by_dim.items(), key=lambda x: -x[1]):
        print(f"  {k:<30} {v}")
    print("\nTop 20 edges by weight:")
    for e in edges[:20]:
        print(f"  {e['weight']:.2f}  {e['from']:<30} → {e['to']} ({e['from_dim']} → {e['to_dim']})")

    return CommandResult(
        message=f"Wrote {len(edges)} edges to {output}  (est. ${cost:.3f})"
    )


def run_viz_tag_graph(
    input: str = "app/games/tag_graph.json",
    output: str | None = None,
) -> CommandResult:
    """Render tag_graph.json as an interactive D3 force graph and open it."""
    import tempfile
    import webbrowser

    graph_path = Path(input)
    if not graph_path.exists():
        raise FileNotFoundError(
            f"{input} not found. Run `./sr gen-tag-graph` first."
        )

    edges = json.loads(graph_path.read_text())
    graph_json = json.dumps(edges)
    html = _TAG_GRAPH_HTML.replace("/*GRAPH_DATA*/", graph_json)

    if output:
        html_path = Path(output)
        html_path.write_text(html)
    else:
        fd, tmp = tempfile.mkstemp(suffix=".html", prefix="sr_tag_graph_")
        import os as _os
        _os.close(fd)
        Path(tmp).write_text(html)
        html_path = Path(tmp)

    webbrowser.open(html_path.as_uri())

    node_ids: set[str] = set()
    for e in edges:
        node_ids.add(e["from"])
        node_ids.add(e["to"])

    return CommandResult(
        message=(
            f"Opened visualisation: {len(node_ids)} nodes, {len(edges)} edges"
            + (f" — saved to {html_path}" if output else "")
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
    elif args.command == "gen-tag-graph":
        result = run_gen_tag_graph(args.output)
    elif args.command == "viz-tag-graph":
        result = run_viz_tag_graph(args.input, args.output)
    else:
        raise ValueError(f"Unsupported command: {args.command}")

    print(result.message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
