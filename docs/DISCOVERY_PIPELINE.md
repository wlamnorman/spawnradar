# Discovery Pipeline

How SpawnRadar finds, enriches and ranks content creators for a customer's game. This document covers the full path from game creation to the ranked matches page.

---

## End-to-end flow

```
Customer creates/updates a game
    ↓
LLM generates tight + broad anchor games (one-time, ~$0.01)
    ↓
On-demand crawl fires 5s after save
    ↓
Every 10 min: scheduled re-crawl with rotating categories
    ↓
Creator index populated (source_accounts, profiles, contacts, games_played)
    ↓
Tag materialization (creator_account_game_tags via DB triggers)
    ↓
On request: rank_matches() scores creators against customer game tags
    ↓
Matches page: sorted by coverage score, paginated, filterable
```

---

## Phase 1: Game definition

The customer provides genres, themes, keywords and optionally up to 8 similar game names. On save, two things happen:

**LLM anchor generation** — Claude produces two tiers of reference games:
- **Tight** (enough to reach 5 total with customer picks): same subgenre, same mechanics
- **Broad** (5-10): popular games with audience overlap, different subgenre

The LLM is told what the customer already picked and complements rather than duplicates. Results are stored as `llm_similar_game_names` on the game definition and cleared if the definition changes. Generation is skipped if the Anthropic API key is not configured.

**On-demand discovery job** fires 5 seconds after save via APScheduler. If the LLM key is available and suggestions haven't been generated yet, they're generated before the crawl begins.

Key code: `app/games/service.py` → `_notify_game_changed()` → `schedule_game_discovery()` → `run_game_discovery()`

---

## Phase 2: Building the reference game set

The pipeline builds a priority-ordered list of IGDB games to crawl:

| Priority | Source | Crawl behavior |
|---|---|---|
| 0 | Customer similar games + LLM tight anchors | **Always crawled** every run |
| 1 | IGDB keyword queries (progressive: genre+keyword, genre+theme, keyword-only) | **Rotated** across runs |
| 2 | LLM broad anchors | **Rotated** after keywords |
| 3 | Two-hop expansion (games shared by top creators) | **Rotated** last |

Priority 0 games are the core — they drive initial results within seconds. The other tiers explore progressively wider, mixed in over time via a category offset that increments by 20 after each sync.

### IGDB keyword queries

Three progressive queries, each fires only if the previous returned fewer than 30 games:

1. Core genres AND keyword IDs (tightest)
2. Core genres AND themes (broader)
3. Keyword IDs only (broadest)

Canonical keywords (e.g., "deckbuilder") are expanded to all IGDB aliases ("deck building", "deck-building", "deckbuilder") before querying. The Indie genre (ID 32) is excluded to avoid overly broad results.

### Two-hop expansion

After the first run populates `creator_games_played`, a SQL query (zero API calls) in `cross_reference.py` finds games that 3+ top creators share but aren't already in the reference set. These get added as priority 3 and crawled on subsequent runs.

Key code: `app/creator_index/discovery.py`, `app/creator_index/cross_reference.py`

---

## Phase 3: Twitch bridge and category rotation

All reference games are batch-resolved to Twitch categories via the IGDB→Twitch bridge (`GET /helix/games?igdb_id=...`). The resolved mapping is persisted in `twitch_categories`.

Each run crawls up to 20 categories. Priority 0 games always fill their slots first. The remaining budget is filled from a rotating window of priority 1-3 games:

```
Run 1 (offset=0):   tight(4) + keyword[0:16]
Run 2 (offset=20):  tight(4) + keyword[16:32] + broad[0:4]
Run 3 (offset=40):  tight(4) + broad[4:10] + expansion[0:6]
Run 4 (offset=60):  tight(4) + keyword[0:16] (wraps around)
```

The offset is stored per customer game and incremented by 20 after each sync in `CreatorIndexService`.

---

## Phase 4: Per-category crawl

For each Twitch category:
- **Live streams**: 1 page (up to 100 broadcasters) via `GET /helix/streams`
- **Clips**: 20 clips per category via `GET /helix/clips`

Tight anchor categories (priority 0) get **time-shifted clips**: each run fetches a different 30-day window, cycling through 12 windows over ~1 year. This ensures deeper historical coverage. Other categories get all-time popular clips.

Key code: `app/creator_index/discovery.py`, `app/creator_index/stream_discovery.py`

---

## Phase 5: Per-creator enrichment

Each discovered broadcaster gets full enrichment via the Twitch API:

