# Prospects Performance Plan

## Purpose

This document describes the current `/prospects` performance problem, the
likely causes in the current implementation, and a staged plan for fixing it.

This is a planning document only. It does not prescribe a single exact query
rewrite up front; instead it defines the problem boundaries, design goals, and
the sequence in which the optimizations should be made and verified.

## Problem Summary

The `/games/{slug}/prospects` page appears slow not because the browser is
rendering every matched creator at once, but because the server does too much
work to render one page of 50 rows.

The current implementation:

- overfetches a large candidate set before pagination
- hydrates display data for many more creators than are shown
- recomputes filter maxima on every page load
- reruns the ranking pipeline after workflow updates just to refresh counts
- fetches more relevant-game rows than the template actually renders

This leads to unnecessary SQL work, unnecessary Python work, and slower UI
interactions even when the page only shows a small visible slice.

## Where The Waste Happens

The main hotspots in the current implementation are:

- `app/prospects/service.py`
  - `rank_prospects()`
  - fixed `fetch_limit = max((offset + limit) * 4, 5000)`
  - profile hydration before the final page slice is known
- `app/prospects/router.py`
  - `game_prospects_page()`
  - `update_prospect_workflow()`
  - both endpoints recompute more than they need
- `app/prospects/repository.py`
  - `max_reach_with_overlap()`
  - `max_relevant_games_with_overlap()`
  - `get_relevant_games()`
- `app/frontend/templates/games/prospects.html`
  - the page renders only a limited number of assets per row, but the backend
    often fetches more data than the template can display

The biggest performance mismatch is that lightweight interactions are routed
through a heavy general-purpose ranking pipeline.

## Current Issues

### 1. Rank pipeline overfetches aggressively

Current behavior in `app/prospects/service.py`:

- `rank_prospects()` computes `fetch_limit = max((offset + limit) * 4, 5000)`
- page 1 therefore considers up to 5,000 creators before slicing to 50
- the service scores all returned creators in Python before pagination

Implication:

- page 1 does substantially more work than needed
- workflow POSTs that call `rank_prospects(limit=1)` still hit the same 5,000
  minimum

### 2. Profile hydration happens before pagination

Current behavior:

- after scoring, the service fetches profile data for all scored creators
- sorting and filtering depend on those hydrated profiles
- pagination happens only later

Implication:

- even if the user only needs 50 rows, the service may hydrate thousands of
  profiles to decide what those 50 rows are

### 3. Workflow updates rerun a heavy ranking path

Current behavior in `app/prospects/router.py`:

- the workflow update endpoint persists a sparse state change
- then it recomputes reach max, relevant-game max, and calls
  `rank_prospects(... limit=1, offset=0 ...)`
- the only purpose is to update counts / row visibility / tab counts

Implication:

- a single status click can trigger almost the same expensive ranking flow as a
  full page render

### 4. Relevant games are over-fetched

Current behavior in `app/prospects/repository.py` and the template:

- `get_relevant_games()` returns all relevant games for each visible creator
- the template only renders the first 10 covers

Implication:

- query results and Python objects are larger than necessary

### 5. Filter maxima are recomputed on each GET

Current behavior:

- the route computes `max_reach()` and `max_relevant_games()` separately before
  calling `rank_prospects()`

Implication:

- every page load does multiple overlap scans before the main ranking pass

### 6. Interaction model favors full recomputation

Current behavior:

- filter form submits via normal GET
- status tabs are normal links
- only workflow updates are AJAX, but they still trigger heavy server
  recomputation

Implication:

- the route shape is simple, but expensive

## Design Goals

The revised implementation should aim for:

1. Compute only what is needed for the current visible page.
2. Avoid hydrating full profile / relevant-game payloads before the final page
   slice is known.
3. Make workflow updates cheap and local.
4. Separate ranking, counts, and display hydration into clearer query/service
   layers.
