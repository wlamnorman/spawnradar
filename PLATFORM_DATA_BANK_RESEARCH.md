# Platform Data Bank Research

_Last updated: 2026-03-22_

## Purpose

This document captures the recommended direction for building a platform data
bank for SpawnRadar.

It is intentionally written for the current stage of the product:

- single-person SaaS
- validating market interest
- speed matters more than theoretical elegance
- low operational overhead matters
- we do not need audit-heavy or compliance-heavy infrastructure yet

The goal is not to build a warehouse or a moat-first dataset business.

The goal is to build a **small, reliable, compounding local source index** that:

- makes repeated discovery runs faster
- reduces dependence on live API calls
- improves reliability when APIs are slow or rate-limited
- gradually grows coverage over time
- stays simple enough for one person to maintain

This document is meant to be used later by other agents as a handoff.

## Executive Summary

The right short-term plan is a **DB-first, always-top-up** discovery model.

That means:

- serve as much as possible from a local database
- always reserve some budget for live fetches
- use every run to both serve the customer and feed the database

The data model should be:

- one shared orchestration table for discovered external accounts
- per-platform latest-state profile tables
- shared contact and content-sample tables
- crawl job and cursor tables

This is the right compromise:

- faster than live-only discovery
- less stale than DB-only discovery
- much smaller and simpler than a full warehouse
- much more useful than the current "discover from scratch every time" model

The key architectural rules are:

- latest-state upserts, not append-only warehousing
- per-platform tables where the fields genuinely differ
- no cross-platform identity graph in V1
- no broad enrichment crawler in V1
- no historical data infrastructure unless it creates direct product value

One important framing point:

- the dataset should be treated as an **operational asset**, not as the main
  moat by itself

## Product Fit

### What this helps with immediately

- faster repeat discovery runs
- fewer API calls per user action
- better reliability for demos and real users
- stronger compounding behavior over time
- ability to re-surface good accounts without rediscovering them from zero

### What this does not need to do yet

- build complete cross-platform creator identities
- archive historical snapshots forever
- support audit trails or replay
- crawl broad link graphs or creator websites at scale
- become a separate standalone data product

## Current Repo Gap

Today the app stores queue-facing prospect data in:

- `prospects` in `app/sql/schema.sql`
- one mutable `raw_data` blob per prospect
- one current row per `(platform, handle)`

That is good enough for the queue, but not enough for a reusable source index
because it does not separate:

- source crawling state
- latest reusable account/profile data
- contact extraction
- latest content samples
- cursor state and refresh scheduling
- queue-facing output rows

Future work should keep queue tables as queue/output tables and add a separate
`source_index` subsystem.

## Research Findings

### High-level conclusion

There is no single safe or optimal storage posture for every platform.

- **Twitch** is immediately useful for product value, but policy-sensitive.
- **Bluesky** is the cleanest fit for long-lived indexing.
- **YouTube** is highly valuable but the most restrictive for storage/derived
  data assumptions.
- **Reddit** is useful, but also contract-sensitive for commercial API use.

That means the durable thing we should build is:

- our own indexing machinery
- our own latest-state local DB
- our own queue and product logic

Not:

- a giant permanent archive of third-party platform data

### Platform summary

| Platform | Short-term product value | Data-bank fit | Recommendation |
| --- | --- | --- | --- |
| Twitch | High | Good as latest-state cache/index | Start here |
| Bluesky | Medium | Best true indexing fit | Second |
| YouTube | High | Use cautiously with strict refresh assumptions | Later |
| Reddit | Medium | Useful but less urgent | Later |

### Twitch findings

Twitch is currently one of the highest-value platforms for the product.

- The API docs indicate `Get Channel Followers` can return aggregate follower
  totals.
- Twitch API docs warn not to depend on response string formats or URLs.
- Twitch rate limits and marketing/commercial usage constraints still matter.

Practical conclusion:

- Twitch is a good first platform for the local index because it helps the
  product immediately.
- It should still be treated as a refreshable latest-state source, not a
  permanent archive.

### Bluesky findings

Bluesky is the cleanest architectural fit for a durable index.

- The federation model is designed for replication/indexing.
- Backfill + live firehose patterns are documented.
- Rate limits still exist, but the overall posture is much more index-friendly
  than YouTube or Twitch.

Practical conclusion:

- Bluesky should be the second platform in the source-index rollout.
- It is a good place to prove the module shape cleanly.

### YouTube findings

YouTube is very valuable, but the most restrictive source here.

- Policies require temporary storage / refresh behavior for non-authorized API
  data.
- Policies are restrictive around broad aggregation and derived metrics from
  API data.
- Search is expensive from a quota perspective.

Practical conclusion:

