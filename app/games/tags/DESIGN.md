# Tag System Design

Tags are a big part of how SpawnRadar understands what a game is and who it's for. They drive
discovery queries, score candidate creators and let game developers articulate
their game's identity in structured terms.

## Four dimensions

Every game has tags across four orthogonal dimensions. Each dimension answers a
different question.

| Dimension | Question | Examples |
|-----------|----------|---------|
| **Genre** | What kind of game is it? | `roguelite`, `deckbuilder`, `soulslike` |
| **Mechanics** | How does it play? | `permadeath`, `procedural generation`, `meta-progression` |
| **Vibe** | What does it feel like? | `pixel art`, `dark fantasy`, `atmospheric` |
| **Kindred** | Which other games share its audience? | `hades`, `elden ring`, `stardew valley` |

**Genre** is the broadest signal — it roughly maps to Steam categories and is
what most queries are built from.

**Mechanics** captures the systems that make a game feel the way it does. Two
games can share a genre but feel completely different because of mechanics.
`permadeath` and `meta-progression` together say something very specific about
what kind of player a game attracts.

**Vibe** is aesthetic and tonal. It doesn't describe what you do in a game, it
describes what the experience feels like. A `soulslike` can be `dark fantasy` or
`sci-fi`; a `deckbuilder` can be `pixel art` or `cinematic`. Vibe helps
distinguish games that would otherwise look identical by genre and mechanics.

**Kindred** is a list of comparable titles whose playerbase overlaps with this
game. The insight is simple: if your game would appeal to fans of Hades, you
should be looking for Hades content creators. Kindred spans the full spectrum
from small indie games to major AAA titles — a solo-dev roguelite can legitimately
claim Elden Ring as kindred because some players love both.


## Tag profiles

Each dimension holds a **profile** rather than a flat list. Genre profiles split
tags into two buckets; all other dimensions are flat (primary only).

**Genre — primary and secondary:**
- **Primary** — core identity. A game with `roguelite` as primary is *defined*
  by that genre. These tags drive most discovery queries.
- **Secondary** — supporting signal. Present but not the whole story.

```
primary:    roguelite, deckbuilder
secondary:  puzzle
```

**Mechanics, Vibe, Kindred — primary only:**

These dimensions don't have a secondary tier. Tags are just a flat list of
signals, all treated with equal weight.

```
mechanics:  permadeath, meta-progression
vibe:       pixel art, dark fantasy
kindred:    hades, binding of isaac
```

Tags don't have to match the catalog. A developer can type any tag they want —
it gets normalized (lowercased, punctuation collapsed) and stored as-is. The
catalog exists to suggest good tags and catch common synonyms, not to restrict
what developers can express.

When the same tag appears in both primary and secondary (genre only), the
stronger bucket wins and the duplicate is dropped.


## Normalization

Developers type tags as free text. The normalization pipeline maps this to
catalog entries:

1. **Key cleaning** — lowercase, strip whitespace, collapse punctuation.
   `"Deck-Builder"` → `"deck builder"`
2. **Alias lookup** — common abbreviations and alternate spellings resolve to
   canonical forms. `"rts"` → `"real-time strategy"`, `"bg3"` → `"baldurs gate"`
3. **Fuzzy fallback** — small typos are caught via edit distance.
   `"metroidvaina"` → `"metroidvania"`
4. **Passthrough** — anything that still doesn't match is kept as a normalized
   string. Non-catalog tags survive intact.

The important principle: **normalization never drops a tag**. Developers can
describe genuinely new subgenres and the system records them faithfully.


## How tags flow through the system

```
Developer sets tags
        │
        ▼
   TagProfile (primary + secondary for genre; primary only for others)
        │
        ├──► Query builder
        │       Composes search queries: [prefix?] [genre?] [second tag?] [suffix?]
        │       Each query carries SourceTags provenance (which tag produced it)
        │
        ├──► Discovery sources (YouTube, Twitch, Bluesky, Reddit)
        │       Run queries, collect CandidateRecords
        │       CandidateRecord.raw_data stores source_genre_tag, source_mechanics_tag,
        │       source_vibe_tag for the query that found each creator
        │
        └──► Scoring engine
                Scores each candidate on genre_fit, mechanics_fit, vibe_fit, kindred_fit
                Primary tags carry more weight than secondary in the scoring pass
```

### Query composition

Discovery queries are built by randomly composing tag components:

```
indie  roguelite  permadeath  gameplay
 │         │          │           │
prefix  primary    second      suffix
(30%)   (85%)      (45%)       (85%
```

The RNG is seeded from `game_id + run_index` so each run is reproducible but
different runs explore different combinations. A game with many tags doesn't just
cycle through them sequentially — every query is a fresh draw across all
dimensions, giving uniform coverage regardless of tag count.


## Extending the catalog

To add a new tag:
- Add it to the appropriate catalog list in `_catalog.py` (keep it sorted).
- Add aliases if there are common alternate spellings or abbreviations.
- Optionally add it to the featured list for the UI quick-pick widget.

The catalogs are intentionally conservative. Tags should represent genuine
signals that show up in how creators and communities talk about games — not
every possible descriptor. When in doubt, let it pass through as-is rather than
canonicalising something prematurely.
