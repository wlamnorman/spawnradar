# SpawnRadar: Discovery System Vision
## Tags, Queries, and the Path to Genuine Diversification

*Last updated March 2026. Living document — update as the system evolves.*

---

## Table of Contents

1. [The Current System — What We Have](#1-the-current-system--what-we-have)
2. [The Core Problem: Tags Drive Everything](#2-the-core-problem-tags-drive-everything)
3. [The Five-Dimension Tag Model](#3-the-five-dimension-tag-model)
4. [The Diversification Problem](#4-the-diversification-problem)
5. [Tag-Aware Query Strategy (Future)](#5-tag-aware-query-strategy-future)
6. [Tag Effectiveness Feedback Loops (Future)](#6-tag-effectiveness-feedback-loops-future)
7. [LLM Tag Inference (Future)](#7-llm-tag-inference-future)
8. [Tag Similarity and Cluster Expansion (Future)](#8-tag-similarity-and-cluster-expansion-future)
9. [Roadmap](#9-roadmap)

---

## 1. The Current System — What We Have

### 1.1 Architecture

SpawnRadar's discovery pipeline:

```
Game tags
   ↓
build_tagged_queries()         ← templates per tag dimension + run_index rotation
   ↓
Per-source discovery           ← YouTube API, YouTube scraper, Reddit, Bluesky
   ↓
Prospect upsert                ← dedup by (platform, handle); excluded_handles filter
   ↓
LLM + keyword scoring          ← 7 dimensions, weight tables differ by prospect_type
   ↓
Draft items in queue           ← ordered by priority_score
```

Tags are the **first domino**. Every prospect that appears in a customer's queue was found because a search query — derived from a tag — returned a result that scored above 0.20. If the tags are narrow, the queue is narrow. Rich, well-structured tags produce genuinely diverse discovery.

### 1.2 Tag structure (as of March 2026)

The system now has **four searchable tag dimensions** plus platform:

| Kind | Catalog size | Featured | Purpose |
|---|---|---|---|
| Genre | 105 | 29 | What kind of game it is |
| Audience | 76 | 26 | Who plays it |
| Mechanics | 22 | 8 | How it plays — specific systems |
| Tone | 18 | 8 | Aesthetic and emotional register |
| Platform | 4 | — | Where it runs (checkboxes, not scored) |

Each of the four searchable dimensions has primary and secondary buckets with scoring weights:

| Bucket | Score weight | Meaning |
|---|---|---|
| Primary | 1.0 | Core identity, searched first |
| Secondary | 0.72 | Broadening coverage |
| Custom | 0.55 | User-typed freeform tags |

### 1.3 How queries are built

`build_tagged_queries()` iterates over all four tag dimensions. For each tag, it applies a per-source, per-dimension template list. The `run_index` parameter is used to `_rotate()` the template and tag lists, so successive runs execute queries in a different order and bias toward unexplored templates.

Each `TaggedQuery` carries provenance: `source_genre_tag`, `source_audience_tag`, `source_mechanics_tag`, `source_tone_tag`. The scoring engine uses these to grant **0.85× credit** when a prospect was found by a tag's query even if that tag doesn't appear literally in their profile text.

### 1.4 Scoring

`score_prospect()` computes seven dimensions per prospect/game pair. Weights differ by `prospect_type` (creator / community / developer):

| Dimension | Creator | Community | Developer |
|---|---|---|---|
| genre_fit | 0.25 | 0.35 | 0.30 |
| audience_fit | 0.20 | 0.25 | 0.15 |
| format_fit | 0.15 | 0.00 | 0.10 |
| activity_score | 0.15 | 0.05 | 0.25 |
| contactability | 0.10 | 0.05 | 0.15 |
| audience_size | 0.10 | 0.20 | 0.00 |
| platform_fit | 0.05 | 0.10 | 0.05 |

Mechanics and tone tags are folded into `genre_fit` (they describe what the game is like, not who plays it).

### 1.5 Deduplication and exclusion

- `UNIQUE(game_id, prospect_id)` on `draft_items` prevents duplicate queue entries
- `_seen_handles_for_game()` pre-loads all previously surfaced handles; passed as `excluded_handles` to sources so already-seen prospects are never re-fetched
- `_game_run_index()` counts prior runs to drive rotation

### 1.6 What works well

- **Provenance tracking** is excellent. Four source tag fields let the scoring engine correctly attribute why a prospect was found.
- **Weighted buckets** let customers express tag confidence naturally.
- **LLM scoring override** means keyword matching is a floor, not a ceiling. Claude recognizes fit even when exact tag words don't appear.
- **`run_index` rotation** varies query order across runs so the first queries aren't always the same tags.
- **`excluded_handles`** prevents the pipeline from wasting API quota re-fetching already-known prospects.
- **Four tag dimensions** (genre, audience, mechanics, tone) substantially expand the query space and reach creator segments that genre/audience alone would miss.

### 1.7 What is still missing

1. **No tag coverage tracking.** We don't know which tag/template/source combinations have been searched, how often, or how productive each was. Every run starts from scratch with no memory.
2. **No pagination / offset advancement.** YouTube searches return page 1 every time. Pages 2-5 contain the long-tail creators who are often the best prospects for indie outreach.
3. **No tag effectiveness signal.** Tags that produce only low-scoring prospects continue to be used with equal priority to tags that reliably surface strong prospects.
4. **No LLM tag suggestion at game creation.** Customers have to know the taxonomy to use it well; many pick overly generic tags.
5. **No tag similarity expansion.** A game tagged `roguelite` doesn't automatically explore `action roguelike` or `deckbuilder` spaces even though those communities heavily overlap.

---

## 2. The Core Problem: Tags Drive Everything

A game tagged `["roguelite", "deckbuilder"]` as primary genre generates approximately these YouTube queries per run (with 4 templates each):

```
roguelite games
indie roguelite game
roguelite game review
roguelite gameplay
deckbuilder games
indie deckbuilder game
deckbuilder game review
deckbuilder gameplay
```

That's 8 queries. Each query returns the same top results unless YouTube's index changes. After 3-4 runs, the excluded_handles filter removes most of these results because they've already been ingested. The queue drains but stops growing.

When customers say "I'm getting the same people every time I run discovery," they are correct. Diversification requires all three: **richer tag vocabulary**, **smarter query construction**, and **coverage-aware scheduling**.

---

## 3. The Five-Dimension Tag Model

The four dimensions we have (genre, audience, mechanics, tone) cover most of the space well. There is one remaining dimension worth adding in the future:

### 3.1 Genre — what kind of game (implemented)

105 tags. Describes the mechanical category. These are the most searchable terms because creators and communities self-identify with genre labels.

**Remaining gap:** Sub-genre specificity warnings. "rpg" alone is too broad. The UI could warn when a broad tag is used without a narrowing secondary tag.

### 3.2 Audience — who plays it (implemented)

76 tags. Describes player identity rather than game mechanics. Audience tags let us search for **people**, not just content. "speedrunners" and "slay the spire fans" are searchable identities on YouTube, Reddit, and Bluesky.

**Remaining gap:** Flagship community audience tags for more genres. Highly specific tags like "hades fans" or "elden ring fans" reach proven communities. This is low-effort, high-impact:

```
Genre              → Fan community tags to add
─────────────────────────────────────────────────────
jrpg               → persona fans, final fantasy fans, dragon quest fans
soulslike          → elden ring fans, dark souls fans, fromsoft fans
tactical rpg       → fire emblem fans, advance wars fans
battle royale      → warzone players, apex legends players
crpg               → baldurs gate fans, divinity fans
survival           → valheim fans, minecraft fans, dont starve fans
metroidvania       → hollow knight fans, ori fans
```

### 3.3 Mechanics — how it plays (implemented)

22 tags. Describes specific gameplay systems that cut across genres. A "roguelite" can have `permadeath`, `procedural generation`, `meta-progression`, and `run-based` mechanics — each reaching creators who make content about those systems even if they don't identify with the genre label.

Templates (YouTube): `"games with {tag}"`, `"{tag} games"`, `"best games with {tag}"`, `"{tag} game design"`

### 3.4 Tone — what it feels like (implemented)

18 tags. Describes aesthetic and emotional register. A `cozy` game and a `brutal` game can both be roguelites but attract completely different creators. The "cozy gaming" YouTube community (~2M subscribers across top 20 channels) is invisible to genre searches.

Templates (YouTube): `"{tag} games"`, `"{tag} indie games"`, `"{tag} game aesthetic"`, `"best {tag} games"`

### 3.5 Content format — what content it generates (future)

Some games are inherently suited to specific content types. Tags like `speedrun-viable`, `streaming-friendly`, `daily-puzzle`, `tier-list`, `video-essay-worthy` would let us search for creators based on their **format**, not their genre focus.

This is currently handled implicitly through `format_fit` in the scoring engine (LLM-assessed), but not yet expressed as tags that drive search queries.

### 3.6 The five-dimension model

```
┌─────────────────────────────────────────────────────────────────┐
│                    FIVE-DIMENSION TAG MODEL                      │
├──────────────┬──────────────────────────────────────────────────┤
│ Dimension    │ Status         │ Examples                        │
├──────────────┼────────────────┼─────────────────────────────────┤
│ Genre        │ Implemented    │ roguelite, tactical rpg, fps    │
│ Audience     │ Implemented    │ speedrunners, cozy gamers       │
│ Mechanics    │ Implemented    │ permadeath, meta-progression    │
│ Tone         │ Implemented    │ dark fantasy, pixel art, cozy  │
│ Format       │ Future         │ speedrun-viable, streaming-     │
│              │                │ friendly, daily-run             │
└──────────────┴────────────────┴─────────────────────────────────┘
```

Each dimension generates different search queries, reaches different creator segments, and provides independent scoring signal. A prospect matching on three dimensions independently is almost certainly a strong fit.

---

## 4. The Diversification Problem

### 4.1 Why the queue feels stale

The staleness problem is at the **prospect discovery level**. If the same queries run every week and return the same top results, the prospect pool barely grows. The `excluded_handles` filter is correct — it prevents re-processing — but it means the pipeline needs genuine query diversity to keep finding new people.

The `run_index` rotation helps at the template level (different templates run first on different runs), but it doesn't solve the deeper problem: we never paginate past page 1 of any query.

### 4.2 Three kinds of diversification needed

**Type 1: Query diversity within a run** — Explore different parts of the search space rather than hitting the same queries every time. With 4 tag dimensions × multiple tags × multiple templates, there are hundreds of possible queries. We should sample strategically so that over many runs, we cover the full space.

**Type 2: Temporal diversity across runs** — Track which queries have been run recently. If "roguelite games" was searched last week, this week prioritize "roguelite game review" and deprioritize already-covered ground.

**Type 3: Prospect diversity within a queue** — Even genuinely new prospects tend to be the same archetypes: large channels with the exact genre word in their name. Diversity means covering different channel sizes, content formats, sub-communities, and emerging creators.

---

## 5. Tag-Aware Query Strategy (Future)

### 5.1 Tag coverage tracking

The highest-leverage addition is a **tag coverage log**. For each `(game_id, tag, template, source)` combination, track:

```sql
CREATE TABLE tag_search_coverage (
    coverage_id     TEXT PRIMARY KEY,
    game_id         TEXT NOT NULL REFERENCES games(game_id) ON DELETE CASCADE,
    tag             TEXT NOT NULL,
    tag_dimension   TEXT NOT NULL,   -- genre | audience | mechanics | tone | format
    template        TEXT NOT NULL,
    source          TEXT NOT NULL,   -- youtube | reddit | bluesky
    last_searched_at TEXT,
    result_count    INTEGER DEFAULT 0,
    high_score_count INTEGER DEFAULT 0,
    search_offset   INTEGER DEFAULT 0,
    UNIQUE(game_id, tag, template, source)
);
```

With this, each discovery run can make an intelligent selection decision:
1. **Never-searched combos** — highest priority, explore first
2. **Low-yield combos** (many results, no high scores) — deprioritize
3. **High-yield combos searched long ago** — re-run at an advanced offset
4. **High-yield combos searched recently** — skip this run

### 5.2 Pagination as a diversification tool

YouTube returns results in ranked order. Page 1 returns the 10 biggest channels. Pages 3-5 return mid-tier creators who are often better prospects for indie outreach.

The `search_offset` field enables **progressive pagination**: run 1 searches page 1, run 2 searches pages 2-3, run 3 pages 4-6. Over time, we systematically work through the long tail of each query. This is the single highest-impact change available — no schema changes needed beyond the coverage table, and it immediately shifts discovery toward underexplored creators.

**Expected impact:** Each subsequent run finds 60-80% new prospects vs. the current 10-20%.

### 5.3 Query budget allocation

Given API quota constraints, not all queries can run every discovery run. A smart allocator:

1. **40% of budget** → never-searched combos (pure exploration)
2. **30% of budget** → high-yield combos with `last_searched_at` age > 14 days
3. **20% of budget** → high-yield combos at a new `search_offset` (pagination)
4. **10% of budget** → exploratory combos from low-weight secondary tags

---

## 6. Tag Effectiveness Feedback Loops (Future)

### 6.1 The signal we're ignoring

Every `Outcome` (approved / rejected / snoozed) is connected to a prospect that has a `source_genre_tag` in its `raw_data`. We are not connecting these two facts.

The connection tells us: **which tags produce prospects that customers actually want to contact.**

### 6.2 Tag performance metrics

For each `(game_id, tag)` pair:

```
discovery_rate    = prospects_found / searches_run
approval_rate     = approved_outcomes / prospects_queued_from_tag
avg_final_score   = mean(final_score) for prospects from this tag
```

- **High approval_rate + high avg_final_score** → core tag, maximize budget
- **High discovery_rate + low approval_rate** → noisy tag, too broad or wrong audience
- **Low discovery_rate** → exhausted tag, advance to pagination or deprioritize

### 6.3 Customer-facing tag performance

Display per-tag stats on the setup page. "roguelite is producing 70% approval rate. Your 'moba' tag has zero approvals after 3 runs — consider removing it."

### 6.4 Cross-game tag intelligence

Aggregate tag performance across all games (anonymized). When a new roguelite game is added, suggest the audience tags that have historically produced the highest approval rates for other roguelite games. Cold-start quality improves automatically.

---

## 7. LLM Tag Inference (Future)

### 7.1 The cold-start tagging problem

Customers who don't know the taxonomy pick generic tags: "rpg" instead of "tactical rpg", "strategy" instead of "turn-based tactics." The game description is the richest tagging signal available.

### 7.2 Inference at game creation

When a game is saved (or description updated), call Claude to suggest tags from the four-dimension taxonomy. Present suggestions as one-click chips — not auto-applied, customer decides. This lowers friction while keeping customers in control.

```
Prompt structure:
  Game description: {game.description}
  Genre tags (choose 2-5): {GENRE_TAG_CATALOG}
  Mechanics tags (choose 2-6): {MECHANICS_TAG_CATALOG}
  Tone tags (choose 1-4): {TONE_TAG_CATALOG}
  Audience tags (choose 3-8): {AUDIENCE_TAG_CATALOG}
  Return JSON: {"genre": [...], "mechanics": [...], "tone": [...], "audience": [...]}
```

**Expected impact:** Games go from ~5-8 tags to 12-20 relevant tags from day one.

### 7.3 Iterative refinement from prospect signal

After the first run, a second inference pass: "given these high-scoring prospects, what tags explain why they fit?" Surfaces patterns customers didn't notice: "3 of your top 5 approved prospects mention 'permadeath' prominently — consider adding it as a mechanics tag."

---

## 8. Tag Similarity and Cluster Expansion (Future)

### 8.1 Adjacent tags

A game tagged `roguelite` should eventually also explore `roguelike`, `action roguelike`, and `deckbuilder` creator spaces — these communities heavily overlap but don't appear unless explicitly tagged.

The current alias system handles spelling normalization. It doesn't handle **adjacent expansion**: discovering that related-but-distinct tags also reach valuable prospects.

### 8.2 Tag similarity graph

Build a weighted graph where edges represent co-occurrence:

```
roguelite ─0.9─ roguelike
roguelite ─0.7─ deckbuilder
roguelite ─0.6─ action roguelike
soulslike ─0.6─ action rpg
soulslike ─0.5─ dark fantasy
tactical rpg ─0.8─ turn-based tactics
tactical rpg ─0.6─ xcom fans (audience)
```

Edges can be built from: our own game co-occurrence data, Steam tag data, and Reddit subreddit member overlap.

### 8.3 Expansion queries

When a discovery run has remaining budget after covering primary/secondary tags, expand to one-hop neighbors in the similarity graph. Label these as **expansion queries** with a lower weight. If they produce high-scoring prospects, suggest adding those tags explicitly.

---

## 9. Roadmap

### Done (March 2026)

| What | Impact |
|---|---|
| Expanded genre catalog (66 → 105 tags) | Finer-grained genre searches |
| Expanded audience catalog (58 → 76 tags) | More specific audience targeting |
| Added mechanics tag dimension (22 tags) | Reaches creators covering game systems |
| Added tone tag dimension (18 tags) | Reaches aesthetic-driven communities |
| `run_index` rotation in `build_tagged_queries()` | Varies query order across runs |
| `excluded_handles` filter | Prevents re-fetching known prospects |
| Provenance tracking (4 source tag fields) | Correct scoring attribution |
| Selected tag pills are removable | Better UX for tag management |
| Suggestion chips hide already-selected tags | Cleaner tag picker UX |

### Next — High impact, low complexity

| Action | Effort | Expected outcome |
|---|---|---|
| Progressive pagination (search_offset) | 1-2 days | 60-80% new prospects per run |
| Tag coverage tracking table | 2-3 days | Coverage-aware query scheduling |
| Flagship community audience tags | 1 day | Direct access to active fan communities |

### Short-term

| Action | Effort | Expected outcome |
|---|---|---|
| Tag performance metrics (per tag approval_rate) | 3-4 days | Customer feedback loop on tag quality |
| Format tags (speedrun-viable, streaming-friendly) | 2-3 days | Format-based creator discovery |
| Query budget allocator using coverage data | 2-3 days | Each run explores different space |

### Medium-term

| Action | Effort | Expected outcome |
|---|---|---|
| LLM tag inference at game creation | 5-7 days | Better tags from day one |
| Cross-game tag intelligence for cold-start | 5-7 days | New games benefit from platform learning |
| Tag similarity graph + expansion queries | 7-10 days | Automated adjacent-space exploration |

### The big picture

The ideal discovery system is not a one-time configuration but a **living signal** that gets richer with each run:

```
Customer adds tags
       ↓
LLM inference suggests more
       ↓
Pipeline explores the full tag × template × source space
       ↓
Coverage tracking ensures no query runs twice unnecessarily
       ↓
Pagination explores the long tail of productive queries
       ↓
Outcome data identifies which tags produce approved prospects
       ↓
Tag performance surfaces back to the customer
       ↓
Cross-game learning improves cold-start for new games
       ↓
Similarity graph auto-expands into adjacent tag spaces
```

At maturity, a customer with a roguelite game who has run discovery 10 times would have:
- Explored hundreds of unique query combinations across all four dimensions
- Seen prospects from YouTube, Reddit, and Bluesky across the full audience size spectrum
- Had their tags refined by actual approval signal
- Had the system automatically explore adjacent spaces like "deckbuilder" and "action roguelike"
- Received suggestions based on what worked for similar games across the platform

The queue would feel genuinely different each week — because it would be.

---

*This is a living document. Update it when the system changes.*