- Do not make YouTube the first source-index implementation.
- Add it later, conservatively, once the architecture is stable.

### Reddit findings

Reddit is useful but less central to the short-term value of the data bank.

- API limits and commercial use are controlled by Reddit.
- Derived/commercial use can require explicit approval.

Practical conclusion:

- Reddit should come after Twitch and Bluesky in the short-term plan.

## Recommended Architecture

### Core principle

Build a **latest-state source index** that is optimized for discovery quality
and speed, not for historical completeness.

Every stored row should answer one practical product question:

- what external account is this?
- what is the latest useful profile state?
- what are the latest content samples worth scoring?
- what is the best current contact route?
- when should we refresh this row?

### Serving model

The right serving model is:

1. query the local DB first
2. serve fresh useful results quickly
3. always do some live top-up work
4. feed the DB from every run

This is the compounding loop we want.

The system should avoid both extremes:

- **live-only**: too slow, too rate-limited, too wasteful
- **DB-only**: too stale, stops discovering new accounts

### Practical budget model

Future agents should think in terms of three budgets:

- `db_budget`
- `live_budget`
- `refresh_budget`

Example behavior:

- satisfy most of a run from the local DB if enough fresh matches exist
- always spend a smaller budget on live fetches
- use part of that live budget to refresh stale high-value rows

The exact split can evolve later, but the architecture should support it.

### What an "account" means

In this design, an account means a **platform-specific external entity**.

Examples:

- one Twitch channel
- one YouTube channel
- one Bluesky profile
- one subreddit

Do **not** assume that one creator will be merged into one universal identity
across platforms in V1.

That means:

- one row for their Twitch channel
- one row for their YouTube channel
- one row for their Bluesky profile

Cross-platform identity resolution is explicitly out of scope for the first
version.

### What we are not building yet

- no append-only warehouse
- no cross-platform identity graph
- no generalized linktree / media-kit / website crawler
- no full creator dossier system
- no broad enrichment engine that tries to map every creator across every
  platform

If later we add enrichment, it should be narrow:

- only from obvious links already exposed by the discovered profile
- only when it directly improves contactability or matching

## Recommended Data Model

### 1. `source_accounts`

One stable row per discovered external account.

Suggested fields:

- `account_id`
- `platform`
- `external_id`
- `handle_current`
- `display_name_current`
- `canonical_url`
- `account_type`
- `status`
- `first_seen_at`
- `last_seen_at`
- `created_at`
- `updated_at`

Constraints:

- unique `(platform, external_id)`
- do **not** key by handle alone

This table is the orchestration layer.

### 2. `twitch_profiles_latest`

Latest useful Twitch-specific profile state.

Suggested fields:

- `account_id`
- `broadcaster_id`
- `login`
- `display_name`
- `description`
- `followers_count`
- `viewer_count`
- `language`
- `avatar_url`
- `last_live_at`
- `fetched_at`
- `expires_at`
- `raw_payload_json`

Notes:

- keep follower totals and live viewer counts separate
- this table should reflect the latest known Twitch state only

### 3. `bluesky_profiles_latest`

Latest useful Bluesky-specific profile state.

Suggested fields:

- `account_id`
- `did`
- `handle`
- `display_name`
- `description`
- `followers_count`
- `posts_count`
- `language`
- `avatar_url`
- `last_post_at`
- `fetched_at`
- `expires_at`
- `raw_payload_json`

### 4. `youtube_channels_latest`

Latest useful YouTube-specific channel state.

Suggested fields:

- `account_id`
- `channel_id`
- `handle`
- `display_name`
- `description`
- `subscriber_count`
- `video_count`
- `avatar_url`
- `last_upload_at`
- `fetched_at`
- `expires_at`
- `raw_payload_json`

Notes:

- add only when the source-index architecture is already stable
- treat refresh behavior conservatively

### 5. `reddit_entities_latest`

Latest useful Reddit entity state.

This may later cover:

- subreddits
- posts
- authors

Suggested fields:

- `account_id`
- `entity_kind`
- `external_id`
- `name_or_handle`
- `title`
- `description`
- `subscriber_count`
- `engagement_count`
- `last_active_at`
- `fetched_at`
- `expires_at`
- `raw_payload_json`

### 6. `content_samples_latest`

Latest `N` content items used for scoring and UI.

Suggested fields:

- `sample_id`
- `account_id`
- `platform`
- `external_content_id`
- `content_type`
- `title_or_text`
- `url`
- `thumbnail_url`
- `published_at`
- `engagement_count`
- `language`
- `position_rank`
- `fetched_at`
- `expires_at`

Notes:

- keep only the latest useful samples
- replace/update rows on refresh
- no permanent historical archive

### 7. `contact_points`

Latest known contact routes.

