CREATE TABLE IF NOT EXISTS users (
    user_id       TEXT PRIMARY KEY,
    email         TEXT UNIQUE NOT NULL,
    password_hash TEXT,                        -- NULL for Google-only accounts
    google_id     TEXT UNIQUE,                 -- NULL for password-only accounts
    is_admin      INTEGER NOT NULL DEFAULT 0,
    email_verified INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS guest_identities (
    guest_id            TEXT PRIMARY KEY,
    claimed_by_user_id  TEXT REFERENCES users(user_id) ON DELETE SET NULL,
    first_path          TEXT,
    first_referrer      TEXT,
    first_user_agent    TEXT,
    first_seen_at       TEXT NOT NULL,
    last_seen_at        TEXT NOT NULL,
    claimed_at          TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS workspaces (
    workspace_id    TEXT PRIMARY KEY,
    owner_user_id   TEXT UNIQUE REFERENCES users(user_id) ON DELETE CASCADE,
    guest_id        TEXT UNIQUE REFERENCES guest_identities(guest_id) ON DELETE CASCADE,
    workspace_type  TEXT NOT NULL, -- personal | guest
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK (
        (owner_user_id IS NOT NULL AND guest_id IS NULL AND workspace_type = 'personal')
        OR
        (owner_user_id IS NULL AND guest_id IS NOT NULL AND workspace_type = 'guest')
    )
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id  TEXT PRIMARY KEY,
    user_id     TEXT REFERENCES users(user_id) ON DELETE CASCADE,
    guest_id    TEXT REFERENCES guest_identities(guest_id) ON DELETE CASCADE,
    expires_at  TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK (
        (user_id IS NOT NULL AND guest_id IS NULL)
        OR
        (user_id IS NULL AND guest_id IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS subscriptions (
    subscription_id    TEXT PRIMARY KEY,
    workspace_id       TEXT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    paddle_customer_id     TEXT,
    paddle_subscription_id TEXT,
    tier               TEXT NOT NULL DEFAULT 'indie',    -- indie
    status             TEXT NOT NULL DEFAULT 'active',  -- active | canceled | past_due | paused | comped
    current_period_end TEXT,
    created_at         TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    token_id    TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    expires_at  TEXT NOT NULL,
    used_at     TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS email_verification_tokens (
    token_id    TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    expires_at  TEXT NOT NULL,
    used_at     TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS customer_games (
    customer_game_id   TEXT PRIMARY KEY,
    workspace_id       TEXT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    name               TEXT NOT NULL,
    summary            TEXT,                         -- 1-2 sentence elevator pitch
    description        TEXT NOT NULL,
    slug               TEXT UNIQUE,
    website_url        TEXT,
    platforms          TEXT NOT NULL DEFAULT '[]',  -- JSON array of customer-facing platform slugs
    igdb_genre_ids     TEXT NOT NULL DEFAULT '[]',    -- JSON array of IGDB genre IDs
    igdb_theme_ids     TEXT NOT NULL DEFAULT '[]',    -- JSON array of IGDB theme IDs
    igdb_game_mode_ids TEXT NOT NULL DEFAULT '[]',    -- JSON array of IGDB game mode IDs
    igdb_player_perspective_ids TEXT NOT NULL DEFAULT '[]', -- JSON array of IGDB player perspective IDs
    igdb_keyword_ids   TEXT NOT NULL DEFAULT '[]',    -- JSON array of IGDBKeyword string values
    similar_game_names TEXT NOT NULL DEFAULT '[]',    -- JSON array of customer-provided similar game names
    llm_similar_game_names TEXT NOT NULL DEFAULT '[]', -- JSON array of LLM-suggested tight anchor games
    llm_broad_game_names TEXT NOT NULL DEFAULT '[]',   -- JSON array of LLM-suggested broad audience games
    status             TEXT NOT NULL DEFAULT 'active',
    created_at         TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS bluesky_post_drafts (
    draft_id            TEXT PRIMARY KEY,
    customer_game_id    TEXT NOT NULL UNIQUE REFERENCES customer_games(customer_game_id) ON DELETE CASCADE,
    source_game_slug    TEXT NOT NULL UNIQUE,
    workspace_id        TEXT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    creator_summary     TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'draft', -- draft | approved | rejected | published | failed
    body                TEXT NOT NULL,
    hashtags            TEXT NOT NULL DEFAULT '[]',
    creator_handle      TEXT,
    image_filename      TEXT,
    image_media_type    TEXT,
    image_bytes         BLOB,
    image_alt_text      TEXT NOT NULL DEFAULT '',
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
    reviewed_at         TEXT,
    approved_at         TEXT,
    rejected_at         TEXT
);

CREATE INDEX IF NOT EXISTS idx_bluesky_post_drafts_status_updated
    ON bluesky_post_drafts(status, updated_at);

CREATE TABLE IF NOT EXISTS metric_events (
    event_id    TEXT PRIMARY KEY,
    metric_key  TEXT NOT NULL,
    user_id     TEXT REFERENCES users(user_id) ON DELETE SET NULL,
    workspace_id TEXT REFERENCES workspaces(workspace_id) ON DELETE SET NULL,
    customer_game_id TEXT REFERENCES customer_games(customer_game_id) ON DELETE SET NULL,
    occurred_at TEXT NOT NULL,
    value       REAL NOT NULL DEFAULT 1,
    dedupe_key  TEXT UNIQUE,
    metadata    TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS request_rate_limits (
    event_id    TEXT PRIMARY KEY,
    scope       TEXT NOT NULL,
    key_hash    TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_request_rate_limits_scope_key_created
    ON request_rate_limits(scope, key_hash, created_at);

CREATE INDEX IF NOT EXISTS idx_workspaces_owner_user ON workspaces(owner_user_id);
CREATE INDEX IF NOT EXISTS idx_workspaces_guest ON workspaces(guest_id);

-- Relational tag rows for customer games, mirroring igdb_game_tags shape.
-- The JSON columns on customer_games remain as a denormalized cache;
-- this table is the authoritative source for tag queries and joins.
CREATE TABLE IF NOT EXISTS customer_game_tags (
    customer_game_id TEXT NOT NULL REFERENCES customer_games(customer_game_id) ON DELETE CASCADE,
    tag_type         TEXT NOT NULL,    -- 'genre' | 'theme' | 'mechanic' | 'game_mode' | 'player_perspective'
    tag_id           INTEGER NOT NULL, -- numeric IGDB ID or canonical curated string (SQLite stores either)
    PRIMARY KEY (customer_game_id, tag_type, tag_id)
);

CREATE INDEX IF NOT EXISTS idx_customer_game_tags_type_id ON customer_game_tags(tag_type, tag_id);
CREATE INDEX IF NOT EXISTS idx_sessions_user       ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_reset_tokens_user   ON password_reset_tokens(user_id);

CREATE INDEX IF NOT EXISTS idx_metric_events_key_occurred ON metric_events(metric_key, occurred_at);
CREATE INDEX IF NOT EXISTS idx_metric_events_user_key_occurred ON metric_events(user_id, metric_key, occurred_at);

CREATE TABLE IF NOT EXISTS customer_game_search_cursors (
    customer_game_id TEXT NOT NULL,
    source     TEXT NOT NULL,
    cursors    TEXT NOT NULL DEFAULT '{}',  -- JSON dict: query_key -> cursor_value
    updated_at TEXT NOT NULL,
    PRIMARY KEY (customer_game_id, source),
    FOREIGN KEY (customer_game_id) REFERENCES customer_games(customer_game_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS prospect_statuses (
    customer_game_id TEXT NOT NULL REFERENCES customer_games(customer_game_id) ON DELETE CASCADE,
    account_id       TEXT NOT NULL REFERENCES source_accounts(account_id) ON DELETE CASCADE,
    status           TEXT NOT NULL DEFAULT 'new',
    notes            TEXT NOT NULL DEFAULT '',
    updated_at       TEXT NOT NULL,
    PRIMARY KEY (customer_game_id, account_id)
);

CREATE INDEX IF NOT EXISTS idx_prospect_statuses_game_status
    ON prospect_statuses(customer_game_id, status);

CREATE TABLE IF NOT EXISTS source_accounts (
    account_id            TEXT PRIMARY KEY,
    platform              TEXT NOT NULL,
    external_id           TEXT NOT NULL,
    handle_current        TEXT,
    display_name_current  TEXT,
    canonical_url         TEXT,
    account_type          TEXT NOT NULL DEFAULT 'creator',
    status                TEXT NOT NULL DEFAULT 'active',
    first_seen_at         TEXT NOT NULL,
    last_seen_at          TEXT NOT NULL,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    UNIQUE(platform, external_id)
);

CREATE TABLE IF NOT EXISTS twitch_profiles_latest (
    account_id        TEXT PRIMARY KEY REFERENCES source_accounts(account_id) ON DELETE CASCADE,
    broadcaster_id    TEXT NOT NULL,
    login             TEXT NOT NULL,
    display_name      TEXT NOT NULL,
    description       TEXT,
    followers_count   INTEGER,
    viewer_count      INTEGER,
    recent_avg_live_viewers    INTEGER,
    recent_median_live_viewers INTEGER,
    recent_avg_vod_views       INTEGER,
    recent_median_vod_views    INTEGER,
    streams_last_30d           INTEGER,
    language          TEXT,
    avatar_url        TEXT,
    last_live_at      TEXT,
    fetched_at        TEXT NOT NULL,
    expires_at        TEXT NOT NULL,
    clip_cursor       TEXT,              -- Twitch pagination cursor for next clip page (NULL = start from beginning)
    clips_exhausted   INTEGER NOT NULL DEFAULT 0  -- 1 when all clip pages have been fetched
);

CREATE TABLE IF NOT EXISTS youtube_channels_latest (
    account_id            TEXT PRIMARY KEY REFERENCES source_accounts(account_id) ON DELETE CASCADE,
    channel_id            TEXT NOT NULL,
    handle                TEXT,
    display_name          TEXT NOT NULL,
    description           TEXT,
    subscriber_count      INTEGER,
    video_count           INTEGER,
    recent_avg_views      INTEGER,
    recent_median_views   INTEGER,
    uploads_last_30d      INTEGER,
    default_language      TEXT,
    country               TEXT,
    channel_created_at    TEXT,
    avatar_url            TEXT,
    uploads_playlist_id   TEXT,
    last_upload_at        TEXT,
    fetched_at            TEXT NOT NULL,
    expires_at            TEXT NOT NULL,
    raw_payload_json      TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS content_samples_latest (
    sample_id             TEXT PRIMARY KEY,
    account_id            TEXT NOT NULL REFERENCES source_accounts(account_id) ON DELETE CASCADE,
    platform              TEXT NOT NULL,
    external_content_id   TEXT NOT NULL,
    content_type          TEXT NOT NULL,
    title_or_text         TEXT NOT NULL,
    body_text             TEXT,
    url                   TEXT,
    thumbnail_url         TEXT,
    published_at          TEXT,
    engagement_count      INTEGER,
    language              TEXT,
    position_rank         INTEGER NOT NULL DEFAULT 0,
    fetched_at            TEXT NOT NULL,
    expires_at            TEXT NOT NULL,
    raw_payload_json      TEXT NOT NULL DEFAULT '{}',
    UNIQUE(account_id, external_content_id)
);

CREATE TABLE IF NOT EXISTS contact_points (
    contact_point_id  TEXT PRIMARY KEY,
    account_id        TEXT NOT NULL REFERENCES source_accounts(account_id) ON DELETE CASCADE,
    contact_type      TEXT NOT NULL,
    contact_value     TEXT NOT NULL,
    source_kind       TEXT NOT NULL,
    source_url        TEXT,
    is_public         INTEGER NOT NULL DEFAULT 1,
    first_seen_at     TEXT NOT NULL,
    last_seen_at      TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    UNIQUE(account_id, contact_type, contact_value)
);

CREATE TABLE IF NOT EXISTS creator_profile_facets_latest (
    account_id         TEXT PRIMARY KEY REFERENCES source_accounts(account_id) ON DELETE CASCADE,
    platform           TEXT NOT NULL,
    summary_text       TEXT NOT NULL,
    genre_tags_json    TEXT NOT NULL DEFAULT '[]',
    interest_tags_json TEXT NOT NULL DEFAULT '[]',
    language           TEXT,                        -- BCP-47 code e.g. "en", "de"
    last_activity_at   TEXT,
    fetched_at         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS creator_games_played (
    account_id        TEXT NOT NULL REFERENCES source_accounts(account_id) ON DELETE CASCADE,
    game_name_raw     TEXT NOT NULL,
    game_name_key     TEXT NOT NULL,               -- lowercased for deduplication
    platform          TEXT NOT NULL,
    first_seen_at     TEXT NOT NULL,
    last_seen_at      TEXT NOT NULL,
    observation_count INTEGER NOT NULL DEFAULT 1,
    igdb_game_id      INTEGER REFERENCES igdb_games(igdb_id),
    PRIMARY KEY (account_id, game_name_key)
);

CREATE TABLE IF NOT EXISTS account_metric_samples (
    sample_id      TEXT PRIMARY KEY,
    account_id     TEXT NOT NULL REFERENCES source_accounts(account_id) ON DELETE CASCADE,
    platform       TEXT NOT NULL,
    metric_key     TEXT NOT NULL,
    metric_value   REAL NOT NULL,
    observed_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS crawl_jobs (
    job_id         TEXT PRIMARY KEY,
    platform       TEXT NOT NULL,
    job_type       TEXT NOT NULL,
    seed_key       TEXT NOT NULL,
    status         TEXT NOT NULL,
    attempt        INTEGER NOT NULL DEFAULT 1,
    started_at     TEXT NOT NULL,
    finished_at    TEXT,
    error_message  TEXT,
    args_json      TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS crawl_cursors (
    platform      TEXT NOT NULL,
    cursor_scope  TEXT NOT NULL,
    cursor_key    TEXT NOT NULL,
    cursor_value  TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    PRIMARY KEY (platform, cursor_scope, cursor_key)
);

CREATE TABLE IF NOT EXISTS crawl_seeds (
    seed_id         TEXT PRIMARY KEY,
    platform        TEXT NOT NULL,
    query_text      TEXT NOT NULL,
    seed_kind       TEXT NOT NULL DEFAULT 'bootstrap',
    status          TEXT NOT NULL DEFAULT 'active',
    weight          REAL NOT NULL DEFAULT 1.0,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    last_synced_at  TEXT,
    UNIQUE(platform, query_text)
);

CREATE INDEX IF NOT EXISTS idx_source_accounts_platform ON source_accounts(platform);
CREATE INDEX IF NOT EXISTS idx_source_accounts_last_seen ON source_accounts(platform, last_seen_at);
CREATE INDEX IF NOT EXISTS idx_twitch_profiles_expires ON twitch_profiles_latest(expires_at);
CREATE INDEX IF NOT EXISTS idx_youtube_channels_expires ON youtube_channels_latest(expires_at);
CREATE INDEX IF NOT EXISTS idx_content_samples_account_platform ON content_samples_latest(account_id, platform, position_rank);
CREATE INDEX IF NOT EXISTS idx_contact_points_account ON contact_points(account_id);
CREATE INDEX IF NOT EXISTS idx_creator_profile_facets_last_activity ON creator_profile_facets_latest(platform, last_activity_at);
CREATE INDEX IF NOT EXISTS idx_creator_games_played_account ON creator_games_played(account_id);
CREATE INDEX IF NOT EXISTS idx_creator_games_played_game_key ON creator_games_played(game_name_key);
CREATE INDEX IF NOT EXISTS idx_creator_games_played_igdb ON creator_games_played(igdb_game_id) WHERE igdb_game_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_creator_games_played_igdb_account ON creator_games_played(igdb_game_id, account_id) WHERE igdb_game_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_account_metric_samples_lookup ON account_metric_samples(account_id, platform, metric_key, observed_at);
CREATE INDEX IF NOT EXISTS idx_crawl_jobs_platform_started ON crawl_jobs(platform, started_at);
CREATE INDEX IF NOT EXISTS idx_crawl_cursors_scope_updated ON crawl_cursors(platform, cursor_scope, updated_at);
CREATE INDEX IF NOT EXISTS idx_crawl_seeds_platform_status_weight ON crawl_seeds(platform, status, weight);

-- ─── IGDB Game Catalog ────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS twitch_categories (
    twitch_category_id  TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    box_art_url         TEXT,
    igdb_game_id        INTEGER UNIQUE REFERENCES igdb_games(igdb_id) ON DELETE SET NULL,
    last_synced_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_twitch_categories_name_lower ON twitch_categories(LOWER(name));
CREATE INDEX IF NOT EXISTS idx_twitch_categories_igdb ON twitch_categories(igdb_game_id) WHERE igdb_game_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS igdb_games (
    igdb_id             INTEGER PRIMARY KEY,
    name                TEXT NOT NULL,
    slug                TEXT NOT NULL UNIQUE,
    summary             TEXT,
    first_release_date  INTEGER,
    cover_url           TEXT,
    developer_names_json TEXT NOT NULL DEFAULT '[]',
    platform_ids_json   TEXT NOT NULL DEFAULT '[]',
    platform_names_json TEXT NOT NULL DEFAULT '[]',
    last_synced_at      TEXT NOT NULL
);

-- tag_type: 'genre' | 'theme' | 'mechanic'
-- tag_name/tag_id: official IGDB taxonomy values or canonical curated concepts
CREATE TABLE IF NOT EXISTS igdb_game_tags (
    igdb_id     INTEGER NOT NULL REFERENCES igdb_games(igdb_id) ON DELETE CASCADE,
    tag_type    TEXT NOT NULL,
    tag_name    TEXT NOT NULL,
    tag_id      INTEGER NOT NULL,
    PRIMARY KEY (igdb_id, tag_type, tag_id)
);

CREATE INDEX IF NOT EXISTS idx_igdb_game_tags_type_id ON igdb_game_tags(tag_type, tag_id);
CREATE INDEX IF NOT EXISTS idx_igdb_game_tags_type_id_igdb ON igdb_game_tags(tag_type, tag_id, igdb_id);
CREATE INDEX IF NOT EXISTS idx_igdb_games_name_lower ON igdb_games(LOWER(name));

-- ─── Steam Enrichment For Cached IGDB Games ──────────────────────────────────

CREATE TABLE IF NOT EXISTS steam_game_sync_state (
    igdb_id            INTEGER PRIMARY KEY REFERENCES igdb_games(igdb_id) ON DELETE CASCADE,
    sync_status        TEXT NOT NULL,  -- pending | linked | no_match | error
    last_attempted_at  TEXT,
    last_succeeded_at  TEXT,
    updated_at         TEXT NOT NULL,
    last_error         TEXT
);

CREATE TABLE IF NOT EXISTS steam_game_links (
    igdb_id        INTEGER PRIMARY KEY REFERENCES igdb_games(igdb_id) ON DELETE CASCADE,
    steam_app_id   INTEGER NOT NULL UNIQUE,
    store_url      TEXT NOT NULL,
    match_method   TEXT NOT NULL,
    resolved_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS steam_game_tags (
    igdb_id          INTEGER NOT NULL REFERENCES igdb_games(igdb_id) ON DELETE CASCADE,
    steam_app_id     INTEGER NOT NULL,
    raw_tag          TEXT NOT NULL,
    normalized_tag   TEXT NOT NULL,
    tag_source       TEXT NOT NULL DEFAULT 'steam_store',
    fetched_at       TEXT NOT NULL,
    PRIMARY KEY (igdb_id, raw_tag)
);

CREATE TABLE IF NOT EXISTS steam_game_mapped_tags (
    igdb_id           INTEGER NOT NULL REFERENCES igdb_games(igdb_id) ON DELETE CASCADE,
    source_tag        TEXT NOT NULL,
    mapped_tag_type   TEXT NOT NULL,
    mapped_tag_id     TEXT NOT NULL,
    mapped_tag_name   TEXT NOT NULL,
    mapping_kind      TEXT NOT NULL,
    mapped_at         TEXT NOT NULL,
    PRIMARY KEY (igdb_id, source_tag, mapped_tag_type, mapped_tag_id)
);

CREATE INDEX IF NOT EXISTS idx_steam_game_sync_state_status_updated
    ON steam_game_sync_state(sync_status, updated_at);
CREATE INDEX IF NOT EXISTS idx_steam_game_tags_normalized
    ON steam_game_tags(normalized_tag);
CREATE INDEX IF NOT EXISTS idx_steam_game_mapped_tags_lookup
    ON steam_game_mapped_tags(mapped_tag_type, mapped_tag_id);

-- ─── Cross-Platform Identity Links ────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS identity_links (
    link_id         TEXT PRIMARY KEY,
    account_id_a    TEXT NOT NULL REFERENCES source_accounts(account_id) ON DELETE CASCADE,
    account_id_b    TEXT NOT NULL REFERENCES source_accounts(account_id) ON DELETE CASCADE,
    link_type       TEXT NOT NULL,
    evidence_json   TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(account_id_a, account_id_b)
);

CREATE INDEX IF NOT EXISTS idx_identity_links_account_a ON identity_links(account_id_a);
CREATE INDEX IF NOT EXISTS idx_identity_links_account_b ON identity_links(account_id_b);
