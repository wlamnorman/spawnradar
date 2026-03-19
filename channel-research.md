# Channel And Source Research

This is a working note for SpawnRadar product and ingestion planning.

## What channels look strongest for indie developers

### 1. Reddit

Why it matters:

- High intent. People ask for feedback, share demos, look for playtesters, and react to launches in public.
- Good fit for the "opportunity alerts" idea because relevant threads appear continuously.
- Strong signal density around genre communities, engine communities, and platform-specific communities.

Why it is tricky:

- Reddit's current policies are much stricter than they used to be for commercial usage.
- If SpawnRadar is a commercial product using Reddit data to power discovery or alerts, assume approval/contract review is needed.

Product fit:

- Opportunity alerts
- Community discovery
- Suggested draft generation for replies or posts

Key sources:

- Reddit API docs: <https://www.reddit.com/dev/api/>
- Reddit developer/commercial guidance: <https://redditinc.com/policies/developer-terms>
- Reddit Data API terms: <https://redditinc.com/policies/data-api-terms>
- Reddit help on commercial access: <https://support.reddithelp.com/hc/en-us/articles/14945211791892-Developer-Platform-Accessing-Reddit-Data>

### 2. Bluesky

Why it matters:

- Open network, easier to search and monitor than most large social platforms.
- Good for finding devlogs, launch announcements, demo announcements, festival participation, and "what should I do for marketing?" posts.
- Better long-term source than X/Twitter for productized discovery because the API surface is much more open.

Product fit:

- Real-time alerts
- Search for devs by profile and post content
- Trend detection across tags like `indiedev`, `gamedev`, engine names, genre names, festivals, and release milestones

Key sources:

- Bluesky docs: <https://docs.bsky.app/>
- Search posts API: <https://docs.bsky.app/docs/api/app-bsky-feed-search-posts>
- Search actors API: <https://docs.bsky.app/docs/api/app-bsky-actor-search-actors>
- Jetstream event stream: <https://github.com/bluesky-social/jetstream>

### 3. YouTube

Why it matters:

- Still one of the best channels for finding creators who can cover indie games.
- Also useful for finding indie developers themselves through devlogs, postmortems, trailer drops, and "making my first game" channels.
- Strong metadata surface: channel descriptions, topics, uploads, publish dates, video titles.

Product fit:

- Creator discovery
- Devlog monitoring
- "Find similar creators" workflows

Key sources:

- YouTube Data API overview: <https://developers.google.com/youtube/v3>
- Channels resource: <https://developers.google.com/youtube/v3/docs/channels>

### 4. Twitch

Why it matters:

- Useful for finding small-to-mid creators who stream indie games and demos.
- Also useful for spotting developers who stream development or community playtests.
- Strong complement to YouTube because it captures live behavior rather than just published video metadata.

Product fit:

- Creator discovery
- Livestream opportunity monitoring
- "Who is already streaming similar games?" recommendations

Key source:

- Twitch Helix reference: <https://dev.twitch.tv/docs/api/reference>

### 5. Steam

Why it matters:

- Steam is still the most important public launch surface for many PC indies.
- Steam Next Fest is especially important because it is effectively a structured source of upcoming indie launches, demos, and developer livestream activity.

Why it is tricky:

- Steam does not give you the same kind of clean open discovery API surface that Bluesky or YouTube gives you for this use case.
- Some of the value will likely come from public page ingestion and event-page ingestion rather than a formal developer API.

Product fit:

- Upcoming launch detection
- Festival participation detection
- Competitive landscape and lookalike discovery

Key source:

- Steam Next Fest docs: <https://partner.steamgames.com/doc/marketing/upcoming_events/nextfest/2026june>

### 6. itch.io

Why it matters:

- Great source for very early-stage indie developers, game jams, prototypes, and experimental projects.
- Particularly strong if you want SpawnRadar to find developers before they are "launch-ready" on Steam.
- Jams and browse feeds are valuable signals even when the authenticated API is account-centric.

Why it is tricky:

- The official API is mainly for account data and OAuth access rather than broad public discovery.
- For discovery, the public browse feeds and jam/community pages are more interesting than the authenticated account API.

Product fit:

