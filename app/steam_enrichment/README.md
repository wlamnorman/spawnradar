# Steam Enrichment

This subsystem enriches cached local `igdb_games` with Steam-origin metadata
without pretending Steam and IGDB are the same taxonomy.

## Core Rules

- Store raw Steam facts separately from IGDB facts.
- Persist a Steam link only when the resolver accepts exactly one candidate.
- Never store guessed or probabilistic matches in the main link table.
- Keep mapped canonical tags separate from raw Steam tags.
- Use explicit decomposition rules for compound Steam tags when a combined
  canonical tag does not already exist in SpawnRadar's taxonomy.

## Data Flow

1. `IGDBSyncService` stores or refreshes a cached `igdb_game`.
2. The game is marked `pending` for Steam enrichment.
3. `SteamTagEnrichmentService` searches Steam by game name.
4. Candidate apps are fetched from the Steam store.
5. The resolver applies soft checks:
   - normalized/fuzzy title match
   - developer overlap
   - release-year sanity
   - local canonical tag overlap
6. If exactly one candidate passes the acceptance rules, the service stores:
   - a resolved Steam app link
   - raw Steam tags
   - mapped canonical tags
7. Otherwise it records a factual `no_match` or `error` status.

## Why There Is No Match Confidence Column

The resolver can use soft heuristics internally, but persisted data is binary:

- accepted link
- or no link

This keeps the database factual. The internal scoring only exists to decide
whether a link should be stored at all.

## Tables

- `steam_game_sync_state`
  Tracks whether a cached `igdb_game` is pending, linked, unmatched or errored.

- `steam_game_links`
  One accepted Steam app per local `igdb_id`.

- `steam_game_tags`
  Raw Steam tags as fetched from the store page.

- `steam_game_mapped_tags`
  Deterministic mappings from raw Steam tags into SpawnRadar's current setup
  taxonomy.

## Shared Mapping Behavior

This subsystem owns the shared Steam tag mapping rules. The setup import flow
reuses the same mapping layer so imported game setup and background enrichment
stay aligned.

Text-derived mappings are deliberately stricter than raw Steam tag mappings:

- only an explicit allowlist of stable phrases is considered
- a phrase must appear at least twice across the available Steam/IGDB text
  blobs before it is promoted into a canonical tag
