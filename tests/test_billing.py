"""Tests for subscription management and tier limit enforcement."""

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.billing.models import TIER_LIMITS, TRIAL_LIMITS, Subscription, Tier
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


def test_get_or_create_subscription_creates_indie_sub_for_new_user(
    billing_service, registered_user
):
    sub = billing_service.get_or_create_subscription(registered_user.user_id)
    assert isinstance(sub, Subscription)
    assert sub.user_id == registered_user.user_id
    assert sub.tier == Tier.INDIE
    assert sub.status == "active"


def test_get_or_create_subscription_returns_existing_sub_on_second_call(
    billing_service, registered_user
):
    sub1 = billing_service.get_or_create_subscription(registered_user.user_id)
    sub2 = billing_service.get_or_create_subscription(registered_user.user_id)
    assert sub1.subscription_id == sub2.subscription_id


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
        description="desc",
        genre_tags_raw="puzzle",
        audience_tags_raw="fans",
        platform_tags=["browser"],
        website_url=None,
    )
    assert billing_service.check_game_limit(registered_user.user_id) is False


def test_get_prospects_limit_during_trial(billing_service, registered_user):
    limit = billing_service.get_prospects_limit(registered_user.user_id)
    assert limit == TRIAL_LIMITS["prospects_per_run"]


def test_indie_tier_game_limit_is_three():
    assert TIER_LIMITS[Tier.INDIE]["games"] == 3


def test_indie_tier_prospects_limit_is_fifty():
    assert TIER_LIMITS[Tier.INDIE]["prospects_per_run"] == 50


def test_trial_discovery_runs_limit_is_three():
    assert TRIAL_LIMITS["discovery_runs_per_month"] == 3


def _make_sub(*, trial_ends_at=None, paddle_subscription_id=None, user_id="u1", status="active"):
    now = datetime.now(UTC).isoformat()
    return Subscription(
        subscription_id="sub_test",
        user_id=user_id,
        paddle_customer_id=None,
        paddle_subscription_id=paddle_subscription_id,
        tier=Tier.INDIE,
        status=status,
        current_period_end=None,
        trial_ends_at=trial_ends_at,
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


def test_is_comped_true_when_status_is_comped():
    sub = _make_sub(status="comped")
    assert sub.is_comped is True
    assert sub.has_access is True


def test_comped_access_gets_paid_limits(billing_service, registered_user):
    billing_service.grant_comped_access(registered_user.user_id)

    sub = billing_service.get_or_create_subscription(registered_user.user_id)
    assert sub.is_comped is True
    assert sub.is_trialing is False
    assert sub.paddle_subscription_id is None
    assert billing_service.get_discovery_runs_limit(registered_user.user_id) == TIER_LIMITS[Tier.INDIE]["discovery_runs_per_month"]


# ---------------------------------------------------------------------------
# is_trialing — derived from has_subscription + trial window
# ---------------------------------------------------------------------------


def test_is_trialing_true_when_trial_end_is_in_future():
    future = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    sub = _make_sub(trial_ends_at=future)
    assert sub.is_trialing is True


def test_is_trialing_false_when_trial_has_expired():
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    sub = _make_sub(trial_ends_at=past)
    assert sub.is_trialing is False


def test_is_trialing_false_when_no_trial_end_set():
    sub = _make_sub(trial_ends_at=None)
    assert sub.is_trialing is False


def test_is_trialing_false_when_paddle_subscription_id_is_set():
    # Paying user: trial banner must not reappear even if trial_ends_at is still future.
    future = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    sub = _make_sub(trial_ends_at=future, paddle_subscription_id="sub_paid")
    assert sub.is_trialing is False


# ---------------------------------------------------------------------------
# Full subscription lifecycle (trial → paid → cancelled)
# ---------------------------------------------------------------------------


def test_subscription_lifecycle_trial_to_paid(billing_service, registered_user):
    """Limits, has_subscription, and is_trialing all reflect state correctly
    as a user moves from trial through activation to cancellation."""
    uid = registered_user.user_id

    # --- Trial phase ---
    sub = billing_service.get_or_create_subscription(uid)
    assert sub.has_subscription is False
    assert sub.is_trialing is True
    assert billing_service.get_discovery_runs_limit(uid) == TRIAL_LIMITS["discovery_runs_per_month"]

    # --- Webhook: subscription activated ---
    event = _paddle_event(
        "subscription.activated",
        price_id="pri_indie",
        customer_id="ctm_life",
        sub_id="sub_life",
        user_id=uid,
    )
    billing_service._sync_subscription(event)

    sub = billing_service.get_or_create_subscription(uid)
    assert sub.has_subscription is True
    assert sub.is_trialing is False
    assert billing_service.get_discovery_runs_limit(uid) == TIER_LIMITS[Tier.INDIE]["discovery_runs_per_month"]

    # --- Webhook: subscription cancelled ---
    cancel_event = _paddle_event(
        "subscription.canceled",
        price_id="pri_indie",
        customer_id="ctm_life",
        sub_id="sub_life",
        status="canceled",
        user_id=uid,
    )
    billing_service._cancel_subscription(cancel_event)

    sub = billing_service.get_or_create_subscription(uid)
    assert sub.status == "canceled"
    # paddle_subscription_id is preserved after cancel so has_subscription stays True;
    # limits are still granted (access until period end is handled at the service level).
    assert sub.has_subscription is True


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
    billing_service, registered_user
):
    billing_service.get_or_create_subscription(registered_user.user_id)

    event = _paddle_event(
        "subscription.created",
        price_id="pri_indie",
        customer_id="ctm_42",
        sub_id="sub_abc",
        user_id=registered_user.user_id,
    )
    billing_service._sync_subscription(event)

    updated = billing_service.get_or_create_subscription(
        registered_user.user_id
    )
    assert updated.tier == Tier.INDIE
    assert updated.paddle_customer_id == "ctm_42"
    assert updated.paddle_subscription_id == "sub_abc"
    assert updated.status == "active"