- Early-stage developer discovery
- Jam monitoring
- Prototype and devlog lead generation

Key sources:

- itch.io API overview: <https://itch.io/docs/api/overview>
- itch.io server-side API: <https://itch.io/docs/api/serverside>
- itch.io OAuth: <https://itch.io/docs/api/oauth>
- itch.io jam docs: <https://itch.io/docs/creators/game-jams>

### 7. Discord

Why it matters:

- Many indie developers actually live in Discord communities, private or public.
- Excellent for engagement and long-tail community presence.

Why it is tricky:

- Discovery is weaker than on open networks.
- Data access is fragmented: many valuable servers are private or invite-only.
- Best used as an execution/community channel or through opt-in integrations, not as the first broad discovery source.

Product fit:

- Optional community integrations
- Forum/thread opportunity detection in opted-in servers
- Alert routing destination

Key sources:

- Discord channel types (including forum/media): <https://docs.discord.com/developers/resources/channel>
- Example public server discovery pages: <https://discord.com/servers/game-dev-network-280521930371760138>

### 8. GitHub

Why it matters:

- Not a primary launch channel, but it is a surprisingly useful signal source for finding technically-oriented indie developers.
- Especially useful for open-source tools, engine plugins, game jam repos, Godot/Unity/Unreal experiments, and people who publicly identify with gamedev topics.

Product fit:

- Finding devs as potential customers
- Enriching developer profiles with engine/tooling preferences
- Identifying technical creators or solo devs early

Key sources:

- GitHub repository topics docs: <https://docs.github.com/en/github/administering-a-repository/classifying-your-repository-with-topics>
- GitHub repositories API docs: <https://docs.github.com/en/rest/repos/repos>

## Recommended source priority for SpawnRadar

If the goal is product leverage, I would prioritize sources like this:

1. Bluesky
2. YouTube
3. Steam public/event pages
4. itch.io public feeds and jams
5. Twitch
6. Reddit, but only if legal/commercial access is squared away early
7. Discord as an opt-in integration, not a broad crawler
8. GitHub as an enrichment and developer-finding source

Why this order:

- Bluesky is the best mix of openness and signal.
- YouTube and Twitch directly support creator discovery, which is already close to SpawnRadar's core value.
- Steam and itch.io are where game and developer intent is explicit.
- Reddit is strategically important but policy-sensitive.

## Information sources beyond official APIs

SpawnRadar should not think only in terms of "API or nothing."

Useful source types:

- Public RSS/XML feeds
  - itch.io browse feeds and new uploads feed are especially useful.
- Event pages
  - Steam Next Fest, jam pages, showcase pages, expo pages.
- Public profiles
  - developer bios, external links, studio websites.
- Public posts and devlogs
  - Bluesky posts, YouTube descriptions, public Discord forum posts where accessible.
- Store pages
  - game descriptions, tags, release windows, demo/live status, developer/publisher names.

This matters because some of the best discovery surfaces for indie devs are only partially API-driven.

## Creating formats for outreach to content creators (we can build a general format from this that we use to suggest formats)
https://www.wanderbots.com/blog/quick-reference-checklist-for-developers-contacting-creators
https://www.wanderbots.com/blog/templates-for-contacting-content-creators


## How SpawnRadar can be used to find indie developers

Right now SpawnRadar is framed as "find creators and communities for a game."
It can also become "find games and developers who are likely to need help."

That is a very strong acquisition angle.

### 1. Find developers by launch stage

Build detection around signals like:

- announced a game
- published a demo
- joined a festival
- launched on itch.io
- opened wishlist / playtest / feedback calls
- posted "how do I market this?" or "where should I share this?"

This is probably the highest-value way to find likely customers.

### 2. Find developers by pain signal

Look for public posts that imply a distribution problem:

- "we launched and got no traction"
- "how do I get wishlists?"
- "where can I promote my game?"
- "any subreddits/communities for X genre?"
- "looking for streamers / YouTubers / press"

That gives SpawnRadar a natural lead list of developers with active demand.

### 3. Build a developer graph

A strong internal entity model would be:

- game
- studio / developer
- publisher
- website
- social accounts
- store pages
- content channels
- current launch stage
- opportunity history

This lets you pivot from a game to the developer, and from the developer to other games or channels.