5. Preserve stable pagination and current ranking semantics unless we
   deliberately change them.
6. Be safe to roll out incrementally with measurable before/after latency
   improvements.

## Non-Goals

This work should not attempt to:

- redesign the prospect scoring model from scratch
- change business rules around trial gating or workflow states
- move the whole page to client-side rendering
- prematurely add caching without first simplifying the hot-path work

## Root Cause Assessment

The largest single problem is not "lack of lazy loading" in the frontend.
The dominant issue is query shape and service orchestration:

- the ranking service does broad candidate expansion before it knows which rows
  will actually be shown
- the same ranking function is reused for both page rendering and lightweight
  workflow updates, even though those operations have very different needs
- the service boundary is not cleanly split between:
  - candidate selection
  - counts / filter maxima
  - page hydration

The implementation works functionally, but the shape is not efficient.

## Target Architecture

The implementation should move toward four separate concerns:

1. candidate selection
   - find the candidate account ids that could plausibly appear on the current
     page
2. ranking and filter application
   - score candidates and apply user-visible filters without hydrating
     presentation payloads too early
3. page hydration
   - fetch profile and relevant-game data only for the final page ids
4. workflow/count updates
   - handle status changes and tab counts through a dedicated cheap path rather
     than reusing full page ranking

This keeps page rendering and workflow updates from sharing a single overly
broad method.

## Fix Plan

### Phase 1: Measure and make the waste explicit

Add operational visibility before changing behavior.

Tasks:

- Add request timing logs around `/prospects` GET and workflow POST handlers.
- Add timing logs around:
  - candidate count query
  - profile hydration
  - relevant-game count query
  - relevant-game hydration
- Log the effective `fetch_limit`, number of scored creators, number of
  filtered creators, and final page size.

Success criteria:

- We can identify which stage dominates latency on real production traffic.
- We can compare before/after optimizations with real numbers instead of
  intuition.

### Phase 2: Stop using full ranking for workflow updates

Make the workflow update path cheap first.

Tasks:

- Add a dedicated service/repository path for workflow-tab counts and row
  visibility.
- Do not call the full `rank_prospects()` flow from the workflow update
  endpoint.
- Return only:
  - updated row workflow state
  - visible / hidden decision under the current status filter
  - refreshed status counts if needed, via a specialized count query
- Ensure the workflow update path does not hydrate prospect profiles or
  relevant games unless the UI actually needs them.

Expected gain:

- status/note clicks become much cheaper immediately
- removes the worst "small click, huge rerank" mismatch

### Phase 3: Limit page rendering to a smaller candidate window

Replace the hard minimum `fetch_limit >= 5000` approach.

Tasks:

- Introduce an adaptive candidate window instead of a fixed minimum of 5,000.
- Start with something smaller and grow only if the filtered result set is too
  small for the requested page.
- Keep pagination stable, but do not hydrate thousands of creators by default.

Possible strategy:

- attempt with `candidate_limit = max((offset + limit) * 2, 250)`
- if filters leave too few rows to fill the page, retry with a larger window
- cap retries to a small number of expansions

Expected gain:

- page 1 stops paying an unconditional 5,000-candidate tax

### Phase 4: Split ranking from hydration

The service should operate in two layers:

1. candidate ranking metadata
2. display hydration for the final page rows

Tasks:

- Keep candidate scoring payload small:
  - account id
  - score
  - overlap tags
  - reach if needed for sorting
- Hydrate profiles only after the final page slice is determined, or move the
  required sort fields into the ranking query/result so full profile hydration
  is unnecessary before pagination.

Expected gain:

- fewer profile rows loaded
- simpler mental model for the pipeline
- easier unit testing because scoring and hydration stop depending on each
  other implicitly

### Phase 5: Fetch only the relevant games that are rendered

Change relevant-game hydration to match the UI contract.

Tasks:

