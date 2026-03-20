# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Spawnradar** — a FastAPI web app that helps indie game developers discover and reach out to content creators (YouTubers, Redditors) who match their game's audience profile. Key features: multi-game management, automated prospect discovery, LLM-powered scoring (Claude Haiku), draft outreach message generation, and Stripe billing.

## Commands

```bash
# Set up virtual environment and install dependencies
pip3 install -r requirements.txt -r dev-requirements.txt

# Start dev server (keeps DB, seeds dev data, auto-login enabled, hot reload)
make dev

# Run tests
.venv/bin/pytest

# Run a single test file
.venv/bin/pytest tests/test_scoring.py

# Lint
.venv/bin/ruff check app/

# Type-check
.venv/bin/basedpyright

# Combined repo checks
make check

# Reset DB only (without starting server)
make reset-db

# Deploy to Fly.io
make deploy
```

Tests have a 3-second timeout per test (configured in pyproject.toml).

## Architecture

**Layered**: Routes → Services → Repositories → SQLite. Services hold business logic; repositories handle all SQL. Everything is wired up via `app.state` in the FastAPI lifespan (`app/main.py`), not via dependency injection — routes access services through `request.app.state`.

**Domain modules** under `app/`:
- `auth/` — user registration, login, sessions, password reset
- `games/` — game CRUD, tags (audience/genre/platform stored as JSON), assets, message templates
- `prospects/` — discovered creators, draft outreach items, outcome tracking
- `billing/` — Stripe subscription management, tier enforcement (`free` / `starter` / `pro`)
- `ingestion/` — discovery pipeline: fetches candidates from YouTube API/scraping and Reddit, scores them, writes to DB
- `scoring/` — 7-dimension scoring algorithm (keyword match + optional LLM override via Claude Haiku)
- `scheduler/` — APScheduler background jobs that trigger ingestion on per-game schedules
- `email/` — Resend (primary) / SMTP (fallback) outreach sending
- `devtools/` — CLI (`sp` entry point) and dev seed scripts

**Database**: SQLite at `data/spawnradar.sqlite3` (WAL mode). Schema lives in `sql/schema.sql`; applied via `app/database.py:initialize_database()`. Repositories receive the `db_path` string and open connections themselves per call.

**Templates**: Jinja2 templates in `frontend/templates/` organized by domain (`auth/`, `games/`, `queue/`, `billing/`, `marketing/`, `admin/`). Static assets in `frontend/static/`.

## Key Environment Variables

| Variable | Purpose |
|---|---|
| `DB_PATH` | SQLite path (default: `data/spawnradar.sqlite3`) |
| `DEV_AUTO_LOGIN` | Skip auth in dev (`1`/`true`) |
| `ANTHROPIC_API_KEY` | Claude Haiku for LLM scoring |
| `YOUTUBE_API_KEY` | YouTube Data API |
| `YOUTUBE_CACHE_DIR` | Cache API responses (default: `data/yt_cache`) |
| `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` / `STRIPE_STARTER_PRICE_ID` / `STRIPE_PRO_PRICE_ID` | Stripe billing |
| `RESEND_API_KEY` | Email delivery |
| `SECRET_KEY` | Session signing |
| `LOG_LEVEL` | Set to `DEBUG` to see per-channel scoring details |

All config is loaded via `app/config.py:Settings.from_env()`, which also reads `.env` files.

## Core Data Flow

1. A game is registered with audience/genre/platform tags
2. The scheduler triggers `ingestion/pipeline.py` per game on a configurable schedule
3. The pipeline fetches candidates from YouTube (API + scrape fallback) and Reddit
4. Each candidate is scored against the game profile via `scoring/engine.py` (keyword dimensions + optional Claude Haiku call)
5. High-scoring candidates become `draft_items` in the queue
6. The developer reviews the queue, approves/rejects, and sends outreach from generated draft messages
7. Actions are recorded as `outcomes`

## Frontend Style

- Color tokens live in `frontend/static/style.css` under `:root` — use these, don't add raw hex values
- Primary brand color: `--color-brand` (violet) for buttons, links, key emphasis
- Product UI uses white/muted slate surfaces (`--color-bg-surface`, `--color-bg-muted`)
- Dark `--color-hero-*` palette is for major marketing sections only
- Shared component styles go in `style.css`; avoid one-off inline colors or page-specific variants

## Agent Workflow

- Run `.venv/bin/basedpyright` before finalizing Python changes
- For broad changes, prefer `make check`
- Fix typing issues at the source instead of papering over them with ignores
