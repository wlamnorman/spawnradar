# Scaling SpawnRadar to Two CPUs and Shared Cache

This note covers what happens if we scale the Fly app from `1 CPU / 1 worker`
to `2 CPU`, what can go wrong, what we need to change first, and where Fly's
Upstash Redis fits.

The short version:

- `2 CPU` by itself is low risk.
- `2 workers` is not low risk in the current architecture.
- Redis can help with shared `/matches` caching, but it does not solve the
  biggest multi-worker problem.

## Current State

Today the production app is configured roughly like this:

- `1` Fly machine
- `1 vCPU`
- `1 GB` RAM
- `WEB_CONCURRENCY=1`
- SQLite on a Fly volume
- APScheduler started inside the web app lifespan
- `/matches` ranked snapshots stored in process-local memory

Relevant code:

- web/process config: `fly.toml`, `Dockerfile`
- scheduler startup: `app/main.py`, `app/scheduler/setup.py`
- ranked snapshot cache: `app/matches/service.py`
- SQLite config: `app/database.py`

## What Two CPUs Actually Means

There are two different upgrades people often conflate:

### `2 CPU`, still `1 worker`

This means one machine with more compute available, but still only one web
process serving requests.

What it enables:

- more headroom for scheduler jobs and request handling to share the machine
- somewhat lower risk of the single worker being starved by background work

What it does **not** enable much:

- more web request concurrency
- shared cache improvements

Risk level: low

### `2 CPU` and `2 workers`

This means one machine with two CPU cores and two independent web worker
processes.

What it enables:

- real request concurrency
- one slow `/matches` request does not monopolize the entire app
- better resilience during a traffic spike

What it changes architecturally:

- app startup runs twice
- in-memory caches are duplicated per worker
- SQLite is now accessed by two independent worker processes under load

Risk level: medium to high **unless** we first separate scheduler duties.

## Main Risks of Going to Two Workers

### 1. Duplicate scheduler execution

This is the biggest risk.

The scheduler is started inside the app lifespan in `app/main.py`. With
`uvicorn --workers 2`, both workers run lifespan, which means both workers try
to start APScheduler and both workers schedule the same recurring background
jobs.

What that would cause:

- duplicated creator-index syncs
- duplicated top-category crawls
- duplicated Steam/tag backfills
- extra writes to SQLite
- extra API usage and scraping
- more load right when we are trying to improve concurrency

This is the primary reason we should **not** simply switch to `2 workers` today.

### 2. Per-worker `/matches` snapshot caches

The ranked `/matches` snapshots in `app/matches/service.py` are stored in
process memory.

With two workers:

- worker A has its own cache
- worker B has its own cache
- a snapshot built on worker A is invisible to worker B

What that means:

- duplicate ranking work across workers
- lower cache hit rate
- more memory use
- no correctness issue, but weaker performance than expected

This is annoying, but not a blocker on its own.

### 3. More SQLite contention

SQLite itself is configured reasonably for modest concurrency:

- WAL mode is enabled at initialization
- `busy_timeout` is set
- foreign keys are enabled

That said, two workers increase the chance of:

- reads and writes overlapping
- write lock waits
- background jobs contending with web traffic

This becomes much more noticeable if the scheduler is still running in every
worker.

### 4. Memory pressure

The app now uses `PRAGMA temp_store=MEMORY` for SQLite scratch work, and the
`/matches` snapshot cache also lives in process memory.

With two workers:

- every worker has its own cache
- every worker can build in-memory SQLite temp structures

This is usually fine at low traffic, but on a `1 GB` machine it is something we
would need to watch closely.

## What Redis Would Help With

Fly's Upstash Redis integration can be useful here, but only for one specific
problem: shared cache across workers.

Redis would help with:

- storing ranked `/matches` snapshots in one shared place
- allowing worker A to reuse a snapshot built by worker B
- reducing duplicate ranking work
- making cache behavior consistent across workers

Redis would **not** help with:

- duplicate scheduler startup
- duplicate background jobs
- SQLite write contention caused by duplicate schedulers
- RAM pressure from background scraping