- Limit relevant games per account in SQL to the top 10 by overlap / name
- return a separate total count if needed for the `+N more` badge

Expected gain:

- smaller result sets
- less Python object churn
- no wasted game cover lookups

### Phase 6: Reconsider filter maxima strategy

The current route computes maxima on every GET. This should be reviewed.

Options:

- compute maxima from the same candidate window used for ranking
- cache maxima per customer game for a short TTL
- defer maxima until the filter menu is opened
- accept slightly approximate maxima rather than exact global maxima on every
  request

Recommendation:

- start with simplification, not caching
- if the exact maxima are not critical to correctness, prefer "good enough and
  fast" over "globally exact and expensive"

### Phase 7: Clean up the service boundary

Once the hot path is cheaper, improve the internal structure so it stays
maintainable.

Tasks:

- reduce the responsibility of `rank_prospects()`
- move candidate-window policy into a named helper or policy object
- make repository methods reflect the UI contract explicitly
- remove any remaining hidden coupling between workflow counts, ranking, and
  hydration

Expected gain:

- lower risk of performance regressions
- clearer reasoning about which code path is expensive and why

### Phase 8: Improve frontend interaction model only after backend fixes

Once the backend work is cheaper, evaluate whether the frontend should also
move to partial updates.

Potential improvements:

- HTMX or fetch-based partial table refreshes for filter/status changes
- lazy page loading / infinite scroll only if the backend shape is already
  efficient

Important:

- frontend partial rendering should not be used to hide an inefficient backend

## Code Quality Improvements Needed

The current implementation would benefit from cleaner separation of
responsibilities.

### A. Split the prospect query pipeline into clearer steps

Current `rank_prospects()` is doing too much in one method:

- candidate retrieval
- scoring
- filtering
- workflow-state aggregation
- pagination
- page-row hydration

Refactor direction:

- `rank_candidate_accounts(...)`
- `count_statuses_for_candidates(...)`
- `hydrate_ranked_page(...)`
- optionally a separate `candidate_window_policy(...)`

This will make it easier to optimize one step without destabilizing the others.

### B. Avoid "magic" hard limits without escalation logic

The current `5000` minimum is a blunt instrument.

Refactor direction:

- move candidate-window logic into a named policy/helper
- document why the starting window is what it is
- make expansion explicit and measurable

### C. Keep lightweight endpoints lightweight

The workflow update endpoint should not depend on the full page-ranking path.

Refactor direction:

- separate read models for:
  - page render
  - counts only
  - row-local workflow update

### D. Make the UI contract explicit in repository methods

`get_relevant_games()` should reflect that the page renders at most 10 covers.

Refactor direction:

- repository methods should encode their intended UI usage in their arguments
  or naming, e.g. `get_top_relevant_games(..., per_account_limit=10)`

## Rollout Plan

1. Add instrumentation and collect baseline timings.
2. Ship the workflow-update fix first.
3. Replace the 5,000 minimum candidate window with adaptive expansion.
4. Limit relevant-game hydration to the rendered count.
5. Split ranking from hydration if phases 2-4 have not already forced that
   separation naturally.
6. Reassess whether filter maxima still need separate exact queries.
7. Only then consider frontend partial updates.

## Validation Plan

For each phase, verify:

- P50 / P95 latency for `/prospects` GET
- P50 / P95 latency for workflow POST
- number of candidate creators processed per request
- number of profile rows hydrated per request
- number of relevant-game rows hydrated per request
- correctness:
  - stable ordering
  - same visible creators for the same inputs
  - same status counts (unless intentionally redefined)

## Recommendation

Do not start with frontend lazy-loading work.

The highest-value next changes are:

1. remove the heavy rerank from workflow POSTs
2. replace the fixed 5,000-candidate overfetch with adaptive expansion
3. limit relevant-game hydration to what the template actually renders

Those three changes should remove most of the obvious waste while also making
the codebase cleaner rather than more complex.
