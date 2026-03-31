"""Tests for subscription management and tier limit enforcement."""

import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.billing.models import (
    FREE_LIMITS,
    TIER_LIMITS,
    Subscription,
    Tier,
)
from app.billing.service import BillingService


def _paddle_event(
    event_type: str,
    price_id: str,
    customer_id: str,
    sub_id: str,
    status: str = "active",
    user_id: str | None = None,
):
    custom_data = {"user_id": user_id} if user_id else {}
    return {
        "event_id": "evt_123",
        "event_type": event_type,
        "occurred_at": "2026-06-01T00:00:00Z",
        "notification_id": "ntf_123",
        "data": {
            "id": sub_id,
            "customer_id": customer_id,
            "status": status,
            "items": [{"price": {"id": price_id}}],
            "current_billing_period": {
                "starts_at": "2026-05-01T00:00:00Z",
                "ends_at": "2026-06-01T00:00:00Z",
            },
            "custom_data": custom_data,
        },
    }


def test_get_subscription_returns_none_for_new_user(
    billing_service, registered_user
):
    sub = billing_service.get_subscription(registered_user.user_id)
    assert sub is None


def test_get_subscription_returns_existing_sub(
    billing_service, registered_user, sub_repo
):

    sub_repo.create(str(uuid.uuid4()), registered_user.user_id, Tier.INDIE)
    sub = billing_service.get_subscription(registered_user.user_id)
    assert isinstance(sub, Subscription)
    assert sub.user_id == registered_user.user_id
    assert sub.tier == Tier.INDIE
    assert sub.status == "active"


def test_check_game_limit_returns_true_when_under_limit(
    billing_service, registered_user
):
    assert billing_service.check_game_limit(registered_user.user_id) is True


def test_check_game_limit_returns_false_when_at_limit(
    billing_service, game_service, registered_user
):
    game_service.create_game(
        user_id=registered_user.user_id,
        name="Game 0",
        summary="Short summary",
        description="desc",
        website_url=None,
        igdb_genre_ids=[9],  # Puzzle
    )
    assert billing_service.check_game_limit(registered_user.user_id) is False


def test_indie_tier_game_limit_is_three():
    assert TIER_LIMITS[Tier.INDIE]["games"] == 3


