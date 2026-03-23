CREATE TABLE IF NOT EXISTS users (
    user_id       TEXT PRIMARY KEY,
    email         TEXT UNIQUE NOT NULL,
    password_hash TEXT,                        -- NULL for Google-only accounts
    google_id     TEXT UNIQUE,                 -- NULL for password-only accounts
    is_admin      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id  TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    expires_at  TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS subscriptions (
    subscription_id    TEXT PRIMARY KEY,
    user_id            TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    paddle_customer_id     TEXT,
    paddle_subscription_id TEXT,
    tier               TEXT NOT NULL DEFAULT 'indie',    -- indie
    status             TEXT NOT NULL DEFAULT 'active',  -- active | cancelled | past_due | trialing
    trial_ends_at      TEXT,                            -- NULL means no trial
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

CREATE TABLE IF NOT EXISTS games (
    game_id            TEXT PRIMARY KEY,
    user_id            TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    name               TEXT NOT NULL,
    summary            TEXT,                         -- 1-2 sentence elevator pitch
    description        TEXT NOT NULL,
    slug               TEXT UNIQUE,
    genre_tags         TEXT NOT NULL DEFAULT '[]',   -- JSON array
    genre_tag_profile    TEXT NOT NULL DEFAULT '{"primary":[],"secondary":[]}', -- JSON object
    mechanics_tag_profile TEXT NOT NULL DEFAULT '{"primary":[],"secondary":[]}', -- JSON object
    vibe_tag_profile     TEXT NOT NULL DEFAULT '{"primary":[],"secondary":[]}', -- JSON object
    kindred_tag_profile  TEXT NOT NULL DEFAULT '{"primary":[],"secondary":[]}', -- JSON object
    platform_tags        TEXT NOT NULL DEFAULT '[]',   -- JSON array
    website_url        TEXT,
    discovery_schedule TEXT NOT NULL DEFAULT 'manual',           -- manual | daily | weekly
    discovery_sources  TEXT NOT NULL DEFAULT '["youtube","reddit","bluesky","twitch"]', -- JSON array of source names
    status             TEXT NOT NULL DEFAULT 'active',
    created_at         TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS assets (
    asset_id    TEXT PRIMARY KEY,
    game_id     TEXT NOT NULL REFERENCES games(game_id) ON DELETE CASCADE,
    asset_type  TEXT NOT NULL,  -- screenshot | banner | logo | blurb
    title       TEXT NOT NULL,
    body        TEXT,
    url         TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS message_templates (
    template_id      TEXT PRIMARY KEY,
    game_id          TEXT NOT NULL REFERENCES games(game_id) ON DELETE CASCADE,
    name             TEXT NOT NULL,
    channel          TEXT NOT NULL,  -- email | youtube_dm | reddit_dm | twitter
    subject_template TEXT,
    body_template    TEXT NOT NULL,  -- supports {{creator_name}}, {{game_name}}, {{fit_reason}}
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS prospects (
    prospect_id     TEXT PRIMARY KEY,
    platform        TEXT NOT NULL,   -- youtube | reddit | bluesky | twitch
    handle          TEXT NOT NULL,
    display_name    TEXT NOT NULL,
    profile_url     TEXT,
    contact_channel TEXT,
    contact_value   TEXT,
    audience_size   INTEGER,
    engagement_rate REAL,
    description     TEXT,
    raw_data        TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(platform, handle)
);

CREATE TABLE IF NOT EXISTS draft_items (
    draft_item_id    TEXT PRIMARY KEY,
    game_id          TEXT NOT NULL REFERENCES games(game_id) ON DELETE CASCADE,
    prospect_id      TEXT NOT NULL REFERENCES prospects(prospect_id),
    template_id      TEXT REFERENCES message_templates(template_id),
    subject_line     TEXT,
    body_text        TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'queued',  -- queued | approved | rejected | snoozed | sent
    priority_score   REAL NOT NULL DEFAULT 0,
    fit_summary      TEXT,
    score_breakdown  TEXT NOT NULL DEFAULT '{}',
    last_edited_at   TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at       TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(game_id, prospect_id)
);

CREATE TABLE IF NOT EXISTS outcomes (
    outcome_id    TEXT PRIMARY KEY,
    draft_item_id TEXT NOT NULL REFERENCES draft_items(draft_item_id) ON DELETE CASCADE,
    outcome_type  TEXT NOT NULL,  -- approved | rejected | snoozed | sent
    notes         TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS discovery_runs (
    run_id      TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    game_id     TEXT NOT NULL REFERENCES games(game_id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS metric_events (
    event_id    TEXT PRIMARY KEY,
    metric_key  TEXT NOT NULL,
    user_id     TEXT REFERENCES users(user_id) ON DELETE SET NULL,
    game_id     TEXT REFERENCES games(game_id) ON DELETE SET NULL,
    occurred_at TEXT NOT NULL,
    value       REAL NOT NULL DEFAULT 1,
    dedupe_key  TEXT UNIQUE,
    metadata    TEXT NOT NULL DEFAULT '{}'
);

-- Durable analytics facts stay separate from discovery_runs because discovery_runs
-- is operational billing state tied to users/games with cascading deletes.
CREATE TABLE IF NOT EXISTS discovery_run_facts (
    run_id            TEXT PRIMARY KEY,
    user_id           TEXT NOT NULL,
    game_id           TEXT NOT NULL,
    started_at        TEXT NOT NULL,
    completed_at      TEXT,
    status            TEXT NOT NULL DEFAULT 'started',
    discovered_count  INTEGER NOT NULL DEFAULT 0,
    scored_count      INTEGER NOT NULL DEFAULT 0,
    queued_count      INTEGER NOT NULL DEFAULT 0,
    error_message     TEXT
);

-- Score observations intentionally avoid foreign keys so score distributions
-- survive queue/game cleanup and user/game deletions.
CREATE TABLE IF NOT EXISTS prospect_score_observations (
    observation_id TEXT PRIMARY KEY,
    run_id         TEXT NOT NULL,
    user_id        TEXT NOT NULL,
    game_id        TEXT NOT NULL,
    score          REAL NOT NULL,
    queued         INTEGER NOT NULL DEFAULT 0,
    occurred_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS creator_signups (
    creator_id        TEXT PRIMARY KEY,
    display_name      TEXT NOT NULL,
    email             TEXT UNIQUE NOT NULL,
    email_verified    INTEGER NOT NULL DEFAULT 0,
    youtube_handle    TEXT,
    twitch_handle     TEXT,
    tiktok_handle     TEXT,
    reddit_handle     TEXT,
    bluesky_handle    TEXT,
    genre_interests   TEXT NOT NULL DEFAULT '[]',   -- JSON array of genre strings
    platform_pref     TEXT NOT NULL DEFAULT 'any',  -- pc | console | mobile | browser | any
    audience_size     TEXT,  -- "under_5k" | "5k_20k" | "20k_100k" | "100k_plus"
    accepts_keys      TEXT NOT NULL DEFAULT 'yes',  -- yes | sometimes | no
    preferred_contact TEXT NOT NULL DEFAULT 'email', -- email | youtube_dm | twitch_dm | reddit_dm | twitter_dm
    lead_time_pref    TEXT,  -- "1_week" | "2_3_weeks" | "1_month" | "no_pref"
    -- Survey responses
    pitch_first_check TEXT,   -- what do you look at first in a pitch?
    pitch_delete_why  TEXT,   -- what makes you delete immediately?
    pitch_open_to     TEXT NOT NULL DEFAULT '[]',  -- JSON array of factors
    contact_timing    TEXT,   -- before | after | either | no_pref
    creator_notes     TEXT,   -- anything else for developers to know
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_creator_signups_email ON creator_signups(email);

CREATE TABLE IF NOT EXISTS request_rate_limits (
    event_id    TEXT PRIMARY KEY,
    scope       TEXT NOT NULL,
    key_hash    TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_request_rate_limits_scope_key_created
    ON request_rate_limits(scope, key_hash, created_at);

CREATE INDEX IF NOT EXISTS idx_games_user          ON games(user_id);
CREATE INDEX IF NOT EXISTS idx_games_schedule      ON games(discovery_schedule);
CREATE INDEX IF NOT EXISTS idx_draft_items_game    ON draft_items(game_id);
CREATE INDEX IF NOT EXISTS idx_draft_items_status  ON draft_items(status);
CREATE INDEX IF NOT EXISTS idx_prospects_platform  ON prospects(platform);
CREATE INDEX IF NOT EXISTS idx_sessions_user       ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_reset_tokens_user   ON password_reset_tokens(user_id);

CREATE INDEX IF NOT EXISTS idx_discovery_runs_user_created ON discovery_runs(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_metric_events_key_occurred ON metric_events(metric_key, occurred_at);
CREATE INDEX IF NOT EXISTS idx_metric_events_user_key_occurred ON metric_events(user_id, metric_key, occurred_at);
CREATE INDEX IF NOT EXISTS idx_discovery_run_facts_status_started ON discovery_run_facts(status, started_at);
CREATE INDEX IF NOT EXISTS idx_discovery_run_facts_user_started ON discovery_run_facts(user_id, started_at);
CREATE INDEX IF NOT EXISTS idx_prospect_score_observations_occurred ON prospect_score_observations(occurred_at);
CREATE INDEX IF NOT EXISTS idx_prospect_score_observations_queued ON prospect_score_observations(queued, occurred_at);

CREATE TABLE IF NOT EXISTS game_search_cursors (
    game_id    TEXT NOT NULL,
    source     TEXT NOT NULL,
    cursors    TEXT NOT NULL DEFAULT '{}',  -- JSON dict: query_key -> cursor_value
    updated_at TEXT NOT NULL,
    PRIMARY KEY (game_id, source),
    FOREIGN KEY (game_id) REFERENCES games(game_id) ON DELETE CASCADE
);
