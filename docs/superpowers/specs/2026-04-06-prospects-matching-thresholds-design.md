# Prospects Matching Thresholds

## Problem

Loading `/prospects` for any game is too slow because the system considers too
many irrelevant creators as candidates. The current pipeline fetches up to 5,000
creators who share *any single tag* with the customer game, then scores, filters,
and hydrates profiles for all of them before showing 20 rows.

The root cause is not the fetch limit number itself — it's that the definition of
"candidate" is too loose. A creator who played one RPG once is treated the same
as a creator who covers the exact genre/theme combination of the customer game.

## Design

### Matching threshold: 50% coverage floor

A creator is only a prospect candidate if their coverage score is at least 50%.

Coverage score is the existing weighted metric:

```
coverage = sum(tag_weight * tag_evidence(games_count)) / sum(all_tag_weights)
```

Where genre tags weigh 3x and theme/mechanic tags weigh 1x, and `tag_evidence`
is a saturating curve (0.93 for 1 game, 0.967 for 2, 1.0 for 3+).

The 50% floor is a strict cutoff (`coverage_score > 0.5`). Creators at or below
it do not appear in the prospects list, are not counted in status tabs, and are
not included in filter computations.

### Why a single threshold suffices

With genre weights at 3x, the CustomerGame validation below (minimum 2 genre
tags), and the strict `> 0.5` threshold, the coverage floor mathematically
implies:

- At least 2 overlapping tags with the customer game
- At least 1 overlapping genre tag

Proof sketch: A game with 2 genres and 0 themes has denominator 6. A creator
matching 1 genre with perfect evidence scores `3/6 = 0.5` exactly, which fails
the strict `> 0.5` check. Reaching above 0.5 requires either a second genre
match or a genre + theme/mechanic combination, both of which guarantee 2+ tags
and 1+ genre.

These properties emerge from the weighted scoring rather than being separate
rules. No additional tag-count or tag-type checks are needed as business rules.

### SQL pre-filter: overlap_count >= 2

Although the strict `> 0.5` floor is the only *matching rule*, the SQL query that
fetches candidate tag counts will enforce `overlap_count >= 2` in its CTE. This
is a performance optimization, not a business rule — any creator with only 1
overlapping tag scores at most `3/6 = 0.5` (one genre on a 2-genre game), which
fails the strict threshold. Filtering them in SQL avoids transferring and scoring
rows that will certainly be discarded.

### CustomerGame validation: minimum 2 genre tags

A CustomerGame must have at least 2 genre tags for the prospects page to generate
results. Without sufficient genre tags, the coverage scoring cannot meaningfully
differentiate creators, and the matching threshold cannot reliably imply genre
overlap.

The prospects page should show a clear message when a game has fewer than 2 genre
tags, directing the user to add more tags before prospects can be generated.

### Filter bounds derived from matched candidates

The two separate aggregate queries (`max_reach_with_overlap` and
`max_relevant_games_with_overlap`) are removed. Filter slider upper bounds
(reach max, relevant games max) are computed as a byproduct of the scoring
pipeline from the already-scored matched candidate set.

This eliminates two expensive SQL queries that currently block page rendering.
The resulting bounds are more useful to the user because they reflect the actual
range of their matched prospects, not the range of all creators with any tag
overlap.

### Remove hard fetch limit

The current `fetch_limit = max((offset + limit) * 4, 5000)` is replaced by
quality-based filtering. The `LIMIT` clause in `query_creator_tag_counts` either
becomes a large safety cap (to prevent runaway queries in degenerate cases) or is
removed entirely if the matching thresholds sufficiently constrain the result set.

The matching thresholds themselves become the candidate-limiting mechanism.

## Changes by file

### `app/prospects/repository.py`

**`query_creator_tag_counts()`**:
- Add `HAVING COUNT(*) >= 2` (or equivalent) to the `eligible_creators` CTE
- Remove or raise the `LIMIT ?` to a safety cap
- Remove the `ORDER BY overlap_count DESC` that was only meaningful with the
  top-N limit

**Remove `max_reach_with_overlap()` and `max_relevant_games_with_overlap()`**:
- These methods are no longer called; filter bounds come from the scored set

**Remove `count_creators_with_overlap()`**:
- This method and its service wrapper `count_prospects()` are unused (no callers
  found outside the service itself). Remove both as dead code.

### `app/prospects/service.py`

**`_build_filtered_candidates()`**:
- Add the strict 50% coverage floor to the scoring loop (skip creators with
  `coverage_score <= 0.5`)
- Compute `reach_filter_max` and `games_filter_max` from the scored candidate
  set as a byproduct
- Remove the `fetch_limit` parameter or repurpose it as a safety cap
- Return the derived filter bounds in `_FilteredCandidates`

**Remove `max_reach()`, `max_relevant_games()`, and `count_prospects()`**:
- No longer needed; filter bounds are derived from the matched set
- `count_prospects()` is dead code with no callers

**`rank_prospects()`**:
- Return the derived filter bounds alongside prospects, total count, and status
  counts
- Remove the `fetch_limit` computation

### `app/prospects/router.py`

**`game_prospects_page()`**:
- Remove the pre-ranking calls to `service.max_reach()` and
  `service.max_relevant_games()`
- Get filter bounds from the `rank_prospects()` return value
- Add a guard for CustomerGame genre tag count: if fewer than 2 genre tags,
  render a message instead of running the ranking pipeline
- Adapt filter clamping logic to use the new bounds source

**`update_prospect_workflow()` route handler**:
- No changes needed; the router handler calls `service.count_ranked_prospects()`
  after the upsert, which delegates to `_build_filtered_candidates()` and will
  inherit the new threshold automatically

### `app/prospects/models.py`

- Add `reach_filter_max: int` and `games_filter_max: int` fields to
  `_FilteredCandidates` (or a new return dataclass if the internal class is not
  suitable for the public API)
- These fields are populated by `_build_filtered_candidates()` and surfaced
  through `rank_prospects()` to the router

### `app/frontend/templates/games/prospects.html`

- Add an empty state for games with insufficient genre tags
- No other template changes needed; filter sliders already accept max values
  from the route context

## What does not change

- The coverage scoring formula and tag weights
- The `tag_evidence` saturating curve
- Workflow state management and status tabs
- Contact method filtering logic
- Pagination behavior
- Display profile hydration (already only fetches the page slice)
- Relevant games hydration (already limited to 10 per account)

## Expected impact

- The candidate set shrinks significantly (creators with low tag overlap or
  single-tag matches are excluded before scoring and profile hydration)
- Filter-max aggregate queries are eliminated (2 fewer SQL round trips per GET)
- The `fetch_limit` blunt instrument is replaced by meaningful quality thresholds
- Page load time improves proportionally to the reduction in candidate set size
- The definition of "prospect" becomes explicit and intentional rather than
  "anyone with any tag overlap"

## Validation

- Compare page load times before and after using existing timing logs
- Verify that the top-ranked creators (high coverage scores) still appear in the
  same order
- Verify that creators previously shown with very low coverage scores are now
  excluded
- Verify filter slider bounds are reasonable and reflect the matched set
- Verify the insufficient-genre-tags empty state renders correctly
- Verify workflow updates still return correct status counts
