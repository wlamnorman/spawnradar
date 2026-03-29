# Creator Index Design

`app/creator_index/` builds SpawnRadar's reusable bank of platform-specific creator data.
It is intentionally separate from the customer-facing review queue. The durable primitive
here is a platform account in `source_accounts`, not a merged cross-platform identity.

This document describes the intended data flow for discovery and enrichment, with emphasis
on the Twitch path because that is the active product path right now and it has an explicit
category-resolution step. The YouTube code is currently parked rather than part of the
default crawl flow.

## Discovery overview

There are two broad discovery modes:

1. Customer-game discovery
   The service takes a `CustomerGame`, derives a small genre/theme subset, prefers
   locally observed `IGDBGame`s in that region, falls back to global IGDB expansion only
   when needed, and runs the Twitch category-discovery pipeline for several seed
   `igdb_game_id`s.

2. Bootstrap discovery
   The service runs stored `crawl_seeds` that are not tied to any one customer game so the
   bank can grow even when there are few or no active customer games. In the current
   Twitch-first shape, the default bootstrap seed is global live Twitch sampling.

In the current product shape, both of these active modes are Twitch-first. YouTube remains
implementable, but it is intentionally not wired into the default scheduler or default
creator-index service flow right now.

Both modes converge on the same persistence model:

- `source_accounts`
- platform latest tables such as `twitch_profiles_latest`
- `content_samples_latest`
- `contact_points`
- `creator_games_played`
- `creator_profile_facets_latest`

The important architectural point is that they do **not** converge at "choose an
IGDB game." They converge later, when both entrypoints have been resolved into
discovered creator account bundles that can go through the same ingestion path.

## Discovery entrypoints and convergence

The creator index currently has two main discovery entrypoints:

1. `IGDBGame`-backed entrypoints
   These start from one or more `igdb_game_id`s chosen from observed creator activity in
   a customer game's tag region, with global IGDB expansion as fallback.

2. bootstrap entrypoints
   These start from a stored generic seed in `crawl_seeds`. Today the active default
   bootstrap is global live Twitch, not text search.

These two paths stay separate until they both yield discovered account bundles.
Only after that point do they share the same downstream ingestion flow.

In code, that boundary now looks like:

- `account_discovery.py`
  Explicit entrypoint and pre-ingestion discovery result types.
- `CreatorIndexService.discover_account_bundles(...)`
  Resolves one entrypoint into discovered account bundles.
- `CreatorIndexService._ingest_discovered_account_batch(...)`
  Shared downstream ingestion once both paths have converged.

## Twitch IGDB-driven discovery

The Twitch live-directory path is slightly different because Twitch stream discovery is
keyed by a Twitch category ID, while our scheduling logic is keyed by IGDB games.

The steps are:

1. Start from an `IGDBGame`.
   In the scheduled customer-game path, this usually comes from observed creator activity
   in the same tag region, with global IGDB expansion as fallback. Developer tools can
   also request a one-off inspection directly. If the local `IGDBGame` row is missing,
   the service first fetches it on demand before continuing.

2. Resolve the `IGDBGame` to a Twitch category.
   We call `GET /helix/games?igdb_id=...` and persist the returned Twitch category
   metadata for later UI use and debugging.

3. Discover live streams for that Twitch category.
   We call `GET /helix/streams` with the resolved `twitch_category_id`, optionally with
   language filters such as `en`.

4. Enrich the discovered broadcasters.
   The Twitch adapter fetches structured Twitch data for each discovered broadcaster:
   search-channel results, user records, channel-information records, live stream records,
   recent videos, and follower totals. This gives us structured identity, language, live
   audience, recent content, current/last played games, and lightweight historical evidence.

5. Fetch full account bundles for the discovered broadcasters.
   The Twitch adapter fetches complete account/profile bundles for the discovered broadcasters.

6. Shared ingestion persists the discovered account bundles.
   Once bundles exist, the creator index uses the same downstream ingestion flow it uses
   for any other discovered bundles: source accounts, latest tables, content samples,
   contact points, creator games played, and derived creator-profile facets.

