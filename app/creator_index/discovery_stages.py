"""Reference game building, Twitch category bridging and category crawling.

Extracted from ``discovery.py`` — see that module's docstring for the full
pipeline overview.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

import httpx

from app.creator_index.stream_discovery import TwitchStreamClient
from app.creator_index.twitch_http import twitch_request_json
from app.games.models import CustomerGame
from app.igdb.client import IGDBClient
from app.igdb.models import IGDBGame
from app.igdb.repository import IGDBRepository
from app.igdb.taxonomy import canonical_to_igdb_aliases

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReferenceGame:
    """An IGDB game used as a crawl target, with Twitch category info."""

    igdb_game: IGDBGame
    twitch_category_id: str | None = None
    twitch_category_name: str | None = None
    priority: int = 0  # lower = higher priority (similar games first)


# ---------------------------------------------------------------------------
# Stage A: Build reference game set
# ---------------------------------------------------------------------------


async def resolve_similar_games(
    names: Sequence[str],
    igdb_client: IGDBClient,
) -> list[IGDBGame]:
    """Resolve free-text game names to IGDB games via search."""
    games: list[IGDBGame] = []
    seen: set[int] = set()
    for name in names:
        if not name.strip():
            continue
        results = await igdb_client.fetch_games_by_name(name.strip(), limit=3)
        if not results:
            log.warning("Similar game not found on IGDB: %s", name)
            continue
        # Pick best match: prefer exact name match, fall back to first
        best = results[0]
        name_lower = name.strip().lower()
        for r in results:
            if r.name.lower() == name_lower:
                best = r
                break
        if best.igdb_id not in seen:
            seen.add(best.igdb_id)
            games.append(best)
            log.debug(
                "Similar game resolved: '%s' → %s (id=%d)",
                name,
                best.name,
                best.igdb_id,
            )
    return games


async def run_keyword_queries(
    customer_game: CustomerGame,
    igdb_client: IGDBClient,
    existing_ids: set[int],
) -> list[IGDBGame]:
    """Progressive IGDB keyword queries (the exp14 strategy).

    Q1: core genres AND keywords
    Q2: core genres AND themes (if <30 new games)
    Q3: keywords only (if <30 new games)
    """
    all_games: dict[int, IGDBGame] = {}

    # Expand canonical keywords to all IGDB aliases, then resolve to numeric IDs.
    # e.g. "deckbuilder" → ["deck building", "deck-building", "deckbuilder"]

    all_igdb_keyword_names: list[str] = []
    for canonical in customer_game.igdb_keyword_ids:
        all_igdb_keyword_names.extend(canonical_to_igdb_aliases(canonical))

    keyword_id_map: dict[str, int] = {}
    if all_igdb_keyword_names:
        keyword_id_map = await igdb_client.resolve_keyword_ids(
            all_igdb_keyword_names
        )
    keyword_ids = list(keyword_id_map.values())

    genre_ids = [
        g for g in customer_game.igdb_genre_ids if g != 32
    ]  # drop Indie
    if not genre_ids:
        genre_ids = list(customer_game.igdb_genre_ids)
    theme_ids = list(customer_game.igdb_theme_ids)

    # Q1: genres + keywords
    if keyword_ids:
        results = await igdb_client.fetch_games_by_keywords(
            keyword_ids,
            genre_ids=genre_ids,
            limit=50,
        )
        for g in results:
            if g.igdb_id not in existing_ids:
                all_games[g.igdb_id] = g

    # Q2: genres + themes
    if theme_ids and len(all_games) < 30:
        results = await igdb_client.fetch_games_by_keywords(
            [],
            genre_ids=genre_ids,
            theme_ids=theme_ids,
            limit=50,
        )
        for g in results:
            if g.igdb_id not in existing_ids and g.igdb_id not in all_games:
                all_games[g.igdb_id] = g

    # Q3: keywords only
    if keyword_ids and len(all_games) < 30:
        results = await igdb_client.fetch_games_by_keywords(
            keyword_ids,
            limit=50,
        )
        for g in results:
            if g.igdb_id not in existing_ids and g.igdb_id not in all_games:
                all_games[g.igdb_id] = g

    log.debug(
        "Keyword queries found %d new reference games for '%s'",
        len(all_games),
        customer_game.name,
    )
    return list(all_games.values())


# ---------------------------------------------------------------------------
# Two-hop expansion: discover new reference games from top creators
# ---------------------------------------------------------------------------

_EXPANSION_MIN_CREATORS = (
    3  # game must be shared by at least this many top creators
)
_EXPANSION_TOP_CREATORS = 20  # how many top creators to sample from
_EXPANSION_MAX_GAMES = 20  # cap on expanded games


def _find_expansion_games(
    db_path: str,
    customer_game: CustomerGame,
    exclude_igdb_ids: set[int],
) -> list[tuple[int, str]]:
    """Find games shared by top creators that aren't in the reference set.

    Queries ``creator_games_played`` for games that 3+ of the top 20
    creators (by tag overlap) share, excluding games already in the
    reference set.  Returns ``[(igdb_id, game_name), ...]``.

    This is pure SQL — zero API calls.
    """
    from app.creator_index.matching import customer_game_tag_keys
    from app.database import get_connection

    game_tags = customer_game_tag_keys(customer_game)
    if not game_tags:
        return []

    # Build a CTE for the customer game's tags
    tag_values = []
    tag_params: list[object] = []
    for tag_type, tag_id in game_tags:
        tag_values.append("SELECT ? AS tag_type, ? AS tag_id")
        tag_params.extend([tag_type, str(tag_id)])
    tags_cte = " UNION ALL ".join(tag_values)

    # Build exclusion list (parameterized to avoid SQL injection)
    exclude_params: list[object] = []
    if exclude_igdb_ids:
        exclude_placeholders = ",".join("?" for _ in exclude_igdb_ids)
        exclude_clause = (
            f"AND cgp2.igdb_game_id NOT IN ({exclude_placeholders})"
        )
        exclude_params = list(exclude_igdb_ids)
    else:
        exclude_clause = ""

    sql = f"""
        WITH game_tags AS (
            {tags_cte}
        ),
        -- Find creators with tag overlap (top N by overlap count)
        top_creators AS (
            SELECT ctc.account_id, COUNT(DISTINCT gt.tag_id) AS overlap_count
            FROM (
                SELECT cgp.account_id, igt.tag_type, igt.tag_id
                FROM creator_games_played cgp
                JOIN igdb_game_tags igt ON igt.igdb_id = cgp.igdb_game_id
                WHERE cgp.igdb_game_id IS NOT NULL
                GROUP BY cgp.account_id, igt.tag_type, igt.tag_id
            ) ctc
            JOIN game_tags gt ON gt.tag_type = ctc.tag_type
                              AND gt.tag_id = CAST(ctc.tag_id AS TEXT)
            GROUP BY ctc.account_id
            ORDER BY overlap_count DESC
            LIMIT {_EXPANSION_TOP_CREATORS}
        )
        -- Find games shared by 3+ top creators, excluding reference set
        SELECT cgp2.igdb_game_id, ig.name, COUNT(DISTINCT cgp2.account_id) AS shared_count
        FROM creator_games_played cgp2
        JOIN top_creators tc ON tc.account_id = cgp2.account_id
        JOIN igdb_games ig ON ig.igdb_id = cgp2.igdb_game_id
        WHERE cgp2.igdb_game_id IS NOT NULL
          {exclude_clause}
        GROUP BY cgp2.igdb_game_id
        HAVING shared_count >= {_EXPANSION_MIN_CREATORS}
        ORDER BY shared_count DESC
        LIMIT {_EXPANSION_MAX_GAMES}
    """

    all_params = tag_params + exclude_params
    with get_connection(db_path) as conn:
        rows = conn.execute(sql, all_params).fetchall()

    results = [(int(row[0]), str(row[1])) for row in rows]
    if results:
        log.info(
            "[%s] Two-hop expansion: %d games shared by %d+ top creators",
            customer_game.name,
            len(results),
            _EXPANSION_MIN_CREATORS,
        )
    return results


async def build_reference_games(
    customer_game: CustomerGame,
    igdb_client: IGDBClient,
    igdb_repo: IGDBRepository,
    *,
    db_path: str | None = None,
) -> list[ReferenceGame]:
    """Build the full reference game set with 4 priority tiers.

    0. Customer + LLM tight anchors (always crawled)
    1. IGDB keyword games (rotated)
    2. LLM broad anchors (rotated after keywords)
    3. Two-hop expansion games (discovered from top creators' game libraries)

    All resolved games are persisted to the IGDB cache.
    """
    reference_games: list[ReferenceGame] = []
    seen_ids: set[int] = set()

    # 1. Customer-provided + LLM-suggested similar games (highest priority)
    similar_names = customer_game.all_similar_game_names
    if similar_names:
        similar_games = await resolve_similar_games(similar_names, igdb_client)
        for g in similar_games:
            seen_ids.add(g.igdb_id)
            igdb_repo.upsert(g)
            reference_games.append(ReferenceGame(igdb_game=g, priority=0))
    else:
        if not customer_game.igdb_keyword_ids:
            log.debug(
                "[%s] No similar games and no keywords — using genre+theme only",
                customer_game.name,
            )

    # 2. Progressive IGDB keyword queries
    keyword_games = await run_keyword_queries(
        customer_game, igdb_client, seen_ids
    )
    for g in keyword_games:
        seen_ids.add(g.igdb_id)
        igdb_repo.upsert(g)
        reference_games.append(ReferenceGame(igdb_game=g, priority=1))

    # 3. Broad LLM anchors (lower priority, mixed in over time via rotation)
    broad_names = list(customer_game.llm_broad_game_names)
    if broad_names:
        broad_games = await resolve_similar_games(broad_names, igdb_client)
        for g in broad_games:
            if g.igdb_id not in seen_ids:
                seen_ids.add(g.igdb_id)
                igdb_repo.upsert(g)
                reference_games.append(ReferenceGame(igdb_game=g, priority=2))

    # 4. Two-hop expansion: games shared by top creators (zero API calls)
    expansion_count = 0
    if db_path:
        expansion_games = _find_expansion_games(
            db_path,
            customer_game,
            seen_ids,
        )
        for igdb_id, _game_name in expansion_games:
            if igdb_id not in seen_ids:
                # Game is already in igdb_games (discovered via enrichment).
                # Build a minimal IGDBGame — we only need id + name for
                # the Twitch bridge.
                row = igdb_repo.get(igdb_id)
                if row is not None:
                    seen_ids.add(igdb_id)
                    minimal_game = IGDBGame(
                        igdb_id=igdb_id,
                        name=row["name"],
                        slug=row["slug"] or "",
                        summary=row["summary"],
                        genre_ids=[],
                        theme_ids=[],
                        first_release_date=row["first_release_date"],
                        cover_url=row["cover_url"],
                        platform_ids=[],
                        platform_names=[],
                        keyword_names=[],
                    )
                    reference_games.append(
                        ReferenceGame(igdb_game=minimal_game, priority=3)
                    )
                    expansion_count += 1

    similar_count = sum(1 for r in reference_games if r.priority == 0)
    keyword_count = sum(1 for r in reference_games if r.priority == 1)
    broad_count = sum(1 for r in reference_games if r.priority == 2)
    log.info(
        "Reference game set for '%s': %d similar + %d keyword + %d broad + %d expansion = %d total",
        customer_game.name,
        similar_count,
        keyword_count,
        broad_count,
        expansion_count,
        len(reference_games),
    )
    return reference_games


# ---------------------------------------------------------------------------
# Stage B: Bridge to Twitch + crawl
# ---------------------------------------------------------------------------


async def bridge_to_twitch(
    games: list[ReferenceGame],
    twitch_client: TwitchStreamClient,
) -> list[ReferenceGame]:
    """Batch-resolve IGDB games to Twitch categories.

    Returns the same list with ``twitch_category_id`` and
    ``twitch_category_name`` populated where available.
    """
    igdb_ids = [g.igdb_game.igdb_id for g in games]
    twitch_lookup: dict[int, tuple[str, str]] = {}

    for i in range(0, len(igdb_ids), 100):
        chunk = igdb_ids[i : i + 100]
        page = await twitch_client.get_games(igdb_game_ids=chunk)
        for tg in page.data:
            if tg.igdb_game_id:
                with contextlib.suppress(ValueError, TypeError):
                    twitch_lookup[int(tg.igdb_game_id)] = (
                        tg.twitch_game_id,
                        tg.name,
                    )

    bridged: list[ReferenceGame] = []
    for game in games:
        if game.igdb_game.igdb_id in twitch_lookup:
            cat_id, cat_name = twitch_lookup[game.igdb_game.igdb_id]
            bridged.append(
                ReferenceGame(
                    igdb_game=game.igdb_game,
                    twitch_category_id=cat_id,
                    twitch_category_name=cat_name,
                    priority=game.priority,
                )
            )

    log.debug(
        "Twitch bridge: %d/%d games have categories",
        len(bridged),
        len(games),
    )
    return bridged


@dataclass
class CrawlHit:
    """A broadcaster discovered in a Twitch category."""

    broadcaster_id: str
    source_game_name: str
    source_igdb_game_id: int | None


async def fetch_twitch_auth_headers(
    http: httpx.AsyncClient,
    twitch_client: TwitchStreamClient,
) -> dict[str, str]:
    return await twitch_client.auth_headers(http, force_refresh=True)


async def crawl_category(
    category_id: str,
    game_name: str,
    igdb_game_id: int | None,
    *,
    http: httpx.AsyncClient,
    auth_headers: dict[str, str],
    refresh_headers: Callable[[], Awaitable[dict[str, str]]] | None = None,
    max_stream_pages: int = 2,
    max_clips: int = 50,
    clip_started_at: str | None = None,
    clip_ended_at: str | None = None,
) -> list[CrawlHit]:
    """Crawl live streams + clips for one Twitch category.

    Pass *clip_started_at* / *clip_ended_at* (RFC3339) to fetch clips
    from a specific time window instead of all-time popular clips.
    """
    hits: list[CrawlHit] = []
    seen: set[str] = set()
    current_headers = auth_headers

    async def refresh_crawl_headers() -> dict[str, str] | None:
        nonlocal current_headers
        if refresh_headers is None:
            return current_headers
        current_headers = await refresh_headers()
        return current_headers

    # Live streams
    from app.creator_index.stream_discovery import parse_streams_page

    cursor: str | None = None
    for _ in range(max_stream_pages):
        params: list[tuple[str, str]] = [
            ("game_id", category_id),
            ("first", "100"),
        ]
        if cursor:
            params.append(("after", cursor))
        body = await twitch_request_json(
            http,
            "GET",
            "https://api.twitch.tv/helix/streams",
            headers=current_headers,
            params=params,
            refresh_headers=refresh_crawl_headers,
        )
        page = parse_streams_page(body)
        if not page.data:
            break
        for stream in page.data:
            if stream.user_id not in seen:
                seen.add(stream.user_id)
                hits.append(
                    CrawlHit(
                        broadcaster_id=stream.user_id,
                        source_game_name=game_name,
                        source_igdb_game_id=igdb_game_id,
                    )
                )
        cursor = page.pagination.cursor
        if not cursor:
            break

    # Clips — optionally time-windowed for freshness on repeat runs
    clip_params: list[tuple[str, str]] = [
        ("game_id", category_id),
        ("first", str(max_clips)),
    ]
    if clip_started_at:
        clip_params.append(("started_at", clip_started_at))
    if clip_ended_at:
        clip_params.append(("ended_at", clip_ended_at))
    clip_body = await twitch_request_json(
        http,
        "GET",
        "https://api.twitch.tv/helix/clips",
        headers=current_headers,
        params=clip_params,
        refresh_headers=refresh_crawl_headers,
    )
    clips = clip_body.get("data", []) if isinstance(clip_body, dict) else []
    for clip in clips:
        uid = clip.get("broadcaster_id")
        if uid and isinstance(uid, str) and uid not in seen:
            seen.add(uid)
            hits.append(
                CrawlHit(
                    broadcaster_id=uid,
                    source_game_name=game_name,
                    source_igdb_game_id=igdb_game_id,
                )
            )

    log.debug(
        "  Crawled %s: %d creators (streams + clips)",
        game_name,
        len(hits),
    )
    return hits
