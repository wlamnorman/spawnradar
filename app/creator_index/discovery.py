"""Demand-driven creator discovery pipeline.

Builds a priority-tiered reference game set (tight anchors → IGDB keywords →
broad anchors → two-hop expansion), bridges to Twitch categories, crawls
streams + clips per category, and enriches each creator at discovery time.

The main entry point is :func:`discover_creators`, an async generator that
yields :class:`EnrichedCreator` instances as they are found.  The caller is
responsible for persistence.

Key features:
- Category rotation across runs (offset-based)
- Time-shifted clip windows for tight anchors
- Skip-recently-enriched with incremental clip deepening
- Two-hop expansion from top creators' game libraries (zero API calls)

See ``docs/DISCOVERY_PIPELINE.md`` for the full strategy documentation.
"""

from __future__ import annotations

import contextlib
import logging
import time
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from dataclasses import dataclass

import httpx

from app.creator_index.adapters.base import AccountSeedBundle
from app.creator_index.enrichment import TwitchEnrichment
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


@dataclass(frozen=True)
class EnrichedCreator:
    """A fully enriched creator yielded by the discovery pipeline."""

    bundle: AccountSeedBundle
    source_game_name: str
    source_igdb_game_id: int | None


# ---------------------------------------------------------------------------
# Stage A: Build reference game set
# ---------------------------------------------------------------------------


