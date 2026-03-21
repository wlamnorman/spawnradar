# Community Target Filtering

This note is about a specific quality problem in SpawnRadar discovery:

- some search results are large and active
- some look topically relevant on the surface
- but they are bad outreach targets because they are too tied to a single game, franchise, or ecosystem

Example:

- `starcraft 2 strategy forums`

That may look relevant for a strategy game, but in practice it is often a poor place to post about a different strategy game because:

- the community expectation is title-specific discussion
- the members are there for `StarCraft 2`, not strategy games in general
- self-promotion is more likely to feel off-topic or spammy

So long term, SpawnRadar should not just find places that are active. It should find places where posting is contextually acceptable.

## Product Goal

We want to distinguish between:

- `genre-level opportunities`
- `format-level opportunities`
- `title-specific communities`
- `creator ecosystems that are too narrow`

The product should prefer:

- genre communities
- adjacent communities with proven openness to similar games
- creators who cover a category, not just one title

And it should down-rank or filter:

- official game forums
- subreddits tied to one game or one franchise
- creators whose content is almost entirely one title
- communities where posting another game would be obviously off-topic

## Core Distinction: Audience Fit vs Posting Fit

A common mistake is treating these as the same thing.

They are not.

A StarCraft 2 forum may have:

- high `audience fit` for an RTS game

but low:

- `posting fit`

because the community is there for one title, not for broader discovery.

SpawnRadar should model this explicitly over time.

## Recommended Long-Term Model

Add a separate dimension called:

- `posting_fit`

This should answer:

> Is this actually a good place to share this game, given what this space is for?

That is different from:

- `genre_fit`
- `audience_fit`
- `platform_fit`

Long term, a queue item should be able to score like this:

- audience fit: high
- genre fit: high
- posting fit: low

And the final ranking should reflect that.

## Community Types We Should Track

We should treat target surfaces as different categories, not one generic bucket.

### 1. Genre Communities

Examples:

- general tactics forums
- indie strategy subreddits
- puzzle game communities

These are usually the best opportunities.

### 2. Format Communities

Examples:

- speedrunning communities
- challenge-run communities
- deckbuilder communities
- browser game communities

These can be strong if the game clearly fits the format.

### 3. Platform Communities

Examples:

- Steam Deck communities
- browser game communities
- PC strategy communities

These are useful as supporting channels, not always primary ones.

### 4. Title-Specific Communities

Examples:

- `r/starcraft`
- `r/factorio`
- official game forums
- Discord servers for one game

These are risky by default.

Some are still useful, but only if:

- the game is extremely adjacent
- the community has a history of discussing alternatives or genre comparisons
- the posting rules clearly allow it

### 5. Creator Niches

Examples:

- a channel covering many RTS games
- a channel covering mostly one live-service title

These should be treated similarly to communities. Some creators are category-focused; others are effectively single-title channels.

## High-Level Filtering Rule

Long term, SpawnRadar should classify discovered targets into:

- `broad category`
- `adjacent niche`
- `title-specific`
- `official / owned channel`

And then apply defaults:

- broad category: keep
- adjacent niche: keep, but inspect
- title-specific: down-rank heavily
- official / owned channel: usually exclude

## Signals That A Community Is Too Game-Specific

These are the best long-term indicators.

### Name Signals

If the title or handle includes:

- a known game name
- a franchise name
- a sequel number
- a studio-owned brand

then it is likely title-specific.

Examples:

- `starcraft 2 strategy forum`
- `factorio builds`
- `rimworld modding hub`

### Description Signals

If the description says things like:

- `official forum`
- `discussion for [game name]`
- `community for players of [game]`
- `mods, builds, and news for [title]`

then posting fit is likely low for unrelated games.

### Content Concentration Signals

If recent content is overwhelmingly about one title:

- same game mentioned in most recent posts
- same game in most recent video titles
- same franchise dominating the surface

then it is probably too narrow.

This is especially useful for creators.

### Rule Signals

If posting rules or pinned content say:

- no self-promo
- only content about this game
- no off-topic comparisons

the target should probably be excluded entirely.

### Moderation / Ownership Signals

If the space appears to be:

- official
- publisher-owned
- developer-run

it should usually not be treated as a discovery opportunity.

## Signals That A Community Is Broad Enough