def _make_sub(
    *,
    paddle_subscription_id=None,
    user_id="u1",
    status="active",
):
    now = datetime.now(UTC).isoformat()
    return Subscription(
        subscription_id="sub_test",
        user_id=user_id,
        paddle_customer_id=None,
        paddle_subscription_id=paddle_subscription_id,
        tier=Tier.INDIE,
        status=status,
        current_period_end=None,
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# has_subscription — single source of truth for "has a paid Paddle sub"
# ---------------------------------------------------------------------------


def test_has_subscription_false_when_no_paddle_id():
    sub = _make_sub(paddle_subscription_id=None)
    assert sub.has_subscription is False


def test_has_subscription_true_when_paddle_id_is_set():
    sub = _make_sub(paddle_subscription_id="sub_paid")
    assert sub.has_subscription is True


def test_has_access_false_without_subscription():
    sub = _make_sub()
    assert sub.has_access is False


def test_has_access_true_for_active_paid_subscription_without_period_end():
    sub = _make_sub(paddle_subscription_id="sub_paid", status="active")
    assert sub.has_access is True


def test_has_access_false_for_past_due_subscription():
    future = (datetime.now(UTC) + timedelta(days=5)).isoformat()
    base = _make_sub(paddle_subscription_id="sub_paid", status="past_due")
    sub = Subscription(
        subscription_id=base.subscription_id,
        user_id=base.user_id,
        paddle_customer_id=base.paddle_customer_id,
        paddle_subscription_id=base.paddle_subscription_id,
        tier=base.tier,
        status=base.status,
        current_period_end=future,
        created_at=base.created_at,
        updated_at=base.updated_at,
    )
    assert sub.has_access is False


def test_canceled_subscription_loses_access_after_period_end():
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    base = _make_sub(paddle_subscription_id="sub_paid", status="canceled")
    sub = Subscription(
        subscription_id=base.subscription_id,
        user_id=base.user_id,
        paddle_customer_id=base.paddle_customer_id,
        paddle_subscription_id=base.paddle_subscription_id,
        tier=base.tier,
        status=base.status,
        current_period_end=past,
        created_at=base.created_at,
        updated_at=base.updated_at,
    )
    assert sub.has_access is False


def test_is_comped_true_when_status_is_comped():
    sub = _make_sub(status="comped")
    assert sub.is_comped is True
    assert sub.has_access is True


def test_comped_access_gets_paid_limits(billing_service, registered_user):
    billing_service.grant_comped_access(registered_user.user_id)

    sub = billing_service.get_subscription(registered_user.user_id)
    assert sub is not None
    assert sub.is_comped is True
    assert sub.paddle_subscription_id is None
    assert billing_service.check_game_limit(registered_user.user_id) is True


# ---------------------------------------------------------------------------
# Full subscription lifecycle (free → paid → cancelled)
# ---------------------------------------------------------------------------


def test_subscription_lifecycle_free_to_paid(
    billing_service, registered_user, sub_repo
):
    """Limits and has_subscription reflect state correctly as a user moves
    from free through activation to cancellation."""

    uid = registered_user.user_id

    # --- Free phase (no sub row) ---
    sub = billing_service.get_subscription(uid)
    assert sub is None

    # Create sub row so webhook can update it
    sub_repo.create(str(uuid.uuid4()), uid, Tier.INDIE)

    # --- Webhook: subscription activated ---
    event = _paddle_event(
        "subscription.activated",
        price_id="pri_indie",
        customer_id="ctm_life",
        sub_id="sub_life",
        user_id=uid,
    )
    billing_service._sync_subscription(event)

    sub = billing_service.get_subscription(uid)
    assert sub is not None
    assert sub.has_subscription is True
    assert sub.has_access is True

    # --- Webhook: subscription cancelled at period end ---
    cancel_event = _paddle_event(
        "subscription.canceled",
        price_id="pri_indie",
        customer_id="ctm_life",
        sub_id="sub_life",
        status="canceled",
        user_id=uid,
    )
    billing_service._cancel_subscription(cancel_event)

    billing_service._subs.update_from_paddle(
        uid,
        current_period_end=(datetime.now(UTC) - timedelta(days=1)).isoformat(),
    )

    sub = billing_service.get_subscription(uid)
    assert sub is not None
    assert sub.status == "canceled"
    assert sub.has_subscription is True
    assert sub.has_access is False


def test_checkout_context_uses_indie_price_id(
    billing_service, registered_user
):
    ctx = billing_service.checkout_context(
        registered_user.user_id, "dev@example.com"
    )
    assert ctx.price_id == "pri_indie"
    assert ctx.environment == "sandbox"
    assert ctx.customer_email == "dev@example.com"
    assert ctx.custom_data == {"user_id": registered_user.user_id}


def test_sync_subscription_updates_customer_ids_and_status(
    billing_service, registered_user, sub_repo
):

    sub_repo.create(str(uuid.uuid4()), registered_user.user_id, Tier.INDIE)

    event = _paddle_event(
        "subscription.created",
        price_id="pri_indie",
        customer_id="ctm_42",
        sub_id="sub_abc",
        user_id=registered_user.user_id,
    )
    billing_service._sync_subscription(event)

    updated = billing_service.get_subscription(registered_user.user_id)
    assert updated is not None
    assert updated.tier == Tier.INDIE
    assert updated.paddle_customer_id == "ctm_42"
    assert updated.paddle_subscription_id == "sub_abc"
    assert updated.status == "active"


def test_sync_subscription_treats_legacy_price_ids_as_indie(
    billing_service, registered_user, sub_repo
):

    sub_repo.create(str(uuid.uuid4()), registered_user.user_id, Tier.INDIE)

    event = _paddle_event(
        "subscription.created",
        price_id="pri_studio_legacy",
        customer_id="ctm_legacy",
        sub_id="sub_legacy",
        user_id=registered_user.user_id,
    )
    billing_service._sync_subscription(event)

    updated = billing_service.get_subscription(registered_user.user_id)
    assert updated is not None
    assert updated.tier == Tier.INDIE
    assert updated.paddle_subscription_id == "sub_legacy"


def test_sync_subscription_falls_back_to_customer_id_lookup(
    billing_service, registered_user, sub_repo
):

    sub_repo.create(str(uuid.uuid4()), registered_user.user_id, Tier.INDIE)
    billing_service._subs.update_from_paddle(
        registered_user.user_id, paddle_customer_id="ctm_lookup"
    )

    event = _paddle_event(
        "subscription.updated",
        price_id="pri_indie",
        customer_id="ctm_lookup",
        sub_id="sub_xyz",
        status="past_due",
    )
    billing_service._sync_subscription(event)

    updated = billing_service.get_subscription(registered_user.user_id)
    assert updated is not None
    assert updated.paddle_subscription_id == "sub_xyz"
    assert updated.status == "past_due"


def test_cancel_subscription_marks_subscription_cancelled(
    billing_service, registered_user, sub_repo
):

    sub_repo.create(str(uuid.uuid4()), registered_user.user_id, Tier.INDIE)
    billing_service._subs.update_from_paddle(
        registered_user.user_id,
        paddle_customer_id="ctm_cancel",
        tier=Tier.INDIE,
        status="active",
    )

    event = _paddle_event(
        "subscription.canceled",
        price_id="pri_indie",
        customer_id="ctm_cancel",
        sub_id="sub_cancel",
        status="canceled",
        user_id=registered_user.user_id,
    )
    billing_service._cancel_subscription(event)

    cancelled = billing_service.get_subscription(registered_user.user_id)
    assert cancelled is not None
    assert cancelled.status == "canceled"
    assert cancelled.tier == Tier.INDIE


def test_verify_signature_returns_true_for_correct_signature(billing_service):
    secret = "webhook_secret_test"
    payload = b'{"event_type":"subscription.created"}'
    ts = "1700000000"
    signed = ts.encode() + b":" + payload
    sig = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    header = f"ts={ts};h1={sig}"

    with patch("app.billing.service.time.time", return_value=1700000001):
        assert (
            billing_service._verify_signature(payload, header, secret) is True
        )


def test_handle_webhook_raises_on_invalid_signature(billing_service):
    payload = b'{"event_type":"subscription.created"}'
    with pytest.raises(ValueError, match="signature"):
        billing_service.handle_webhook(payload, "ts=1;h1=bad", "secret")


def test_handle_webhook_is_noop_when_webhook_secret_missing(
    sub_repo, game_repo
):
    svc = BillingService(sub_repo, game_repo)
    svc.handle_webhook(b"{}", "any", "")


def test_handle_webhook_processes_without_api_key(
    registered_user, sub_repo, game_repo
):

    sub_repo.create(str(uuid.uuid4()), registered_user.user_id, Tier.INDIE)
    svc = BillingService(
        sub_repo,
        game_repo,
        paddle_indie_price_id="pri_indie",
    )
    payload = json.dumps(
        _paddle_event(
            "subscription.created",
            price_id="pri_indie",
            customer_id="ctm_no_api",
            sub_id="sub_no_api",
            user_id=registered_user.user_id,
        )
    ).encode()
    ts = "1700000000"
    signed = ts.encode() + b":" + payload
    signature = hmac.new(
        b"webhook_secret_test", signed, hashlib.sha256
    ).hexdigest()
    header = f"ts={ts};h1={signature}"

    with patch("app.billing.service.time.time", return_value=1700000001):
        svc.handle_webhook(payload, header, "webhook_secret_test")

    updated = sub_repo.get_by_user(registered_user.user_id)
    assert updated is not None
    assert updated.tier == Tier.INDIE
    assert updated.paddle_subscription_id == "sub_no_api"


# ---------------------------------------------------------------------------
# sync_from_transaction — eager activation on checkout success redirect
# ---------------------------------------------------------------------------


def _mock_http_responses(transaction_data: dict, subscription_data: dict):
    """Return an httpx AsyncClient mock that yields two sequential responses."""
    txn_resp = MagicMock()
    txn_resp.raise_for_status = MagicMock()
    txn_resp.json.return_value = {"data": transaction_data}

    sub_resp = MagicMock()
    sub_resp.raise_for_status = MagicMock()
    sub_resp.json.return_value = {"data": subscription_data}

    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(side_effect=[txn_resp, sub_resp])
    return client


@pytest.mark.anyio
async def test_sync_from_transaction_activates_subscription(
    billing_service, registered_user, sub_repo
):
    """Success redirect with _ptxn activates the subscription immediately."""

    sub_repo.create(str(uuid.uuid4()), registered_user.user_id, Tier.INDIE)

    txn_data = {"subscription_id": "sub_txn", "customer_id": "ctm_txn"}
    sub_data = {
        "status": "active",
        "items": [{"price": {"id": "pri_indie"}}],
        "current_billing_period": {
            "starts_at": "2026-03-01T00:00:00Z",
            "ends_at": "2026-04-01T00:00:00Z",
        },
    }
    mock_client = _mock_http_responses(txn_data, sub_data)

    with patch(
        "app.billing.service.httpx.AsyncClient", return_value=mock_client
    ):
        await billing_service.sync_from_transaction(
            registered_user.user_id, "txn_abc"
        )

    sub = billing_service.get_subscription(registered_user.user_id)
    assert sub is not None
    assert sub.has_subscription is True
    assert sub.has_access is True
    assert sub.paddle_subscription_id == "sub_txn"
    assert sub.paddle_customer_id == "ctm_txn"


@pytest.mark.anyio
async def test_sync_from_transaction_is_noop_without_api_key(
    sub_repo, game_repo, registered_user
):
    """No API key → silently skips, no sub row created."""
    svc = BillingService(
        sub_repo, game_repo, paddle_indie_price_id="pri_indie"
    )

    await svc.sync_from_transaction(registered_user.user_id, "txn_abc")

    sub = sub_repo.get_by_user(registered_user.user_id)
    assert sub is None


@pytest.mark.anyio
async def test_sync_from_transaction_is_noop_without_transaction_id(
    billing_service, registered_user, sub_repo
):
    """Empty transaction ID → silently skips."""

    sub_repo.create(str(uuid.uuid4()), registered_user.user_id, Tier.INDIE)

    await billing_service.sync_from_transaction(registered_user.user_id, "")

    sub = billing_service.get_subscription(registered_user.user_id)
    assert sub is not None
    assert sub.has_subscription is False


@pytest.mark.anyio
async def test_sync_from_transaction_swallows_api_errors(
    billing_service, registered_user, sub_repo
):
    """Paddle API failure does not raise — webhook will recover."""

    sub_repo.create(str(uuid.uuid4()), registered_user.user_id, Tier.INDIE)

    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(side_effect=Exception("network error"))

    with patch("app.billing.service.httpx.AsyncClient", return_value=client):
        await billing_service.sync_from_transaction(
            registered_user.user_id, "txn_bad"
        )

    sub = billing_service.get_subscription(registered_user.user_id)
    assert sub is not None
    assert sub.has_subscription is False


def test_free_limits_value():
    """FREE_LIMITS grants 1 game slot."""

    assert FREE_LIMITS == {"games": 1}


def test_canceled_subscription_keeps_access_until_period_end():
    future = (datetime.now(UTC) + timedelta(days=5)).isoformat()
    sub = _make_sub(
        paddle_subscription_id="sub_paid",
        status="canceled",
    )
    sub = Subscription(
        subscription_id=sub.subscription_id,
        user_id=sub.user_id,
        paddle_customer_id=sub.paddle_customer_id,
        paddle_subscription_id=sub.paddle_subscription_id,
        tier=sub.tier,
        status=sub.status,
        current_period_end=future,
        created_at=sub.created_at,
        updated_at=sub.updated_at,
    )
    assert sub.has_access is True