1. **Profile** — user info, channel info, follower count (`GET /helix/users`, `/helix/channels`)
2. **Clips** — per-broadcaster, 2 pages, 730-day lookback
3. **Contact info** — Twitch panels parsed for links, YouTube email fallback via channel about page
4. **Games played** — extracted from clip game IDs, deduplicated per sync

Results are persisted to:
- `source_accounts` — platform identity (handle, display name, URL)
- `twitch_profiles_latest` — current stats (followers, profile image, recent audience)
- `content_samples_latest` — recent clips/videos
- `contact_points` — email, Discord, social links
- `creator_games_played` — games observed from creator's content

### Repeat-run optimizations

**Skip recently enriched** — if a creator's profile was fetched within 7 days, skip full enrichment. Saves 4-5 API calls per known creator.

**Clip deepening** — for skipped creators whose clips are not exhausted and who have fewer than 5 observed games, fetch one additional page of clips using a stored pagination cursor. Cost: 1-2 API calls instead of 5+.

**Contact dedup** — if we already have contact points for a creator, skip panel/YouTube scraping on re-enrichment.

Key code: `app/creator_index/enrichment.py`

---

## Phase 6: Tag materialization

When a `creator_games_played` row is inserted or updated, a set of **SQLite triggers** automatically materializes the creator-game-tag relationship into `creator_account_game_tags`. This is a denormalized table that pre-joins:

```
creator_games_played.account_id  →  igdb_game_tags (via igdb_game_id)  →  creator_account_game_tags
```

One row in `creator_account_game_tags` means: "this creator has played a game carrying this tag." The triggers fire on:
- INSERT into `creator_games_played` — populate tags for the new game
- UPDATE on `creator_games_played` — remove old tags, add new tags
- DELETE from `creator_games_played` — clean up tags
- INSERT/DELETE on `igdb_game_tags` — propagate tag changes to all affected creators

This materialization exists so the ranking hot-path doesn't need to rebuild the `creator → game → tag` join on every page load.

Key code: `app/sql/schema.sql` (triggers), `app/matches/repository.py` reads from this table

---

## Phase 7: Steam tag enrichment

A separate background job enriches cached IGDB games with Steam data:

1. Find IGDB games with status `pending` in `steam_game_sync_state`
2. Search Steam store by game name
3. If match found: scrape raw Steam tags (user-defined genre tags)
4. Map raw Steam tags to IGDB keyword IDs via `steam_tag_to_igdb_keyword`
5. Insert mapped tags into `igdb_game_tags` (which triggers materialization into `creator_account_game_tags`)

This enriches the tag vocabulary beyond official IGDB metadata. For example, Steam users might tag a game "deckbuilder" or "roguelite" even if IGDB doesn't have those as keywords.

Key code: `app/steam_enrichment/service.py`, `app/steam_enrichment/tag_mapping.py`

---

## Phase 8: Match ranking

When a user visits `/games/{slug}/matches`, the ranking pipeline scores all creators against the customer's game definition:

### Tag counting

`MatchRepository.query_creator_tag_counts()` queries `creator_account_game_tags` to count how many distinct games each creator has played that carry each of the customer game's tags. The result is a per-creator tag profile: `{(tag_type, tag_id): distinct_game_count}`.

### Coverage scoring

`match_creator_tags_to_game()` in `matching.py` computes a coverage score:

1. Extract the customer game's tags (genres, themes, mechanics/keywords)
2. For each tag, compute `tag_evidence(distinct_games_count)` — a saturating curve:
   - 0 games → 0.0
   - 1 game → 0.93
   - 2 games → 0.967
   - 3+ games → 1.0
3. Weight by tag type: genres × 3, themes × 1, mechanics × 1
4. Coverage = weighted sum of evidence / total weight

The coverage score ranges from 0.0 to 1.0 and represents how well a creator's game library overlaps with the customer's game definition.

### Filtering and display

The ranking service applies user-selected filters:
- **Reach** — min/max follower count
- **Overlap** — min/max coverage score
- **Games played** — min/max relevant game count
- **Contact method** — email, Discord, Twitch, YouTube, X, Instagram, TikTok, Bluesky
- **Workflow status** — new, contacted, negotiating, key_sent, not_pursuing

Results are sorted by coverage score (descending), paginated at 20 per page and hydrated with full profile data (display name, avatar, reach, contact info, relevant games list).

Key code: `app/matches/service.py`, `app/matches/repository.py`, `app/creator_index/matching.py`

---

## Scheduled jobs

