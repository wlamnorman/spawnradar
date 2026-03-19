CREATE TABLE IF NOT EXISTS users (
    user_id       TEXT PRIMARY KEY,
    email         TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
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
    subscription_id         TEXT PRIMARY KEY,
    user_id                 TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    stripe_customer_id      TEXT,
    stripe_subscription_id  TEXT,
    tier                    TEXT NOT NULL DEFAULT 'free',    -- free | starter | pro
    status                  TEXT NOT NULL DEFAULT 'active',  -- active | cancelled | past_due | trialing
    trial_ends_at           TEXT,                            -- NULL means no trial
    current_period_end      TEXT,
    created_at              TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at              TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS password_reset_tokens (
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
    description        TEXT NOT NULL,
    slug               TEXT UNIQUE,
    genre_tags         TEXT NOT NULL DEFAULT '[]',   -- JSON array
    audience_tags      TEXT NOT NULL DEFAULT '[]',   -- JSON array
    platform_tags      TEXT NOT NULL DEFAULT '[]',   -- JSON array
    website_url        TEXT,
    discovery_schedule TEXT NOT NULL DEFAULT 'manual', -- manual | daily | weekly
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
    platform        TEXT NOT NULL,   -- youtube | reddit
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
    suggested_action TEXT,
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

CREATE INDEX IF NOT EXISTS idx_games_user          ON games(user_id);
CREATE INDEX IF NOT EXISTS idx_games_schedule      ON games(discovery_schedule);
CREATE INDEX IF NOT EXISTS idx_draft_items_game    ON draft_items(game_id);
CREATE INDEX IF NOT EXISTS idx_draft_items_status  ON draft_items(status);
CREATE INDEX IF NOT EXISTS idx_prospects_platform  ON prospects(platform);
CREATE INDEX IF NOT EXISTS idx_sessions_user       ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_reset_tokens_user   ON password_reset_tokens(user_id);
