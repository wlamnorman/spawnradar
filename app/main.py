"""FastAPI application entry point for Spawnradar."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from functools import cache
from pathlib import Path

from authlib.integrations.starlette_client import OAuth
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from app.admin.router import router as admin_router
from app.auth.cookies import AnonymousSessionMiddleware
from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.auth.repository import (
    EmailVerificationTokenRepository,
    PasswordResetTokenRepository,
    SessionRepository,
    UserRepository,
)
from app.auth.router import router as auth_router
from app.auth.service import AuthService
from app.billing.models import (
    PUBLIC_TIERS,
    TIER_LIMITS,
    TIER_PRICES,
    Subscription,
)
from app.billing.repository import SubscriptionRepository
from app.billing.router import router as billing_router
from app.billing.service import BillingService
from app.config import Settings
from app.database import initialize_database
from app.dependencies import get_billing_service, get_templates
from app.email.service import EmailService
from app.game_import.service import GameImportService
from app.games.repository import CustomerGameRepository
from app.games.router import router as games_router
from app.games.service import CustomerGameService
from app.metrics.repository import MetricsRepository
from app.metrics.router import router as metrics_router
from app.metrics.service import MetricsService
from app.prospects.router import router as prospects_router
from app.routes.blog import router as blog_router
from app.routes.favicon import router as favicon_router
from app.routes.health import router as health_router
from app.routes.legal import router as legal_router
from app.routes.seo import router as seo_router
from app.runtime import SourceRuntime
from app.scheduler.setup import create_scheduler, schedule_game_discovery
from app.security import csrf_token_for

# Configure logging for our app modules.
logging.basicConfig(
    level=logging.WARNING,  # suppress noisy third-party libs
    format="%(levelname)s  %(name)s  %(message)s",
)

_APP_DIR = Path(__file__).resolve().parent
_FRONTEND_DIR = _APP_DIR / "frontend"
_TEMPLATES_DIR = _FRONTEND_DIR / "templates"
_STATIC_DIR = _FRONTEND_DIR / "static"
logger = logging.getLogger(__name__)


@cache
def _static_asset_version(path: str) -> int | None:
    """Return a stable cache-busting token for a static asset."""
    asset_path = _STATIC_DIR / path
    try:
        return asset_path.stat().st_mtime_ns
    except FileNotFoundError:
        return None


def static_asset_url(path: str) -> str:
    """Return a versioned static URL so deploys invalidate stale browser caches."""
    version = _static_asset_version(path)
    if version is None:
        return f"/static/{path}"
    return f"/static/{path}?v={version}"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the database and wire up application services on startup."""
    settings: Settings = app.state.settings
    initialize_database(settings.db_path)

    db_path = settings.db_path
    source_runtime = SourceRuntime(
        youtube_api_key=settings.youtube_api_key,
        youtube_cache_dir=settings.youtube_cache_dir,
        twitch_client_id=settings.twitch_client_id,
        twitch_client_secret=settings.twitch_client_secret,
    )

    # Repositories
    user_repo = UserRepository(db_path)
    session_repo = SessionRepository(db_path)
    reset_token_repo = PasswordResetTokenRepository(db_path)
    email_verification_token_repo = EmailVerificationTokenRepository(db_path)
    customer_game_repo = CustomerGameRepository(db_path)
    sub_repo = SubscriptionRepository(db_path)
    metrics_repo = MetricsRepository(db_path)

    # Services
    email_service = EmailService(
        resend_api_key=settings.resend_api_key,
        from_address=settings.email_from,
    )
    metrics_service = MetricsService(metrics_repo, sub_repo)
    auth_service = AuthService(
        user_repo,
        session_repo,
        reset_token_repo,
        email_verification_token_repo,
        metrics_service=metrics_service,
    )
    # CustomerGameService gets wired with on_game_changed callback below
    # after the scheduler is created.
    customer_game_service = CustomerGameService(
        customer_game_repo,
        metrics_service=metrics_service,
    )
    game_import_service = GameImportService()
    billing_service = BillingService(
        sub_repo=sub_repo,
        customer_game_repo=customer_game_repo,
        metrics_service=metrics_service,
        paddle_api_key=settings.paddle_api_key,
        paddle_client_side_token=settings.paddle_client_side_token,
        paddle_indie_price_id=settings.paddle_indie_price_id,
        paddle_environment=settings.paddle_environment,
        base_url=settings.base_url,
    )
    scheduler = None
    if settings.scheduler_enabled:
        scope_message = (
            ", ".join(settings.creator_index_game_names)
            if settings.creator_index_game_names
            else "all active games"
        )
        logger.info(
            "Starting creator-index scheduler with games=%s",
            scope_message,
        )
        catalog_dir = str(Path(__file__).resolve().parent / "catalog")
        scheduler = create_scheduler(
            db_path,
            source_runtime,
            catalog_dir=catalog_dir,
        )
        scheduler.start()

        # Wire on-demand discovery: when a game is created/updated,
        # schedule a one-shot discovery job.
        def _on_game_changed(customer_game_id: str) -> None:
            schedule_game_discovery(
                scheduler,
                db_path,
                source_runtime,
                customer_game_id,
            )

        customer_game_service.set_on_game_changed(_on_game_changed)

    def subscription_for(request: Request) -> Subscription | None:
        """Return the current user's subscription for use in base templates."""
        session_id = request.cookies.get("session_id")
        if not session_id:
            return None
        user = request.app.state.auth_service.get_user_for_session(session_id)
        if user is None:
            return None
        return request.app.state.billing_service.get_subscription(
            user.user_id
        )

    # Jinja2 templates
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    templates.env.globals["csrf_token_for"] = csrf_token_for
    templates.env.globals["subscription_for"] = subscription_for
    templates.env.globals["static_asset_url"] = static_asset_url

    # Attach everything to app.state for dependency access in routes
    app.state.email_service = email_service
    app.state.auth_service = auth_service
    app.state.email_verification_token_repo = email_verification_token_repo
    app.state.customer_game_service = customer_game_service
    app.state.game_import_service = game_import_service
    app.state.billing_service = billing_service
    app.state.metrics_service = metrics_service
    app.state.user_repo = user_repo
    app.state.session_repo = session_repo
    app.state.subscription_repo = sub_repo
    app.state.customer_game_repo = customer_game_repo
    app.state.templates = templates
    app.state.scheduler = scheduler

    yield

    if scheduler is not None and scheduler.running:
        scheduler.shutdown(wait=False)


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
    logging.getLogger("app").setLevel(
        getattr(logging, settings.log_level, logging.INFO)
    )

    # Fly already handles public HTTP->HTTPS redirects at the edge via
    # `force_https = true` in fly.toml. Avoid app-level HTTPS redirects here so
    # internal Fly health checks and metrics scrapes can stay on plain HTTP.
    secure_transport = settings.uses_https

    # SessionMiddleware is required by authlib to store OAuth state between
    # the redirect and callback. It's separate from our own session cookie.
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        same_site="lax",
        https_only=secure_transport,
    )
    app.add_middleware(AnonymousSessionMiddleware, settings=settings)

    # Google OAuth client (no-op if credentials are not configured)
    oauth = OAuth()
    if settings.google_client_id and settings.google_client_secret:
        oauth.register(
            name="google",
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
        )
    app.state.oauth = oauth

    # Static files
    _STATIC_DIR.mkdir(parents=True, exist_ok=True)
    app.mount(
        "/static", StaticFiles(directory=str(_STATIC_DIR)), name="static"
    )

    async def not_found_handler(request: Request, exc: Exception):
        """Render a branded 404 page for browser requests."""
        accept = request.headers.get("accept", "")
        detail = "Not Found"
        if isinstance(exc, StarletteHTTPException) and isinstance(
            exc.detail, str
        ):
            detail = exc.detail

        if "text/html" not in accept:
            return JSONResponse(status_code=404, content={"detail": detail})

        user = None
        session_id = request.cookies.get("session_id")
        if session_id:
            user = request.app.state.auth_service.get_user_for_session(
                session_id
            )

        return request.app.state.templates.TemplateResponse(
            request,
            "errors/404.html",
            {"user": user},
            status_code=404,
        )

    app.add_exception_handler(404, not_found_handler)

    # Routers
    app.include_router(health_router)
    app.include_router(metrics_router)
    app.include_router(seo_router)
    app.include_router(legal_router)
    app.include_router(favicon_router)
    app.include_router(blog_router)
    app.include_router(auth_router)
    app.include_router(games_router)
    app.include_router(prospects_router)
    app.include_router(billing_router)
    app.include_router(admin_router)

    @app.get("/")
    async def root(
        request: Request,
        user: User | None = Depends(get_current_user),
        templates: Jinja2Templates = Depends(get_templates),
    ):
        """Render the public landing page."""
        return templates.TemplateResponse(
            request,
            "marketing/home.html",
            {"user": user},
        )

    @app.get("/pricing")
    async def pricing(
        request: Request,
        user: User | None = Depends(get_current_user),
        templates: Jinja2Templates = Depends(get_templates),
        billing_service: BillingService = Depends(get_billing_service),
    ):
        """Render the public pricing page."""
        return templates.TemplateResponse(
            request,
            "billing/pricing.html",
            {
                "user": user,
                "billing_enabled": billing_service.checkout_enabled,
                "tier_limits": TIER_LIMITS,
                "tier_prices": TIER_PRICES,
                "tiers": PUBLIC_TIERS,
            },
        )

    return app


app = create_app()