async def _resolve_similar_games(
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


async def _run_keyword_queries(
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
        similar_games = await _resolve_similar_games(
            similar_names, igdb_client
        )
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
    keyword_games = await _run_keyword_queries(
        customer_game, igdb_client, seen_ids
    )
    for g in keyword_games:
        seen_ids.add(g.igdb_id)
        igdb_repo.upsert(g)
        reference_games.append(ReferenceGame(igdb_game=g, priority=1))

    # 3. Broad LLM anchors (lower priority, mixed in over time via rotation)
    broad_names = list(customer_game.llm_broad_game_names)
    if broad_names:
        broad_games = await _resolve_similar_games(broad_names, igdb_client)
        for g in broad_games:
            if g.igdb_id not in seen_ids:
                seen_ids.add(g.igdb_id)
                igdb_repo.upsert(g)
                reference_games.append(ReferenceGame(igdb_game=g, priority=2))

    # 4. Two-hop expansion: games shared by top creators (zero API calls)
    expansion_count = 0
    if db_path:
        expansion_games = _find_expansion_games(
            db_path, customer_game, seen_ids,
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
        similar_count, keyword_count, broad_count, expansion_count,
        len(reference_games),
    )
    return reference_games


# ---------------------------------------------------------------------------
# Two-hop expansion: discover new reference games from top creators
# ---------------------------------------------------------------------------

_EXPANSION_MIN_CREATORS = 3  # game must be shared by at least this many top creators
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
        exclude_clause = f"AND cgp2.igdb_game_id NOT IN ({exclude_placeholders})"
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
            customer_game.name, len(results), _EXPANSION_MIN_CREATORS,
        )
    return results


# ---------------------------------------------------------------------------
# Stage B: Bridge to Twitch + crawl
# ---------------------------------------------------------------------------


async def _bridge_to_twitch(
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
class _CrawlHit:
    """A broadcaster discovered in a Twitch category."""

    broadcaster_id: str
    source_game_name: str
    source_igdb_game_id: int | None


async def _fetch_twitch_auth_headers(
    http: httpx.AsyncClient,
    twitch_client: TwitchStreamClient,
) -> dict[str, str]:
    token_resp = await http.post(
        "https://id.twitch.tv/oauth2/token",
        params={
            "client_id": twitch_client._client_id,
            "client_secret": twitch_client._client_secret,
            "grant_type": "client_credentials",
        },
    )
    token_resp.raise_for_status()
    token = token_resp.json()["access_token"]
    return {
        "Client-ID": twitch_client._client_id,
        "Authorization": f"Bearer {token}",
    }


async def _crawl_category(
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
) -> list[_CrawlHit]:
    """Crawl live streams + clips for one Twitch category.

    Pass *clip_started_at* / *clip_ended_at* (RFC3339) to fetch clips
    from a specific time window instead of all-time popular clips.
    """
    hits: list[_CrawlHit] = []
    seen: set[str] = set()
    current_headers = auth_headers

    async def refresh_crawl_headers() -> dict[str, str] | None:
        nonlocal current_headers
        if refresh_headers is None:
            return current_headers
        current_headers = await refresh_headers()
        return current_headers

    # Live streams
    from app.creator_index.stream_discovery import _parse_streams_page

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
        page = _parse_streams_page(body)
        if not page.data:
            break
        for stream in page.data:
            if stream.user_id not in seen:
                seen.add(stream.user_id)
                hits.append(
                    _CrawlHit(
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
                _CrawlHit(
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


# ---------------------------------------------------------------------------
# Stage C+D: Enrich + yield
# ---------------------------------------------------------------------------


_PROFILE_TTL_DAYS = 7
_DEEPEN_MAX_GAMES = 5  # only deepen creators with fewer than this many games


@dataclass
class _ClipState:
    """Clip enrichment state for a known broadcaster."""

    account_id: str
    clip_cursor: str | None
    clips_exhausted: bool
    games_played_count: int


def _get_clip_deepening_candidate(
    db_path: str, external_id: str,
) -> _ClipState | None:
    """Return clip state if this broadcaster is eligible for deepening.

    Eligible means: recently enriched, clips NOT exhausted, and fewer
    than ``_DEEPEN_MAX_GAMES`` games observed.  Returns ``None`` if
    the creator doesn't exist, clips are exhausted, or they already
    have enough games.
    """
    from app.database import get_connection

    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT sa.account_id, tp.clip_cursor, tp.clips_exhausted,
                   (SELECT COUNT(*) FROM creator_games_played cgp
                    WHERE cgp.account_id = sa.account_id) AS games_count
            FROM twitch_profiles_latest tp
            JOIN source_accounts sa ON tp.account_id = sa.account_id
            WHERE sa.external_id = ? AND sa.platform = 'twitch'
            LIMIT 1
            """,
            (external_id,),
        ).fetchone()
    if row is None:
        return None
    exhausted = bool(row["clips_exhausted"])
    games_count = row["games_count"]
    if exhausted or games_count >= _DEEPEN_MAX_GAMES:
        return None
    return _ClipState(
        account_id=row["account_id"],
        clip_cursor=row["clip_cursor"],
        clips_exhausted=exhausted,
        games_played_count=games_count,
    )


def _update_clip_state(
    db_path: str, account_id: str,
    cursor: str | None, exhausted: bool,
) -> None:
    """Persist updated clip cursor + exhaustion flag."""
    from app.database import get_connection

    with get_connection(db_path) as conn:
        conn.execute(
            """
            UPDATE twitch_profiles_latest
            SET clip_cursor = ?, clips_exhausted = ?
            WHERE account_id = ?
            """,
            (cursor, int(exhausted), account_id),
        )


def _is_recently_enriched(db_path: str, external_id: str) -> bool:
    """Return True if this broadcaster was enriched within the TTL window.

    Used to skip re-enrichment on repeat crawl runs, freeing API budget
    for discovering new creators instead.
    """
    from app.database import get_connection

    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT tp.fetched_at FROM twitch_profiles_latest tp
            JOIN source_accounts sa ON tp.account_id = sa.account_id
            WHERE sa.external_id = ? AND sa.platform = 'twitch'
            LIMIT 1
            """,
            (external_id,),
        ).fetchone()
    if row is None:
        return False
    from datetime import UTC, datetime, timedelta

    try:
        fetched = datetime.fromisoformat(row[0])
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=UTC)
        return (datetime.now(UTC) - fetched) < timedelta(days=_PROFILE_TTL_DAYS)
    except (ValueError, TypeError):
        return False


@dataclass
class _CreatorState:
    """Cached state for a known broadcaster — enrichment + contacts in one query."""

    account_id: str
    recently_enriched: bool
    has_contacts: bool
    clip_cursor: str | None
    clips_exhausted: bool
    games_played_count: int


def _get_creator_state(db_path: str, external_id: str) -> _CreatorState | None:
    """Fetch all needed enrichment state in one DB query.

    Returns ``None`` if the broadcaster is not in the DB at all.
    """
    from app.database import get_connection

    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT
                sa.account_id,
                tp.fetched_at,
                tp.clip_cursor,
                tp.clips_exhausted,
                (SELECT COUNT(*) FROM creator_games_played cgp
                 WHERE cgp.account_id = sa.account_id) AS games_count,
                (SELECT 1 FROM contact_points cp
                 WHERE cp.account_id = sa.account_id LIMIT 1) AS has_contact
            FROM source_accounts sa
            LEFT JOIN twitch_profiles_latest tp ON tp.account_id = sa.account_id
            WHERE sa.external_id = ? AND sa.platform = 'twitch'
            LIMIT 1
            """,
            (external_id,),
        ).fetchone()
    if row is None or row["account_id"] is None:
        return None

    # Check TTL
    recently_enriched = False
    fetched_at = row["fetched_at"]
    if fetched_at:
        from datetime import UTC, datetime, timedelta

        try:
            fetched = datetime.fromisoformat(fetched_at)
            if fetched.tzinfo is None:
                fetched = fetched.replace(tzinfo=UTC)
            recently_enriched = (datetime.now(UTC) - fetched) < timedelta(
                days=_PROFILE_TTL_DAYS
            )
        except (ValueError, TypeError):
            pass

    return _CreatorState(
        account_id=row["account_id"],
        recently_enriched=recently_enriched,
        has_contacts=row["has_contact"] is not None,
        clip_cursor=row["clip_cursor"],
        clips_exhausted=bool(row["clips_exhausted"]),
        games_played_count=row["games_count"],
    )


def _has_contacts(db_path: str, external_id: str) -> bool:
    """Check whether we already have contact points for a broadcaster."""
    from app.database import get_connection

    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT 1 FROM contact_points cp
            JOIN source_accounts sa ON cp.account_id = sa.account_id
            WHERE sa.external_id = ? AND sa.platform = 'twitch'
            LIMIT 1
            """,
            (external_id,),
        ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


_DEFAULT_DEADLINE_SECONDS = 900  # 15 minutes max per game


async def discover_creators(
    customer_game: CustomerGame,
    *,
    igdb_client: IGDBClient,
    twitch_client: TwitchStreamClient,
    enrichment: TwitchEnrichment,
    igdb_repo: IGDBRepository,
    db_path: str | None = None,
    max_categories: int = 20,
    category_offset: int = 0,
    deadline_seconds: float = _DEFAULT_DEADLINE_SECONDS,
) -> AsyncGenerator[EnrichedCreator, None]:
    """Discover and enrich content creators for a customer game.

    Yields :class:`EnrichedCreator` instances as they are found.  The
    caller is responsible for persisting each yielded creator.

    Similar games (customer-provided and LLM-suggested) are crawled first
    for fastest initial results.

    *max_categories* caps how many Twitch categories to crawl per run.
    *category_offset* rotates which slice of categories to crawl.
    Pass an incrementing offset across runs to explore different games
    each time (e.g. run 1: offset=0, run 2: offset=20, run 3: offset=40).

    *deadline_seconds* caps the total wall-clock time.  The pipeline
    stops after the current category when the deadline is exceeded.
    """
    t0 = time.monotonic()
    deadline = t0 + deadline_seconds

    # Stage A: build reference games
    log.debug("[%s] Stage A: building reference games...", customer_game.name)
    ref_games = await build_reference_games(
        customer_game,
        igdb_client,
        igdb_repo,
        db_path=db_path,
    )
    if not ref_games:
        log.warning("[%s] No reference games found", customer_game.name)
        return
    log.debug(
        "[%s] Stage A done: %d reference games (%.1fs)",
        customer_game.name,
        len(ref_games),
        time.monotonic() - t0,
    )

    # Stage B: bridge to Twitch
    t1 = time.monotonic()
    log.debug("[%s] Stage B: bridging to Twitch...", customer_game.name)
    bridged = await _bridge_to_twitch(ref_games, twitch_client)
    if not bridged:
        log.warning("[%s] No Twitch categories found", customer_game.name)
        return
    log.debug(
        "[%s] Stage B done: %d categories (%.1fs)",
        customer_game.name,
        len(bridged),
        time.monotonic() - t1,
    )

    # Split into tiers:
    #   priority 0 = tight anchors (customer + LLM tight) — always crawled
    #   priority 1 = IGDB keyword games — rotated
    #   priority 2 = LLM broad anchors — rotated after keywords
    #   priority 3 = two-hop expansion games — rotated last
    always = [r for r in bridged if r.priority == 0]
    rotated = [r for r in bridged if r.priority >= 1]

    # Rotate keyword/broad/expansion categories using the offset
    if rotated and category_offset > 0:
        effective_offset = category_offset % len(rotated)
        rotated = rotated[effective_offset:] + rotated[:effective_offset]

    # Cap so total doesn't exceed max_categories
    budget = max(0, max_categories - len(always))
    rotated = rotated[:budget]

    bridged = always + rotated
    tier_counts = {p: sum(1 for r in bridged if r.priority == p) for p in range(4)}
    log.info(
        "[%s] Crawling %d categories (%d tight + %d keyword + %d broad + %d expansion, offset=%d)",
        customer_game.name,
        len(bridged),
        tier_counts.get(0, 0),
        tier_counts.get(1, 0),
        tier_counts.get(2, 0),
        tier_counts.get(3, 0),
        category_offset,
    )

    # Get a shared auth token for category crawling and refresh it on 401.
    async with httpx.AsyncClient(timeout=20) as http:
        auth_headers = await _fetch_twitch_auth_headers(http, twitch_client)

        async def refresh_headers() -> dict[str, str]:
            nonlocal auth_headers
            auth_headers = await _fetch_twitch_auth_headers(
                http, twitch_client
            )
            return auth_headers

        # Compute time-shifted clip window for tight anchors.
        # Each run (identified by category_offset) shifts to a different
        # 30-day window so repeat crawls of the same categories surface
        # different creators.
        from datetime import UTC, datetime, timedelta

        _CLIP_WINDOW_DAYS = 30
        window_index = (category_offset // 20) % 12  # 12 windows = ~1 year
        now = datetime.now(UTC)
        window_end = now - timedelta(days=window_index * _CLIP_WINDOW_DAYS)
        window_start = window_end - timedelta(days=_CLIP_WINDOW_DAYS)
        tight_clip_started = window_start.strftime("%Y-%m-%dT%H:%M:%SZ")
        tight_clip_ended = window_end.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Stage C: crawl + enrich + yield
        seen_broadcasters: set[str] = set()
        creators_yielded = 0

        for cat_idx, ref_game in enumerate(bridged, 1):
            if time.monotonic() > deadline:
                log.warning(
                    "[%s] Deadline exceeded after %d/%d categories (%.0fs)",
                    customer_game.name, cat_idx - 1, len(bridged),
                    time.monotonic() - t0,
                )
                break

            assert ref_game.twitch_category_id is not None
            cat_name = ref_game.twitch_category_name or ref_game.igdb_game.name
            log.debug(
                "[%s] Crawling category %d/%d: %s",
                customer_game.name,
                cat_idx,
                len(bridged),
                cat_name,
            )

            # Tight anchors get time-shifted clips; others get all-time
            clip_start = tight_clip_started if ref_game.priority == 0 else None
            clip_end = tight_clip_ended if ref_game.priority == 0 else None

            hits = await _crawl_category(
                ref_game.twitch_category_id,
                cat_name,
                ref_game.igdb_game.igdb_id,
                http=http,
                auth_headers=auth_headers,
                refresh_headers=refresh_headers,
                max_stream_pages=1,
                max_clips=20,
                clip_started_at=clip_start,
                clip_ended_at=clip_end,
            )

            new_hits = [
                h for h in hits if h.broadcaster_id not in seen_broadcasters
            ]
            enriched_count = 0
            skipped_recent = 0
            for hit_idx, hit in enumerate(new_hits, 1):
                seen_broadcasters.add(hit.broadcaster_id)

                # Single query: get all state we need for this creator
                state = (
                    _get_creator_state(db_path, hit.broadcaster_id)
                    if db_path
                    else None
                )

                # Skip recently enriched — but try clip deepening if eligible
                if state and state.recently_enriched:
                    if (
                        not state.clips_exhausted
                        and state.games_played_count < _DEEPEN_MAX_GAMES
                    ):
                        new_games, next_cursor, exhausted = (
                            await enrichment.deepen_broadcaster_clips(
                                hit.broadcaster_id,
                                cursor=state.clip_cursor,
                            )
                        )
                        if new_games:
                            from app.creator_index.repository import (
                                CreatorIndexRepository,
                            )

                            assert db_path is not None
                            repo = CreatorIndexRepository(db_path)
                            game_names = tuple(
                                g.game_name for g in new_games
                            )
                            repo.upsert_creator_games_played(
                                state.account_id,
                                "twitch",
                                game_names,
                            )
                        assert db_path is not None
                        _update_clip_state(
                            db_path, state.account_id,
                            next_cursor, exhausted,
                        )
                    skipped_recent += 1
                    continue

                skip_contacts = state.has_contacts if state else False
                t_enrich = time.monotonic()
                bundle = await enrichment.enrich_broadcaster(
                    hit.broadcaster_id,
                    skip_contacts=skip_contacts,
                )
                enrich_ms = (time.monotonic() - t_enrich) * 1000
                if bundle is None:
                    log.debug(
                        "[%s]   enrichment %d/%d (broadcaster %s) → skip (%.0fms)",
                        customer_game.name,
                        hit_idx,
                        len(new_hits),
                        hit.broadcaster_id,
                        enrich_ms,
                    )
                    continue

                enriched_count += 1
                creators_yielded += 1
                log.debug(
                    "[%s]   enriched %d/%d %s (%.0fms, contacts=%s)",
                    customer_game.name,
                    hit_idx,
                    len(new_hits),
                    bundle.account.display_name_current
                    or bundle.account.handle_current,
                    enrich_ms,
                    "skipped" if skip_contacts else "fetched",
                )
                yield EnrichedCreator(
                    bundle=bundle,
                    source_game_name=hit.source_game_name,
                    source_igdb_game_id=hit.source_igdb_game_id,
                )

            if enriched_count > 0:
                log.info(
                    "[%s] %d/%d %s: +%d creators (%d total, %.0fs)",
                    customer_game.name, cat_idx, len(bridged), cat_name,
                    enriched_count, creators_yielded, time.monotonic() - t0,
                )
            else:
                log.debug(
                    "[%s] %d/%d %s: 0 new (crawled %d, skipped %d recent)",
                    customer_game.name, cat_idx, len(bridged), cat_name,
                    len(new_hits), skipped_recent,
                )

    log.info(
        "[%s] Discovery complete: %d creators from %d categories in %.1fs",
        customer_game.name,
        creators_yielded,
        len(bridged),
        time.monotonic() - t0,
    )


# ---------------------------------------------------------------------------
# Pre-population: top Twitch categories
# ---------------------------------------------------------------------------


async def crawl_top_categories(
    twitch_client: TwitchStreamClient,
    enrichment: TwitchEnrichment,
    igdb_repo: IGDBRepository,
    *,
    max_categories: int = 20,
    db_path: str | None = None,
    deadline_seconds: float = _DEFAULT_DEADLINE_SECONDS,
) -> AsyncGenerator[EnrichedCreator, None]:
    """Crawl top Twitch categories for pre-population.

    This is genre-agnostic — it discovers creators from whatever is
    popular on Twitch right now.  No CustomerGame needed.
    """
    t0 = time.monotonic()
    deadline = t0 + deadline_seconds

    async with httpx.AsyncClient(timeout=20) as http:
        auth_headers = await _fetch_twitch_auth_headers(http, twitch_client)

        async def refresh_headers() -> dict[str, str]:
            nonlocal auth_headers
            auth_headers = await _fetch_twitch_auth_headers(
                http, twitch_client
            )
            return auth_headers

        body = await twitch_request_json(
            http,
            "GET",
            "https://api.twitch.tv/helix/games/top",
            headers=auth_headers,
            params=[("first", str(min(max_categories, 100)))],
            refresh_headers=refresh_headers,
        )

        top_games = body.get("data", []) if isinstance(body, dict) else []
        log.info(
            "[top-categories] Starting crawl of %d categories", len(top_games)
        )

        seen_broadcasters: set[str] = set()
        creators_yielded = 0

        for cat_idx, game_data in enumerate(top_games, 1):
            if time.monotonic() > deadline:
                log.warning(
                    "[top-categories] Deadline exceeded after %d/%d categories (%.0fs)",
                    cat_idx - 1, len(top_games), time.monotonic() - t0,
                )
                break

            cat_id = game_data.get("id")
            cat_name = game_data.get("name", "Unknown")
            if not cat_id:
                continue

            igdb_id: int | None = None
            try:
                page = await twitch_client.get_games(twitch_game_ids=(cat_id,))
                if page.data and page.data[0].igdb_game_id:
                    igdb_id = int(page.data[0].igdb_game_id)
            except (ValueError, TypeError):
                pass

            hits = await _crawl_category(
                cat_id,
                cat_name,
                igdb_id,
                http=http,
                auth_headers=auth_headers,
                refresh_headers=refresh_headers,
                max_stream_pages=1,
                max_clips=20,
            )

            new_hits = [
                h for h in hits if h.broadcaster_id not in seen_broadcasters
            ]
            for hit in new_hits:
                seen_broadcasters.add(hit.broadcaster_id)

                # Skip recently enriched (same logic as discover_creators)
                state = (
                    _get_creator_state(db_path, hit.broadcaster_id)
                    if db_path
                    else None
                )
                if state and state.recently_enriched:
                    continue

                skip_contacts = state.has_contacts if state else False
                bundle = await enrichment.enrich_broadcaster(
                    hit.broadcaster_id,
                    skip_contacts=skip_contacts,
                )
                if bundle is None:
                    continue

                creators_yielded += 1
                yield EnrichedCreator(
                    bundle=bundle,
                    source_game_name=hit.source_game_name,
                    source_igdb_game_id=hit.source_igdb_game_id,
                )

            if new_hits:
                log.info(
                    "[top-categories] %d/%d %s: +%d creators (%d total, %.0fs)",
                    cat_idx,
                    len(top_games),
                    cat_name,
                    len(new_hits),
                    creators_yielded,
                    time.monotonic() - t0,
                )

    log.info(
        "[top-categories] Complete: %d creators from %d categories in %.1fs",
        creators_yielded,
        len(top_games),
        time.monotonic() - t0,
    )