Suggested fields:

- `contact_point_id`
- `account_id`
- `contact_type`
- `contact_value`
- `source_kind`
- `source_url`
- `confidence`
- `is_public`
- `first_seen_at`
- `last_seen_at`
- `updated_at`

Notes:

- upsert by `(account_id, contact_type, contact_value)`
- this table should only store practical contactability data

### 8. `crawl_jobs`

Append-only operational job history.

Suggested fields:

- `job_id`
- `platform`
- `job_type`
- `seed_key`
- `status`
- `attempt`
- `started_at`
- `finished_at`
- `error_message`
- `args_json`

This is one place where append-only history is worth it because it is useful
operationally and small.

### 9. `crawl_cursors`

Latest resumable cursor state.

Suggested fields:

- `cursor_id`
- `platform`
- `cursor_scope`
- `cursor_key`
- `cursor_value`
- `updated_at`

### 10. Optional: `account_metric_samples`

Only add this if it creates direct product value.

Examples:

- Twitch average viewers over time
- follower growth trend for a subset of high-value accounts

Suggested fields:

- `sample_id`
- `account_id`
- `metric_name`
- `metric_value`
- `observed_at`

Do not add this table until there is a concrete need.

## Format Recommendation

### Default storage stance

For the current stage:

- latest-state upserts
- small operational job log
- small optional metric samples only when justified

Do **not** build:

- a broad append-only raw observation table
- a generic data lake
- a historical replay system

### Operational store

Short-term recommendation:

- separate SQLite DB is acceptable if it speeds implementation

Longer-term recommendation:

- move the source index to Postgres once it is clearly valuable

Important:

- keep the source index logically separate from queue tables from day one
- do not block on Postgres before proving the product value

### Raw payload handling

Store only the **latest raw payload** per platform-specific latest-state row.

Recommended envelope:

```json
{
  "platform": "twitch",
  "external_id": "141981764",
  "adapter_version": "twitch/v1",
  "fetched_at": "2026-03-22T18:00:00Z",
  "expires_at": "2026-03-23T18:00:00Z",
  "raw": {}
}
```

This is enough flexibility for future parsing changes without committing to a
history-heavy system.

## Why This Is Good Enough

The robustness comes from structure, not from storing everything forever.

### 1. Stable external IDs

Use:

- Twitch `broadcaster_id`
- YouTube `channel_id`
- Bluesky `did`
- Reddit object IDs / fullnames

### 2. Per-platform latest tables

This avoids fake normalization where semantics differ.

Examples:

- Twitch live viewers are not YouTube subscribers
- Bluesky followers are not Reddit subreddit subscribers
- subreddit/community entities are not creator profiles

### 3. Per-platform adapters

Each adapter should own:

- fetching
- normalization
- TTL / refresh behavior
- cursor semantics

### 4. Latest raw payload retained

Keeping the latest raw payload gives enough room to:

- patch a parser
- inspect weird rows
- expose a new field later

without building a history system.

### 5. Hybrid serving loop

This is the most important product property.

We want:

- DB-first speed
- live-fetch freshness
- compounding data growth

That is more useful for the product than perfect historical fidelity.

## Do We Need Per-Platform Storage?

Yes.

Given the current product and team size, the best shape is:

- one shared orchestration table
- per-platform latest-state tables
- shared contact/content/job/cursor tables

This is better than one giant normalized profile table because it keeps the
data model honest.

It also makes new platforms easier to add later.

## Recommended Repo Layout

Future agents should isolate this work from queue code.

Suggested layout:

```text
app/source_index/
  __init__.py
  models.py
  repository.py
  service.py
  scheduler.py
  cursors.py
  adapters/
    __init__.py
    base.py
    twitch.py
    bluesky.py
    youtube.py
    reddit.py
```

Integration boundaries:

- `source_index` owns crawling and latest reusable source data
- `ingestion` consumes from `source_index`
- `queue` remains queue-focused
- metrics remain separate

## Suggested Platform Order

### First: Twitch

Reason:

- high short-term product value
- already useful in the app
- likely immediate payoff from caching/indexing repeated discovery

### Second: Bluesky

Reason:

- best architectural fit for a durable local index
- good place to refine the module cleanly after Twitch

### Third: YouTube

Reason:

- high value, but more restrictive and higher-risk to overbuild early

### Fourth: Reddit

Reason:

- useful, but less urgent than Twitch and Bluesky for the first version of the
  data bank

## Implementation Plan

### Phase 0: Lock Scope

Before writing schema, lock in these constraints:

- latest-state, not warehouse
- DB-first plus always-live-top-up
- no broad append-only observation storage
- no cross-platform identity graph in V1
- no general enrichment crawler in V1
- no time-series tables without explicit product need

