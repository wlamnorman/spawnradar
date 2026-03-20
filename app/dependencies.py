"""Shared FastAPI dependencies for app.state-backed services and repos."""

from __future__ import annotations

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.auth.repository import UserRepository
from app.auth.service import AuthService
from app.billing.repository import SubscriptionRepository
from app.billing.service import BillingService
from app.config import Settings
from app.email.service import EmailService
from app.games.repository import (
    AssetRepository,
    GameRepository,
    MessageTemplateRepository,
)
from app.games.service import GameService
from app.prospects.repository import DraftItemRepository, ProspectRepository
from app.prospects.service import ProspectService


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


def get_auth_service(request: Request) -> AuthService:
    return request.app.state.auth_service


def get_email_service(request: Request) -> EmailService:
    return request.app.state.email_service


def get_game_service(request: Request) -> GameService:
    return request.app.state.game_service


def get_billing_service(request: Request) -> BillingService:
    return request.app.state.billing_service


def get_prospect_service(request: Request) -> ProspectService:
    return request.app.state.prospect_service


def get_game_repo(request: Request) -> GameRepository:
    return request.app.state.game_repo


def get_asset_repo(request: Request) -> AssetRepository:
    return request.app.state.asset_repo


def get_template_repo(request: Request) -> MessageTemplateRepository:
    return request.app.state.template_repo


def get_prospect_repo(request: Request) -> ProspectRepository:
    return request.app.state.prospect_repo


def get_draft_repo(request: Request) -> DraftItemRepository:
    return request.app.state.draft_repo


def get_user_repo(request: Request) -> UserRepository:
    return request.app.state.user_repo


def get_subscription_repo(request: Request) -> SubscriptionRepository:
    return request.app.state.subscription_repo
