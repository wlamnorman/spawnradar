# Adding a New Ingestion Source

Each file in this directory is one platform. Adding a source means dropping a new file here and touching three other lines across the codebase.

## Steps

### 1. Add the enum member — `app/ingestion/registry.py`

```python
class Source(StrEnum):
    YOUTUBE_API = "youtube_api"
    YOUTUBE     = "youtube"
    REDDIT      = "reddit"
    BLUESKY     = "bluesky"   # ← add this
```

The string value is what gets stored in the database and in `game.discovery_sources`.

### 2. Create the source file — `app/ingestion/sources/bluesky.py`

```python
from app.ingestion.base import CandidateRecord, CandidateSource
from app.ingestion.registry import Source, register

@register(Source.BLUESKY)
class BlueskySource(CandidateSource):
    async def discover(self, game, limit) -> list[CandidateRecord]:
        ...
        return [
            CandidateRecord(
                platform="bluesky",
                handle="@alice.bsky.social",
                display_name="Alice",
                profile_url="https://bsky.app/profile/alice.bsky.social",
                contact_channel="bluesky_dm",
                contact_value=None,
                audience_size=12_000,
                engagement_rate=None,
                description="Indie game dev. Posts devlogs and playthroughs.",
                raw_data={...},            # platform-specific fields
                last_active_days=3,        # days since last post
                text_signals=["just shipped a new puzzle game", "roguelike run with chat"],
                prospect_type="creator",   # creator | community | developer
            )
        ]
```

### 3. Register the import — `app/ingestion/sources/__init__.py`

```python
from app.ingestion.sources import bluesky, reddit, youtube, youtube_api
```

This is what causes `@register(Source.BLUESKY)` to actually run at startup.

### 4. Wire up the pipeline — `app/ingestion/pipeline.py`

Add an `elif source_name == Source.BLUESKY:` branch in `run_ingestion` that
instantiates the source and appends `(BlueskySource(...), limit_per_source)` to
the sources list. Pass any required credentials through `run_ingestion`'s
signature (follow the pattern used for `youtube_api_key`).

### 5. (Optional) Add a typed raw_data model — `app/ingestion/raw_data.py`

If the source stores platform-specific fields in `raw_data` that you want
typed access to inside the source file itself, add a Pydantic model:

```python
class BlueskyProfileData(BaseModel):
    did: str
    handle: str
    follower_count: int
    ...
```

This is only used inside your source file — the pipeline and scoring engine
always read through the normalized fields (`last_active_days`, `text_signals`,
`prospect_type`).

---

## Normalized fields every source must populate

| Field | Type | Purpose |
|---|---|---|
| `last_active_days` | `int \| None` | Days since last post/upload/activity. Drives `activity_score` in the scoring engine. `None` = unknown (gets a neutral 0.4). |
| `text_signals` | `list[str]` | Recent post titles, video titles, stream titles, devlog excerpts — whatever best represents recent content. Fed to the LLM prompt and used for keyword scoring. |
| `prospect_type` | `str` | `"creator"` — individual content creator (YouTuber, streamer, Bluesky poster). `"community"` — a space to post in (subreddit, Discord server). `"developer"` — an indie dev as a potential customer. |

Setting these correctly is the main contract between a source and the rest of the
pipeline. The scoring engine and LLM prompt read these fields and nothing else
from the source-specific `raw_data`.

---

## Source priority (from channel-research.md)

Recommended order to implement new sources:

1. **Bluesky** — open API, strong indie dev signal, real-time search available
2. **itch.io** — RSS feeds and jam pages, early-stage developer discovery
3. **Steam** — public event pages (Next Fest), upcoming launch detection
4. **Twitch** — Helix API, creator discovery for live-streaming audience
5. **Reddit** — already implemented; requires commercial API approval for production use
6. **Discord** — opt-in integrations only, not a broad crawler
7. **GitHub** — enrichment source for developer profiles, not primary discovery