Acceptance criteria:

- future agents can read this doc and understand the target system is small,
  fast and practical

### Phase 1: Core `source_index` Module

Deliverables:

- `app/source_index/`
- `models.py`
- `repository.py`
- `service.py`
- `scheduler.py`

Initial tables:

- `source_accounts`
- `twitch_profiles_latest`
- `bluesky_profiles_latest`
- `content_samples_latest`
- `contact_points`
- `crawl_jobs`
- `crawl_cursors`

Acceptance criteria:

- can upsert an account
- can upsert a Twitch row
- can upsert a Bluesky row
- can replace latest content samples
- can upsert contact points
- can store job history and cursors

### Phase 2: Adapter Framework

Deliverables:

- `adapters/base.py`
- adapters declare:
  - `fetch_seed(...)`
  - `fetch_profile(...)`
  - `fetch_content_samples(...)`
  - `extract_contact_points(...)`
  - `ttl(...)`

Acceptance criteria:

- platform-specific code is isolated
- queue code does not import platform adapters directly

### Phase 3: Scheduler and Warm-Cache Loop

Deliverables:

- seed jobs
- refresh jobs
- cursor persistence
- staleness refresh using `expires_at`

Acceptance criteria:

- jobs are resumable
- stale rows get refreshed
- failures are visible in `crawl_jobs`

### Phase 4: Twitch First

Deliverables:

- Twitch adapter
- Twitch latest profile upserts
- Twitch latest stream/content sample refresh
- Twitch contact point extraction

Acceptance criteria:

- repeated Twitch discovery runs can query local data first
- repeated Twitch runs do fewer Helix calls

### Phase 5: Bluesky Second

Deliverables:

- Bluesky adapter
- Bluesky latest profile upserts
- Bluesky latest post sample refresh

Acceptance criteria:

- repeated Bluesky discovery runs can query local data first
- live Bluesky calls are reduced on repeat runs

### Phase 6: Read Local Index First, Always Top Up Live

Deliverables:

- discovery pipeline consults `source_index` first
- live calls remain as bounded top-up and refresh work

Acceptance criteria:

- repeated discovery runs are faster
- discovery still keeps discovering some new accounts
- queue behavior remains stable or improves

### Phase 7: Add More Platforms Carefully

Possible additions:

- `youtube_channels_latest`
- `reddit_entities_latest`
- optional `account_metric_samples`

Acceptance criteria:

- each new platform is added because it clearly improves product value
- the system stays simple enough for one person to maintain

## Guidance for Future Agents

- Do not turn `prospects` into a warehouse.
- Do not build append-only raw observation storage by default.
- Do not key by handle alone.
- Do not merge multiple platforms into one creator identity in V1.
- Do not mix queue state and crawl state.
- Do not add a general enrichment crawler unless there is a direct product need.
- Keep the system tight, readable and easy to operate for a single-person
  SaaS.

## Open Questions

- separate SQLite first, or go straight to Postgres?
- should YouTube be in the first source-index rollout at all?
- is Twitch + Bluesky enough to prove the model before adding more?
- what DB/live split should we target for discovery runs?

## Recommended Next Step

If another agent picks this up later, the first concrete implementation step
should be:

1. create `app/source_index/`
2. add `source_accounts`, `twitch_profiles_latest`, `bluesky_profiles_latest`,
   `content_samples_latest`, `contact_points`, `crawl_jobs` and
   `crawl_cursors`
3. implement the adapter interface
4. build Twitch first
5. build Bluesky second
6. keep the current queue/prospect tables unchanged until the source index
   proves useful

## Sources

Official documentation reviewed for this research:

- YouTube Developer Policies:
  https://developers.google.com/youtube/terms/developer-policies
- YouTube quota costs:
  https://developers.google.com/youtube/v3/determine_quota_cost
- YouTube `channels.list`:
  https://developers.google.com/youtube/v3/docs/channels/list
- Twitch API Concepts:
  https://dev.twitch.tv/docs/api/guide
- Twitch API Reference:
  https://dev.twitch.tv/docs/api/reference
- Twitch Developer Agreement:
  https://www.twitch.tv/p/de-de/legal/developer-agreement/
- Reddit Data API Terms:
  https://redditinc.com/policies/data-api-terms
- Bluesky backfill:
  https://docs.bsky.app/docs/advanced-guides/backfill
- Bluesky federation architecture:
  https://docs.bsky.app/docs/advanced-guides/federation-architecture
- Bluesky rate limits:
  https://docs.bsky.app/docs/advanced-guides/rate-limits

## Notes

- This is an engineering research document, not legal advice.
- Platform terms and rate limits can change.
- Future agents should re-check official docs before implementing a new source
  or significantly scaling an existing one.