def test_sync_subscription_treats_legacy_price_ids_as_indie(
    billing_service, registered_user
):
    billing_service.get_or_create_subscription(registered_user.user_id)

    event = _paddle_event(
        "subscription.created",
        price_id="pri_studio_legacy",
        customer_id="ctm_legacy",
        sub_id="sub_legacy",
        user_id=registered_user.user_id,
    )
    billing_service._sync_subscription(event)

    updated = billing_service.get_or_create_subscription(
        registered_user.user_id
    )
    assert updated.tier == Tier.INDIE
    assert updated.paddle_subscription_id == "sub_legacy"


def test_sync_subscription_falls_back_to_customer_id_lookup(
    billing_service, registered_user
):
    billing_service.get_or_create_subscription(registered_user.user_id)
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

    updated = billing_service.get_or_create_subscription(
        registered_user.user_id
    )
    assert updated.paddle_subscription_id == "sub_xyz"
    assert updated.status == "past_due"


def test_cancel_subscription_marks_subscription_cancelled(
    billing_service, registered_user
):
    billing_service.get_or_create_subscription(registered_user.user_id)
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

    cancelled = billing_service.get_or_create_subscription(
        registered_user.user_id
    )
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
    svc = BillingService(
        sub_repo,
        game_repo,
        paddle_indie_price_id="pri_indie",
    )
    svc.get_or_create_subscription(registered_user.user_id)
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
    billing_service, registered_user
):
    """Success redirect with _ptxn activates the subscription immediately."""
    billing_service.get_or_create_subscription(registered_user.user_id)

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

    with patch("app.billing.service.httpx.AsyncClient", return_value=mock_client):
        await billing_service.sync_from_transaction(
            registered_user.user_id, "txn_abc"
        )

    sub = billing_service.get_or_create_subscription(registered_user.user_id)
    assert sub.has_subscription is True
    assert sub.is_trialing is False
    assert sub.paddle_subscription_id == "sub_txn"
    assert sub.paddle_customer_id == "ctm_txn"


@pytest.mark.anyio
async def test_sync_from_transaction_is_noop_without_api_key(
    sub_repo, game_repo, registered_user
):
    """No API key → silently skips, subscription stays in trial."""
    svc = BillingService(sub_repo, game_repo, paddle_indie_price_id="pri_indie")
    svc.get_or_create_subscription(registered_user.user_id)

    await svc.sync_from_transaction(registered_user.user_id, "txn_abc")

    sub = sub_repo.get_by_user(registered_user.user_id)
    assert sub is not None
    assert sub.has_subscription is False


@pytest.mark.anyio
async def test_sync_from_transaction_is_noop_without_transaction_id(
    billing_service, registered_user
):
    """Empty transaction ID → silently skips."""
    billing_service.get_or_create_subscription(registered_user.user_id)

    await billing_service.sync_from_transaction(registered_user.user_id, "")

    sub = billing_service.get_or_create_subscription(registered_user.user_id)
    assert sub.has_subscription is False


@pytest.mark.anyio
async def test_sync_from_transaction_swallows_api_errors(
    billing_service, registered_user
):
    """Paddle API failure does not raise — webhook will recover."""
    billing_service.get_or_create_subscription(registered_user.user_id)

    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(side_effect=Exception("network error"))

    with patch("app.billing.service.httpx.AsyncClient", return_value=client):
        await billing_service.sync_from_transaction(
            registered_user.user_id, "txn_bad"
        )

    sub = billing_service.get_or_create_subscription(registered_user.user_id)
    assert sub.has_subscription is False
