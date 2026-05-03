"""Account and subscription management commands for the developer CLI."""

from __future__ import annotations

from datetime import UTC, datetime

from app.auth.repository import (
    PasswordResetTokenRepository,
    SessionRepository,
    UserRepository,
    WorkspaceRepository,
)
from app.auth.service import AuthService
from app.billing.repository import SubscriptionRepository
from app.billing.service import BillingService
from app.config import Settings
from app.database import get_connection, initialize_database
from app.devtools.bootstrap import DEV_EMAIL, DEV_PASSWORD, ensure_dev_user
from app.devtools.utils import CommandResult
from app.email.service import EmailService
from app.games.repository import CustomerGameRepository


def run_free_account(db_path: str) -> CommandResult:
    """Reset the dev account to a free user with no subscription."""
    initialize_database(db_path)
    user = ensure_dev_user(db_path)
    sub_repo = SubscriptionRepository(db_path)
    sub_repo.delete_by_user(user.user_id)
    return CommandResult(
        message=f"Free account ready for {DEV_EMAIL} (password: {DEV_PASSWORD}). No subscription.",
    )


def run_activate_sub(db_path: str) -> CommandResult:
    """Give the dev account a fake active paid subscription."""
    initialize_database(db_path)
    user = ensure_dev_user(db_path)
    sub_repo = SubscriptionRepository(db_path)
    existing = sub_repo.get_by_user(user.user_id)
    if existing is None:
        import uuid

        from app.billing.models import Tier

        sub_repo.create(str(uuid.uuid4()), user.user_id, Tier.INDIE)
    sub_repo.update_from_paddle(
        user.user_id,
        paddle_customer_id="dev_customer",
        paddle_subscription_id="dev_subscription",
        status="active",
    )
    return CommandResult(
        message=f"Subscription activated for {DEV_EMAIL}.",
        created=True,
    )


def run_expire_sub(db_path: str) -> CommandResult:
    """Cancel the dev account's subscription so it appears lapsed."""
    initialize_database(db_path)
    user = ensure_dev_user(db_path)
    sub_repo = SubscriptionRepository(db_path)
    existing = sub_repo.get_by_user(user.user_id)
    if existing is None:
        return CommandResult(
            message=f"No subscription found for {DEV_EMAIL}.",
        )
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE subscriptions SET status = 'canceled', "
            "updated_at = ? WHERE user_id = ?",
            (datetime.now(UTC).isoformat(), user.user_id),
        )
    return CommandResult(
        message=f"Subscription canceled for {DEV_EMAIL}.",
    )


def run_grant_comp(
    db_path: str,
    emails: list[str],
    *,
    create_missing: bool = False,
    send_reset: bool = False,
) -> CommandResult:
    """Grant complimentary access to users by email."""
    initialize_database(db_path)
    settings = Settings.from_env()
    user_repo = UserRepository(db_path)
    auth = AuthService(
        user_repo,
        session_repo=None,  # type: ignore[arg-type]
        reset_token_repo=PasswordResetTokenRepository(db_path),
        workspace_repo=WorkspaceRepository(db_path),
    )
    billing = BillingService(
        SubscriptionRepository(db_path),
        CustomerGameRepository(db_path),
    )
    email_service = EmailService(
        resend_api_key=settings.resend_api_key,
        from_address=settings.email_from,
    )

    granted: list[str] = []
    created_users: list[str] = []
    reset_sent: list[str] = []
    missing: list[str] = []

    for email in emails:
        user = user_repo.get_by_email(email)
        if user is None and create_missing:
            user = auth.create_email_only_user(email)
            created_users.append(user.email)

        if user is None:
            missing.append(email)
            continue

        billing.grant_comped_access(user.user_id)
        granted.append(user.email)

        if send_reset and email_service.is_configured:
            auth.request_password_reset(
                user.email, email_service, settings.base_url
            )
            reset_sent.append(user.email)

    parts: list[str] = []
    if granted:
        parts.append(f"Granted complimentary access to: {', '.join(granted)}.")
    if created_users:
        parts.append(f"Created accounts for: {', '.join(created_users)}.")
    if send_reset:
        if reset_sent:
            parts.append(
                f"Sent password setup/reset email to: {', '.join(reset_sent)}."
            )
        elif not email_service.is_configured:
            parts.append(
                "Email is not configured, so no password setup emails were sent."
            )
    if missing:
        parts.append(f"No account found for: {', '.join(missing)}.")
    if not parts:
        parts.append("No changes made.")
    return CommandResult(
        message=" ".join(parts), created=bool(granted or created_users)
    )


def run_grant_admin(db_path: str, email: str = DEV_EMAIL) -> CommandResult:
    """Grant admin access to a user by email."""
    initialize_database(db_path)
    if email == DEV_EMAIL:
        ensure_dev_user(db_path)
    user_repo = UserRepository(db_path)
    user = user_repo.get_by_email(email)
    if user is None:
        return CommandResult(message=f"No account found for {email}.")
    if user.is_admin:
        return CommandResult(message=f"{email} is already an admin.")
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE users SET is_admin = 1 WHERE user_id = ?",
            (user.user_id,),
        )
    return CommandResult(message=f"Granted admin access to {email}.")


def run_mint_session(db_path: str, email: str) -> CommandResult:
    """Create and return a fresh session_id for an existing user."""
    initialize_database(db_path)
    user_repo = UserRepository(db_path)
    user = user_repo.get_by_email(email)
    if user is None:
        return CommandResult(message=f"No account found for {email}.")

    auth = AuthService(
        user_repo,
        session_repo=SessionRepository(db_path),
        reset_token_repo=PasswordResetTokenRepository(db_path),
        workspace_repo=WorkspaceRepository(db_path),
    )
    session = auth.create_session_for_user(user.user_id)
    return CommandResult(message=session.session_id, created=True)