| Job | Interval | Entry point | Purpose |
|---|---|---|---|
| Customer game sweep | 10 min | `run_scheduled_creator_index_sync()` | Re-crawl all active games with rotating categories (max 3 per run) |
| Top categories | 30 min | `run_top_categories_crawl()` | Pre-populate from top 20 Twitch categories |
| Catalog discovery | 6 hours | `run_catalog_discovery()` | Pre-populate from internal game definitions (if configured) |
| On-demand | 5s after game save | `run_game_discovery()` | Immediate crawl for new/updated games |
| Steam tag backfill | 15 min | `run_steam_tag_backfill()` | Link IGDB games to Steam, extract tags (25 games per run) |

All discovery jobs share a semaphore (max 2 concurrent) to stay within Twitch's 800 req/min rate limit.

On startup, an immediate one-shot sync and Steam backfill run before the intervals begin.

Key code: `app/scheduler/setup.py`, `app/scheduler/jobs.py`

---

## Pre-population

Two background jobs populate the creator index independently of customer games:

**Top Twitch categories crawl** (every 30 minutes): fetches the top 20 most-watched Twitch categories and crawls their streams + clips. Genre-agnostic — catches whatever's popular. New customers benefit from creators already in the index.

**Catalog discovery** (every 6 hours, if configured): runs the full discovery pipeline against internal game definitions in a catalog directory, covering major genre spaces.

---

## Data model

### Tables written by discovery

| Table | Purpose | Writer |
|---|---|---|
| `source_accounts` | Platform identity (handle, display name, URL) | enrichment.py |
| `twitch_profiles_latest` | Current Twitch stats (followers, profile image) | enrichment.py |
| `content_samples_latest` | Recent clips/videos | enrichment.py |
| `contact_points` | Email, Discord, social links | enrichment.py |
| `creator_games_played` | Games observed from creator's content | enrichment.py |
| `twitch_categories` | Twitch category metadata and IGDB mapping | discovery.py |

### Tables written by enrichment pipelines

| Table | Purpose | Writer |
|---|---|---|
| `igdb_games` | Cached IGDB game metadata | IGDB sync + on-demand fetch |
| `igdb_game_tags` | IGDB game → genre/theme/mechanic tags | IGDB sync + Steam enrichment |
| `steam_game_sync_state` | Steam linking status per IGDB game | Steam enrichment |
| `steam_raw_tags` | Raw user-defined Steam tags | Steam enrichment |
| `steam_tag_to_igdb_keyword` | Mapping from Steam tags to IGDB keywords | Steam enrichment |

### Materialized tables (trigger-maintained)

| Table | Purpose | Populated by |
|---|---|---|
| `creator_account_game_tags` | Denormalized creator×game×tag for fast ranking queries | SQLite triggers on `creator_games_played` and `igdb_game_tags` |

### Tables used by ranking (read-only)

| Table | Read by |
|---|---|
| `creator_account_game_tags` | `MatchRepository.query_creator_tag_counts()` |
| `twitch_profiles_latest` | Profile hydration (reach, avatar) |
| `contact_points` | Contact info and filter matching |
| `creator_games_played` | Relevant games list |
| `match_statuses` | Workflow state (status, notes) |

---

## Key files

| File | Purpose |
|---|---|
| `app/creator_index/discovery.py` | Core pipeline: reference games, bridge, crawl |
| `app/creator_index/enrichment.py` | Twitch API enrichment (profiles, clips, contacts, panels) |
| `app/creator_index/service.py` | Orchestrator: sync games, persist results, rotate offset |
| `app/creator_index/matching.py` | Tag evidence curve and coverage scoring |
| `app/creator_index/cross_reference.py` | Two-hop expansion (SQL-only) |
| `app/creator_index/stream_discovery.py` | Twitch stream/clip fetching |
| `app/creator_index/repository.py` | Persistence: upsert accounts, profiles, contacts, games |
| `app/matches/service.py` | Ranking: score, filter, hydrate, paginate |
| `app/matches/repository.py` | Ranking queries against materialized tag table |
| `app/llm/game_suggestions.py` | Claude API call for anchor game generation |
| `app/steam_enrichment/service.py` | Steam tag backfill pipeline |
| `app/scheduler/jobs.py` | Background job entry points |
| `app/scheduler/setup.py` | Job scheduling configuration |
| `app/sql/schema.sql` | Table definitions, indexes, materialization triggers |

---

## Architecture notes

See `app/creator_index/DESIGN.md` for deeper architectural rationale including:
- Why platform data is stored per-account (no merged identities)
- The converged-after-enrichment pattern
- Why `twitch_categories` is a separate table
- Behavioral-evidence-first matching philosophy
- Catalog growth driven by observed creator activity