We also need positive signals, not just exclusions.

### Multi-Title Coverage

The best sign is that the space consistently discusses:

- many games in the genre
- recommendations
- comparisons
- upcoming games
- demos
- devlogs

### Language About Taste, Not Title

Examples:

- `turn-based tactics fans`
- `browser puzzle games`
- `cozy farming sims`

These are usually better than spaces built around one named franchise.

### Visible History Of Relevant Sharing

If similar games have been posted and discussed well, that is one of the strongest indicators that the target is worth keeping.

## Recommended Data We Should Store

To make this decision well, we need more than a name and a score.

For communities and creators, long term we should store:

- normalized target type
- recent titles or post headlines
- pinned text or rules summary if available
- description text
- official/unofficial guess
- dominant title mentions
- dominant genre mentions
- share of recent content tied to a single title

That gives us enough to build a real `posting_fit` model later.

## A Practical Heuristic We Can Add Later

Before we build a full classifier, there is a simple rule-based layer that would already help:

1. extract named game titles from target name + description + recent content
2. count how concentrated the references are
3. if one title dominates, mark the target as `title_specific`
4. if that title is not the user's game, down-rank sharply

This will not be perfect, but it should catch a lot of obvious false positives.

## How To Detect "Dominant Title"

Long term, use a combination of:

- alias dictionary of known games/franchises
- Steam / itch / IGDB title lists for enrichment
- simple NER-style extraction over recent titles
- frequency thresholds

A good first-pass rule:

- if one non-user game title appears in more than 60 percent of recent content signals, treat the target as title-specific

That is not enough alone, but it is a strong signal.

## Should We Build A Forum Crawler?

Maybe, but not as a broad crawler first.

My recommendation:

- do not start with a general forum crawler
- start with sources that already give cleaner signals
- only crawl forums when we have a strong reason to

Why:

- forums are messy and structurally inconsistent
- rules are often hard to extract reliably
- a lot of forums are low-value or abandoned
- many are title-specific, which creates more false positives

So the better approach is:

- use curated or semi-curated forum sources
- whitelist known valuable forums
- treat forum crawling as an enrichment step, not a first-pass discovery engine

### Better near-term alternatives

Before broad forum crawling, I would prioritize:

- subreddit and community opportunity monitoring
- Bluesky / social post monitoring
- Steam discussion and event surfaces
- creator discovery

These are easier to rank and usually more actionable.

## If We Ever Add A Forum Crawler

It should be constrained.

Recommended design:

### 1. Whitelist-first

Do not crawl arbitrary domains. Start with a curated set of known useful forums.

### 2. Page-type detection

Only ingest:

- forum home pages
- category pages
- rules pages
- recent discussion indexes

Do not crawl deeply by default.

### 3. Posting-fit classifier

Every crawled forum should be classified before it becomes a surfaced opportunity:

- broad genre forum
- platform forum
- title-specific forum
- official support forum
- unclear

### 4. Rule extraction

If we cannot infer whether posting another game is acceptable, the target should not rank highly.

## Product UI Recommendation

Once we support this better, the queue should explain why a community is or is not a good place to post.

Examples:

- `Broad strategy community with recent discussion of multiple indie tactics games`
- `Large audience, but mostly dedicated to StarCraft 2 and unlikely to welcome unrelated posts`

This is better than showing only a numeric fit score.

## Recommended Roadmap

### Phase 1

- keep current discovery
- add heuristics that down-rank obvious title-specific communities and creators
- add an internal `posting_fit` field, even if rule-based at first

### Phase 2

- store more recent-content evidence
- detect dominant title concentration
- surface warnings in the queue

### Phase 3

- add historical outcome feedback
- learn from accepted vs rejected opportunities
- separate `audience fit` from `posting fit` in the UI and ranking

### Phase 4

- optional curated forum ingestion
- optional crawler/enrichment for specific vetted domains

## Concrete Recommendation

Long term, SpawnRadar should not ask:

> Does this audience look relevant?

It should ask:

> Is this a place where sharing this game is actually appropriate?

That means:

- treat title-specific communities as a separate class
- model `posting_fit` explicitly
- avoid broad forum crawling early
- prefer curated or high-signal sources first

That will reduce noisy opportunities and make the queue much more trustworthy.
