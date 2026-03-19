"""FastAPI application entry point for Spawnradar."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.admin.router import router as admin_router
from app.auth.repository import (
    PasswordResetTokenRepository,
    SessionRepository,
    UserRepository,
)
from app.auth.router import router as auth_router
from app.auth.service import AuthService
from app.billing.models import PUBLIC_TIERS, TIER_LIMITS, TIER_PRICES
from app.billing.repository import SubscriptionRepository
from app.billing.router import router as billing_router
from app.billing.service import BillingService
from app.config import Settings
from app.database import initialize_database
from app.email.service import EmailService
from app.games.repository import (
    AssetRepository,
    GameRepository,
    MessageTemplateRepository,
)
from app.games.router import router as games_router
from app.games.service import GameService
from app.prospects.repository import (
    DraftItemRepository,
    OutcomeRepository,
    ProspectRepository,
)
from app.prospects.router import router as prospects_router
from app.prospects.service import ProspectService
from app.routes.health import router as health_router
from app.scheduler.setup import create_scheduler

# Configure logging for our app modules.
# Set LOG_LEVEL=DEBUG in .env to see per-channel scoring details.
# Defaults to INFO so key milestones always show up in the terminal.
_log_level = getattr(
    logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO
)
logging.basicConfig(
    level=logging.WARNING,  # suppress noisy third-party libs
    format="%(levelname)s  %(name)s  %(message)s",
)
logging.getLogger("app").setLevel(_log_level)

_APP_DIR = Path(__file__).resolve().parent
_SERVICE_DIR = _APP_DIR.parent
_FRONTEND_DIR = _SERVICE_DIR / "frontend"
_TEMPLATES_DIR = _FRONTEND_DIR / "templates"
_STATIC_DIR = _FRONTEND_DIR / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the database and wire up application services on startup."""
    settings: Settings = app.state.settings
    initialize_database(settings.db_path)

    db_path = settings.db_path

    # Repositories
    user_repo = UserRepository(db_path)
    session_repo = SessionRepository(db_path)
    reset_token_repo = PasswordResetTokenRepository(db_path)
    game_repo = GameRepository(db_path)
    asset_repo = AssetRepository(db_path)
    template_repo = MessageTemplateRepository(db_path)
    sub_repo = SubscriptionRepository(db_path)
    draft_repo = DraftItemRepository(db_path)
    outcome_repo = OutcomeRepository(db_path)
    prospect_repo = ProspectRepository(db_path)

    # Services
    email_service = EmailService(
        resend_api_key=settings.resend_api_key,
        smtp_host=settings.smtp_host,
        smtp_port=settings.smtp_port,
        smtp_user=settings.smtp_user,
        smtp_password=settings.smtp_password,
        from_address=settings.email_from,
    )
    auth_service = AuthService(user_repo, session_repo, reset_token_repo)
    game_service = GameService(game_repo, asset_repo, template_repo)
    billing_service = BillingService(
        sub_repo=sub_repo,
        game_repo=game_repo,
        stripe_secret_key=settings.stripe_secret_key,
        stripe_starter_price_id=settings.stripe_starter_price_id,
        stripe_pro_price_id=settings.stripe_pro_price_id,
        base_url=settings.base_url,
    )
    prospect_service = ProspectService(draft_repo, outcome_repo)

    # Jinja2 templates
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

    # Attach everything to app.state for dependency access in routes
    app.state.email_service = email_service
    app.state.auth_service = auth_service
    app.state.game_service = game_service
    app.state.billing_service = billing_service
    app.state.prospect_service = prospect_service
    app.state.game_repo = game_repo
    app.state.asset_repo = asset_repo
    app.state.template_repo = template_repo
    app.state.prospect_repo = prospect_repo
    app.state.templates = templates

    scheduler = create_scheduler(settings.db_path)
    scheduler.start()
    app.state.scheduler = scheduler

    try:
        yield
    finally:
        app.state.scheduler.shutdown()


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    settings = Settings.from_env()

    app = FastAPI(
        title="Spawnradar",
        description="Multi-game marketing prospecting for indie developers.",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = settings

    # Static files
    _STATIC_DIR.mkdir(parents=True, exist_ok=True)
    app.mount(
        "/static", StaticFiles(directory=str(_STATIC_DIR)), name="static"
    )

    # Routers
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(games_router)
    app.include_router(prospects_router)
    app.include_router(billing_router)
    app.include_router(admin_router)

    @app.get("/")
    async def root(request: Request):
        """Render the public landing page."""
        session_id = request.cookies.get("session_id")
        user = None
        if session_id:
            user = request.app.state.auth_service.get_user_for_session(
                session_id
            )
        return request.app.state.templates.TemplateResponse(
            request,
            "marketing/home.html",
            {"user": user},
        )

    @app.get("/pricing")
    async def pricing(request: Request):
        """Render the public pricing page."""
        session_id = request.cookies.get("session_id")
        user = None
        if session_id:
            user = request.app.state.auth_service.get_user_for_session(
                session_id
            )

        return request.app.state.templates.TemplateResponse(
            request,
            "billing/pricing.html",
            {
                "user": user,
                "stripe_enabled": request.app.state.billing_service.stripe_enabled,
                "tier_limits": TIER_LIMITS,
                "tier_prices": TIER_PRICES,
                "tiers": PUBLIC_TIERS,
            },
        )

    return app


app = create_app()
