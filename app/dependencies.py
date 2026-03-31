"""Shared FastAPI dependencies for app.state-backed services and repos."""

from __future__ import annotations

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.auth.repository import (
    EmailVerificationTokenRepository,
    UserRepository,
)
from app.auth.service import AuthService
from app.billing.repository import SubscriptionRepository
from app.billing.service import BillingService
from app.config import Settings
from app.email.service import EmailService
from app.game_import.service import GameImportService
from app.games.repository import CustomerGameRepository
from app.games.service import CustomerGameService
from app.metrics.service import MetricsService


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


def get_auth_service(request: Request) -> AuthService:
    return request.app.state.auth_service


def get_email_service(request: Request) -> EmailService:
    return request.app.state.email_service


def get_customer_game_service(request: Request) -> CustomerGameService:
    return request.app.state.customer_game_service


def get_game_import_service(request: Request) -> GameImportService:
    return request.app.state.game_import_service


def get_billing_service(request: Request) -> BillingService:
    return request.app.state.billing_service


def get_metrics_service(request: Request) -> MetricsService:
    return request.app.state.metrics_service


def get_customer_game_repo(request: Request) -> CustomerGameRepository:
    return request.app.state.customer_game_repo


def get_user_repo(request: Request) -> UserRepository:
    return request.app.state.user_repo


def get_subscription_repo(request: Request) -> SubscriptionRepository:
    return request.app.state.subscription_repo


def get_email_verification_token_repo(
    request: Request,
) -> EmailVerificationTokenRepository:
    return request.app.state.email_verification_token_repo