So Redis is useful, but it is not the first architectural fix we need for
multi-worker web serving.

## Why Upstash Redis on Fly Is the Cheap Option

If we decide to introduce Redis, Fly's managed Upstash integration is the
lowest-friction way to do it.

Why it fits:

- no self-managed Redis VM
- straightforward `REDIS_URL` secret
- lives inside the Fly workflow
- cheap enough for our current stage

For our current `/matches` snapshot use case, command volume should stay low.
At current traffic, Redis would mainly be an architecture-enabler, not a
scaling necessity.

## Recommended Scaling Paths

### Option A: `2 CPU`, keep `1 worker`

This is the safest near-term upgrade.

Changes:

- bump Fly VM from `1 CPU` to `2 CPU`
- keep `WEB_CONCURRENCY=1`

Benefits:

- low operational risk
- more compute headroom
- background jobs less likely to starve the single web process

Limits:

- still only one request worker
- no shared-cache benefit
- request concurrency remains limited

Recommended if:

- we want cheap headroom before a marketing push
- we do not want to touch architecture yet

### Option B: `2 CPU`, `2 workers`, no Redis

This is **not recommended yet**.

It only becomes reasonable if we first separate the scheduler from the web
process.

Benefits after scheduler separation:

- better request concurrency
- simpler than adding Redis immediately

Downsides:

- duplicated in-memory caches
- more repeated ranking work
- somewhat worse cache efficiency

Recommended only if:

- scheduler has been moved out of the web workers
- we can tolerate per-worker cache duplication for a while

### Option C: `2 CPU`, `2 workers`, scheduler separated, shared Redis cache

This is the cleanest growth path if traffic meaningfully increases.

Benefits:

- concurrent web handling
- no duplicate scheduler jobs
- shared `/matches` snapshot cache
- more predictable cache hit behavior

Downsides:

- more moving parts
- extra integration complexity

Recommended if:

- `/matches` traffic becomes important
- we start seeing repeated ranking work across workers
- we need the app to stay responsive during marketing-driven usage spikes

## What We Need To Do Before Two Workers

### Required

1. Stop running the scheduler inside every web worker.

We need one of:

- a separate Fly process/machine for the scheduler
- or a deploy flag/env var so only the scheduler process starts APScheduler

Until this is done, `2 workers` is unsafe.

### Strongly recommended

2. Decide whether we are okay with per-worker snapshot caches.

If yes:

- ship `2 workers` first
- accept lower cache efficiency

If no:

- move snapshot caching into Redis

### Recommended for safety

3. Increase RAM if we move to `2 workers`.

`1 GB` might still work, but `2 workers` plus SQLite temp memory plus duplicate
in-process caches is the first place I would expect avoidable instability.

## What Two CPUs and Shared Cache Would Enable

If we do the full safer version:

- `2 CPU`
- `2 workers`
- one scheduler process
- Redis-backed snapshots

then we unlock:

- better handling of multiple simultaneous `/matches` sessions
- less chance that one heavy rank request freezes the site
- better cache reuse across workers
- better resilience while background discovery is running
- safer capacity for a marketing push

This is not "big scale", but it is a meaningful step up from a single-process
deployment.

## Recommended Order of Work

### Near term

1. If we want cheap headroom right away, move to `2 CPU` but keep `1 worker`.
2. Keep watching real traffic and `/matches` usage.

### Before multi-worker web serving

3. Split the scheduler out of the web process.
4. Decide whether snapshot sharing is worth Redis yet.

### When traffic justifies it

5. Move to `2 workers`.
6. Add Upstash Redis if duplicated per-worker snapshot caches become wasteful.

## Bottom Line

If we are preparing for more traffic soon:

- `2 CPU / 1 worker` is a safe upgrade now
- `2 CPU / 2 workers` is **not** safe until scheduler startup is separated
- Upstash Redis is a good future fit for shared `/matches` caching, but it is
  not the first thing we need to change

The scheduler architecture is the key constraint, not Redis pricing.