7. Link observed game play back to IGDB.
   Observed games are accumulated from distinct Twitch evidence sources:
   current live stream, channel information, and recent videos. Those observations are
   deduplicated by game within a sync, then the resulting `creator_games_played` rows are
   linked to IGDB when Twitch exposes a resolvable `game_id`.

8. Opportunistically grow the local IGDB catalog from observed creator activity.
   When a Twitch account bundle includes `ObservedGameSeed` rows with Twitch
   game/category IDs, we resolve those IDs through `GET /helix/games`, read the returned
   `igdb_id`, and fetch any missing `IGDBGame` rows on demand. This means the local
   `igdb_games` table grows primarily from games that creators actually play, rather than
   from broad catalog syncs.

The important design point is that `igdb_game_id` and `twitch_category_id` are different
identifier namespaces. The mapping between them must be explicit and persisted, but it
should be resolved through Twitch's direct IGDB-aware endpoint rather than fuzzy name
matching whenever possible.

## Why `twitch_categories` exists

We keep Twitch categories in their own table instead of burying Twitch fields inside
`igdb_games` because they are Twitch-specific UI and discovery artifacts. At this stage
the table is metadata persistence, not a cache that discovery reads from.

Today we store:

- `twitch_category_id`
- `name`
- `box_art_url`
- optional `igdb_game_id` link
- `last_synced_at`

This gives us:

- persisted Twitch category metadata for the UI
- Twitch box art for category cards later
- traceability for how a category was resolved

## Matching implications

The creator index should prefer behavioral evidence over self-description. That means
`creator_games_played` is the durable bridge from a creator to games and tags:

- creators are observed playing games
- those played games are linked to IGDB when possible
- customer games and IGDB games share a unified genre/theme/mechanic vocabulary
  built from official IGDB genres/themes plus curated keyword-derived concepts
- matching works in tag space using played games, not just profile text

The ingestion surface intentionally avoids storing raw platform payload blobs. The preferred
pattern is:

- parse platform responses into typed structs
- persist the structured fields we actually need
- keep the available platform fields visible in code, even when some are not yet used

## Current limits

- A `CreatorGamePlayed` row may begin life as unresolved text before later IGDB linking.
- Twitch live-directory discovery only sees creators who are live now in a category.
- Richer historical evidence from creator profile pages, such as recently streamed
  categories beyond what Helix exposes through recent videos and channel information,
  still needs a dedicated profile-expansion step.

## Catalog growth principle

The preferred source of truth for local IGDB coverage is observed creator activity:

- if creators are observed playing a game and Twitch can resolve it to an `igdb_id`,
  we should hydrate that `IGDBGame`
- if no creator activity and no active customer need points at a game, we usually do not
  need it locally yet

Bulk IGDB sync remains possible, but it is no longer the preferred driver of catalog growth.

## Crawl selection

The active scheduled runtime is intentionally simple:

- iterate active customer games
- derive a small tag subset from each game
- prefer observed local IGDB games in that tag region
- fall back to global IGDB tag expansion when the observed pool is empty
- run the Twitch category-discovery pipeline for the selected seed games
- separately run bootstrap discovery through the global-live Twitch seed

That logic currently lives in `CreatorIndexService`, not in a separate crawl-policy
framework. This keeps the active Twitch-first product path easier to reason about.

## Storage note (might be out of date now)

Current local SQLite footprint is small enough that retention is not an immediate concern.
A representative local snapshot was about 1.4 MB total, with the largest tables being:

- `content_samples_latest`: about 578 KB
- `twitch_profiles_latest`: about 242 KB
- `source_accounts`: about 37 KB
- `creator_games_played`: about 25 KB

Rough table-only row costs in that snapshot were:

- `twitch_profiles_latest`: about 2.2 KB per row
- `content_samples_latest`: about 1.3 KB per row
- `creator_games_played`: about 228 B per row

Practical implication:

- around 1,000 creators should still be on the order of tens of MB
- around 10,000 creators is likely still in the low hundreds of MB
- retention and TTL policies matter later, but are not the current bottleneck

The main storage drivers are content samples and metric/history tables, not the core account rows.
