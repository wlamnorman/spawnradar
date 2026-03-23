# Discovery And Scoring Overview

This note is the high-level map of how SpawnRadar discovery works today.

It is intentionally close to the code and intentionally light on constants. It
should explain the shape of the system without needing updates every time a
threshold or limit changes.

## Main entry points

- `app/games/router.py`
  - `run_ingestion_api()` validates the game, checks billing/readiness, creates
    a discovery run record and starts the discovery service in the background.
- `app/ingestion/service.py`
  - `DiscoveryRunService` is the canonical discovery-run implementation.
- `app/ingestion/pipeline.py`
  - `run_ingestion()` is the stable compatibility facade.
- `app/prospects/router.py`
  - `queue_api()` returns the current queue and, when requested, the status of a
    specific discovery run for live polling in the UI.

## Core data shapes

The run moves through a small set of normalized objects:

- `Game`
  - the developer's structured game definition: summary, platform tags and tag
    profiles
- `TaggedQuery`
  - one search query plus the tag provenance that produced it
- `CandidateRecord`
  - one source-level discovery result in normalized form
- `Prospect`
  - the persisted version of a candidate, deduped by platform + handle
- `DraftItem`
  - one queued outreach opportunity for a specific game + prospect pair

In shorthand:

```text
Game -> TaggedQuery -> CandidateRecord -> Prospect -> DraftItem
```

## What a discovery run does

At a high level, one run does six things:

1. Choose sources
   - The game's configured discovery sources are resolved into concrete source
     implementations.
   - YouTube can resolve to the API-backed source or the scraper fallback.

2. Build and execute queries
   - Each source builds tagged queries from the game's structured tags.
   - Sources discover in batches through `discover_batches()`, not as one giant
     list.
   - Sources run in parallel at the top level.

3. Normalize and persist candidates
   - Each discovered result is converted into a `CandidateRecord`.
   - Candidates are upserted into `prospects` so the system has a stable,
     deduped prospect record.

4. Prefilter obvious bad fits
   - Before LLM work, the pipeline drops results that are clearly poor
     opportunities, for example:
     - official / owned accounts
     - stale and very small prospects
     - source-specific low-value accounts such as tiny Bluesky creators
     - results with no core genre, vibe or platform signal

5. Score surviving prospects
   - A heuristic score is always computed locally from the game's tags and the
     prospect's normalized data.
   - If LLM scoring is enabled, promising shortlisted prospects are also sent to
     the LLM for semantic fit overrides.
   - The final score is the heuristic score with any available LLM overrides
     applied.

6. Queue outreach opportunities
   - Strong enough prospects are upserted into `draft_items`.
   - Existing queue items are refreshed in place instead of duplicated.
   - New queue items stream into the UI while the run is still in progress.

## How sources fit into the pipeline

Sources live in `app/ingestion/sources/`.

Each source is responsible for:

- building source-specific queries
- fetching raw results from its platform
- normalizing them into `CandidateRecord`
- filling the common fields the rest of the system depends on

The important normalized fields are:

- `last_active_days`
- `text_signals`
- `prospect_type`

Those fields are what make the scoring layer mostly source-agnostic.

## Where the implementation lives

The public import surface is still `app/ingestion/pipeline.py`.

- `app/ingestion/service.py`
  - canonical discovery-run service: source fan-out, batch consumption,
    scoring flow and queue insertion
- `app/ingestion/runs/`
  - lower-level helpers used by the service:
- `budget.py`
  - per-run queue budget and stop conditions
- `filters.py`
  - cheap pre-LLM candidate filtering
- `persistence.py`
  - prospect upserts, LLM reuse, search cursors and other stored run state

## How scoring works

The scoring system is split into two layers:

### 1. Heuristic scoring

Implemented in `app/scoring/engine.py`.

This computes a structured score from:

- genre fit
- vibe fit
- format fit
- activity
- contactability
- audience size
- platform fit

The weight table varies by `prospect_type`, so creators, communities and
developers are not judged exactly the same way.

### 2. LLM scoring

Implemented in `app/scoring/llm_engine.py`.

The LLM does not replace the whole score. It overrides the fit dimensions that
benefit from semantic judgment, especially:

- genre fit
- vibe fit
- format fit
- platform fit
- fit summary / why selected text

The final queue decision still happens in the discovery service.

## What persists between runs

The system keeps a small amount of memory between runs:

- previously queued handles are excluded from future discovery for the same game
- per-source search cursors are stored so later runs can continue exploring
  instead of always starting from the same first page
- existing queue items can be refreshed in place
- queued items with prior LLM results can reuse those scores on later runs

This means a new run is not a full reset. It is more like continuing the search
for the same game definition.

## What the queue represents

The queue is not just "everything discovered."

It is the subset of discovered prospects that:

- survived prefiltering
- scored well enough to be worth review
- fit within the current run's queue budget

Old queue items remain unless the user acts on them. A new discovery run adds to
that review queue; it does not wipe it.

## Where to look when changing behavior

- Source contract and normalized candidate shape:
  - `app/ingestion/base.py`
  - `app/ingestion/sources/SOURCES.md`
- Query generation:
  - `app/ingestion/query_builder.py`
- Run orchestration:
  - `app/ingestion/service.py`
  - `app/ingestion/pipeline.py`
- Heuristic scoring:
  - `app/scoring/engine.py`
- LLM scoring:
  - `app/scoring/llm_engine.py`
- Queue presentation and polling:
  - `app/prospects/router.py`
  - `app/frontend/static/queue.js`

## Maintenance rule

If the meaning of a discovery run changes, update this file together with the
pipeline code. This document is meant to stay near the implementation and act as
the first orientation point for future work.
