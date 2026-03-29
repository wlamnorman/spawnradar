# Discovery Pipeline

How SpawnRadar finds content creators for a customer's game.

## Lifecycle

```
Game Created/Updated
    ↓
LLM generates tight + broad anchor games (one-time, ~$0.01)
    ↓
On-demand crawl fires immediately
    ↓
Every 10 minutes: scheduled re-crawl with rotating categories
```

### 1. Game definition saved

The customer provides genres, themes, keywords, and optionally up to 8 similar game names. On save, two things happen in the background:

**LLM anchor generation** — Claude produces two tiers of reference games:
- **Tight** (enough to reach 5 total with customer picks): same subgenre, same mechanics
- **Broad** (5-10): popular games with audience overlap, different subgenre

The LLM is told what the customer already picked and complements rather than duplicates. Results are stored on the game definition and cleared if the definition changes.

**On-demand discovery job** fires 5 seconds after save.

### 2. Building the reference game set

The pipeline builds a priority-ordered list of IGDB games to crawl:

| Priority | Source | Crawl behavior |
|---|---|---|
| 0 | Customer similar games + LLM tight anchors | **Always crawled** every run |
| 1 | IGDB keyword queries (progressive: genre+keyword, genre+theme, keyword-only) | **Rotated** across runs |
| 2 | LLM broad anchors | **Rotated** after keywords |
| 3 | Two-hop expansion (games shared by top creators) | **Rotated** last |

Priority 0 games are the core — they drive initial results within seconds. The other tiers explore progressively wider, mixed in over time via rotation.

### 3. IGDB keyword queries

Three progressive queries, each fires only if the previous returned fewer than 30 games:

1. Core genres AND keyword IDs (tightest)
2. Core genres AND themes (broader)
3. Keyword IDs only (broadest)

Canonical keywords (e.g., "deckbuilder") are expanded to all IGDB aliases ("deck building", "deck-building", "deckbuilder") before querying. The Indie genre (ID 32) is excluded to avoid overly broad results.

### 4. Two-hop expansion

After the first run populates `creator_games_played`, a SQL query (zero API calls) finds games that 3+ top creators share but aren't in the reference set. These get added as priority 3 and crawled on subsequent runs.

Example: if top Strife of Stars creators all play "Cobalt Core" but it wasn't in the reference set, it gets discovered and added automatically.

### 5. Twitch bridge and category rotation

All reference games are batch-resolved to Twitch categories via the IGDB→Twitch bridge (exact match, no fuzzy search).

Each run crawls up to 20 categories. Priority 0 games always fill their slots first. The remaining budget is filled from a rotating window of priority 1-3 games:

```
Run 1 (offset=0):   tight(4) + keyword[0:16]
Run 2 (offset=20):  tight(4) + keyword[16:32] + broad[0:4]
Run 3 (offset=40):  tight(4) + broad[4:10] + expansion[0:6]
Run 4 (offset=60):  tight(4) + keyword[0:16] (wraps around)
```

The offset increments by 20 after each game sync.

### 6. Per-category crawl

For each Twitch category:
- **Live streams**: 1 page (up to 100 broadcasters)
- **Clips**: 20 clips per category

Tight anchor categories (priority 0) get **time-shifted clips**: each run fetches a different 30-day window (last 30 days, then 30-60 days ago, then 60-90 days ago, cycling through 12 windows over ~1 year). Other categories get all-time popular clips.

### 7. Per-creator enrichment

Each new broadcaster discovered gets full enrichment:
- Profile (user info, channel info, follower count)
- Clips (per-broadcaster, 2 pages, 730-day lookback)
- Contact info (Twitch panels, social links, YouTube email fallback)
- Games played (extracted from clip game IDs)

Results are persisted immediately and the creator is yielded to the UI.

### 8. Repeat-run optimizations

On subsequent runs, creators already in the DB are handled efficiently:

**Skip recently enriched** — if a creator's profile was fetched within 7 days, skip full enrichment entirely. This saves 4-5 API calls per known creator.

**Clip deepening** — for skipped creators whose clips are NOT exhausted and who have fewer than 5 observed games, fetch one additional page of clips using a stored pagination cursor. This incrementally builds richer game-played profiles without re-enriching from scratch. Cost: 1-2 API calls instead of 5+.

**Contact dedup** — if we already have contact points for a creator, skip panel/YouTube scraping on re-enrichment.

### 9. Pre-population

Two background jobs populate the creator DB independently of customer games:

**Top Twitch categories crawl** (every 30 minutes): fetches the top 20 most-watched Twitch categories and crawls their streams + clips. Genre-agnostic — catches whatever's popular. New customers benefit from creators already in the DB.

**Catalog discovery** (daily, if configured): runs the full discovery pipeline against internal game definitions covering major genre spaces.

## Scheduling

| Job | Interval | Purpose |
|---|---|---|
| Customer game sweep | 10 min | Re-crawl all active games with rotating categories |
| Top categories | 30 min | Pre-populate from popular Twitch games |
| Catalog discovery | 24 hours | Pre-populate from internal game definitions |
| On-demand | 5s after game save | Immediate crawl for new/updated games |

## Key files

| File | Purpose |
|---|---|
| `app/creator_index/discovery.py` | Core pipeline: reference games, bridge, crawl, enrich, expand |
| `app/creator_index/enrichment.py` | Twitch API enrichment (profiles, clips, contacts, panels) |
| `app/creator_index/service.py` | Orchestrator: sync games, persist results, rotate offset |
| `app/llm/game_suggestions.py` | Claude API call for anchor game generation |
| `app/scheduler/jobs.py` | Background job entry points |
| `app/scheduler/setup.py` | Job scheduling configuration |