### 4. Use lookalike discovery on developers, not just games

Possible workflows:

- "Find devs like this dev"
- "Find solo PC strategy devs shipping within 12 months"
- "Find devs posting frequent progress updates but with low audience reach"
- "Find developers in genre X who have a demo but weak creator coverage"

That turns SpawnRadar into a prospecting tool for agencies, publishers, service providers, and even your own sales pipeline.

### 5. Add developer alerts

This is the mirror image of opportunity alerts.

Examples:

- notify me when a new solo-dev strategy game appears on itch.io
- notify me when a Steam Next Fest game matches these tags
- notify me when a dev posts about needing marketing help
- notify me when a studio announces a demo or release date

This is especially compelling if SpawnRadar eventually sells to:

- PR agencies
- marketing consultants
- publisher scouting teams
- community managers
- trailer/creative service providers

## Concrete product ideas

### A. Opportunity Alerts

Current direction and still strong:

- notify the developer when good posting opportunities appear

Best early sources:

- Bluesky
- Reddit, if permitted
- opted-in Discord forums

### B. Developer Alerts

New direction worth exploring:

- notify a user when a relevant indie developer appears or becomes active

Best early sources:

- itch.io jams and feeds
- Steam event pages
- Bluesky launch/devlog posts
- GitHub gamedev topics

### C. Reverse Prospecting

SpawnRadar finds:

- games that resemble a customer's portfolio
- developers who are likely to need launch help
- communities already discussing a certain subgenre

This could be a separate product mode.

## Suggested near-term roadmap

### Phase 1

- Add Bluesky search + monitoring
- Add itch.io feed and jam ingestion
- Add Steam public event ingestion for festival/demo signals
- Add developer entities to the data model

### Phase 2

- Add GitHub enrichment for developer profiles
- Add Twitch creator discovery
- Add developer alerts and saved searches

### Phase 3

- Add Reddit only after policy/commercial path is clear
- Add opt-in Discord community integrations
- Add internal scoring for "likely needs marketing help"

## My practical take

If you want the fastest product leverage, I would do this:

1. Keep creator/community discovery as the core.
2. Add Bluesky and itch.io next.
3. Treat Steam festival/public page ingestion as a major signal source.
4. Add a parallel "developer discovery" mode inside SpawnRadar.

That gives you two strong loops:

- help devs find opportunities
- help agencies, publishers, and service providers find devs

## Sources

- Reddit API docs: <https://www.reddit.com/dev/api/>
- Reddit Developer Terms: <https://redditinc.com/policies/developer-terms>
- Reddit Data API Terms: <https://redditinc.com/policies/data-api-terms>
- Reddit commercial/developer guidance: <https://support.reddithelp.com/hc/en-us/articles/14945211791892-Developer-Platform-Accessing-Reddit-Data>
- Bluesky docs: <https://docs.bsky.app/>
- Bluesky post search: <https://docs.bsky.app/docs/api/app-bsky-feed-search-posts>
- Bluesky actor search: <https://docs.bsky.app/docs/api/app-bsky-actor-search-actors>
- Bluesky Jetstream: <https://github.com/bluesky-social/jetstream>
- YouTube Data API: <https://developers.google.com/youtube/v3>
- YouTube channels resource: <https://developers.google.com/youtube/v3/docs/channels>
- Twitch Helix API reference: <https://dev.twitch.tv/docs/api/reference>
- Steam Next Fest docs: <https://partner.steamgames.com/doc/marketing/upcoming_events/nextfest/2026june>
- itch.io API overview: <https://itch.io/docs/api/overview>
- itch.io server-side API: <https://itch.io/docs/api/serverside>
- itch.io OAuth docs: <https://itch.io/docs/api/oauth>
- itch.io game jam docs: <https://itch.io/docs/creators/game-jams>
- Discord channel docs: <https://docs.discord.com/developers/resources/channel>
- Example public game-dev Discord discovery page: <https://discord.com/servers/game-dev-network-280521930371760138>
- GitHub repository topics docs: <https://docs.github.com/en/github/administering-a-repository/classifying-your-repository-with-topics>
- GitHub repositories API docs: <https://docs.github.com/en/rest/repos/repos>
