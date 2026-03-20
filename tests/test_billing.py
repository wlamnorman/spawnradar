"""Tests for subscription management and tier limit enforcement."""

from datetime import UTC, datetime, timedelta

from app.billing.models import TIER_LIMITS, Subscription, Tier


def _ls_event(
    event_name, variant_id, customer_id, sub_id, status="active", user_id=None
):
    """Build a minimal Lemon Squeezy webhook event dict."""
    custom_data = {"user_id": user_id} if user_id else {}
    return {
        "meta": {
            "event_name": event_name,
            "custom_data": custom_data,
        },
        "data": {
            "id": sub_id,
            "type": "subscriptions",
            "attributes": {
                "customer_id": customer_id,
                "status": status,
                "variant_id": variant_id,
                "renews_at": "2026-06-01T00:00:00.000000Z",
                "urls": {
                    "customer_portal": "https://app.lemonsqueezy.com/portal"
                },
            },
        },
    }


# ---------------------------------------------------------------------------
# Subscription creation
# ---------------------------------------------------------------------------


def test_get_or_create_subscription_creates_starter_sub_for_new_user(
    billing_service, registered_user
):
    sub = billing_service.get_or_create_subscription(registered_user.user_id)
    assert isinstance(sub, Subscription)
    assert sub.user_id == registered_user.user_id
    assert sub.tier == Tier.STARTER
    assert sub.status == "active"


def test_get_or_create_subscription_returns_existing_sub_on_second_call(
    billing_service, registered_user
):
    sub1 = billing_service.get_or_create_subscription(registered_user.user_id)
    sub2 = billing_service.get_or_create_subscription(registered_user.user_id)
    assert sub1.subscription_id == sub2.subscription_id


# ---------------------------------------------------------------------------
# Game and prospect limits
# ---------------------------------------------------------------------------


def test_check_game_limit_returns_true_when_under_limit(
    billing_service, registered_user
):
    result = billing_service.check_game_limit(registered_user.user_id)
    assert result is True


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
    result = billing_service.check_game_limit(registered_user.user_id)
    assert result is False


def test_get_prospects_limit_during_trial(billing_service, registered_user):
    limit = billing_service.get_prospects_limit(registered_user.user_id)
    assert limit == 50


def test_starter_tier_game_limit_is_one():
    assert TIER_LIMITS[Tier.STARTER]["games"] == 1


def test_pro_tier_game_limit_is_five():
    assert TIER_LIMITS[Tier.PRO]["games"] == 5


def test_starter_tier_prospects_limit_is_fifty():
    assert TIER_LIMITS[Tier.STARTER]["prospects_per_run"] == 50


def test_pro_tier_prospects_limit_is_500():
    assert TIER_LIMITS[Tier.PRO]["prospects_per_run"] == 500


# ---------------------------------------------------------------------------
# Trial state
# ---------------------------------------------------------------------------


def test_is_trialing_returns_true_when_trial_end_is_in_future(registered_user):
    future = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    sub = Subscription(
        subscription_id="sub_trial",
        user_id=registered_user.user_id,
        ls_customer_id=None,
        ls_subscription_id=None,
        tier=Tier.STARTER,
        status="active",
        current_period_end=None,
        trial_ends_at=future,
        created_at=future,
        updated_at=future,
    )
    assert sub.is_trialing is True


def test_is_trialing_returns_false_when_trial_has_expired(registered_user):
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    sub = Subscription(
        subscription_id="sub_expired",
        user_id=registered_user.user_id,
        ls_customer_id=None,
        ls_subscription_id=None,
        tier=Tier.STARTER,
        status="active",
        current_period_end=None,
        trial_ends_at=past,
        created_at=past,
        updated_at=past,
    )
    assert sub.is_trialing is False


def test_is_trialing_returns_false_when_no_trial_ends_at(registered_user):
    now = datetime.now(UTC).isoformat()
    sub = Subscription(
        subscription_id="sub_notrial",
        user_id=registered_user.user_id,
        ls_customer_id=None,
        ls_subscription_id=None,
        tier=Tier.STARTER,
        status="active",
        current_period_end=None,
        trial_ends_at=None,
        created_at=now,
        updated_at=now,
    )
    assert sub.is_trialing is False


def test_pro_subscription_is_not_treated_as_trialing_with_trial_end():
    future = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    sub = Subscription(
        subscription_id="sub_123",
        user_id="user_123",
        ls_customer_id=None,
        ls_subscription_id=None,
        tier=Tier.PRO,
        status="active",
        current_period_end=None,
        trial_ends_at=future,
        created_at=future,
        updated_at=future,
    )
    assert sub.is_trialing is False
    assert sub.effective_tier == Tier.PRO


def test_trial_days_remaining_returns_correct_value(registered_user):
    future = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    sub = Subscription(
        subscription_id="sub_days",
        user_id=registered_user.user_id,
        ls_customer_id=None,
        ls_subscription_id=None,
        tier=Tier.STARTER,
        status="active",
        current_period_end=None,
        trial_ends_at=future,
        created_at=future,
        updated_at=future,
    )
    assert sub.trial_days_remaining == 3


def test_trial_days_remaining_returns_none_when_not_trialing(registered_user):
    now = datetime.now(UTC).isoformat()
    sub = Subscription(
        subscription_id="sub_notrialdays",
        user_id=registered_user.user_id,
        ls_customer_id=None,
        ls_subscription_id=None,
        tier=Tier.STARTER,
        status="active",
        current_period_end=None,
        trial_ends_at=None,
        created_at=now,
        updated_at=now,
    )
    assert sub.trial_days_remaining is None


# ---------------------------------------------------------------------------
# Webhook: _sync_subscription
# ---------------------------------------------------------------------------


def test_sync_subscription_updates_tier_from_variant_id(
    billing_service, registered_user
):
    billing_service.get_or_create_subscription(registered_user.user_id)

    event = _ls_event(
        "subscription_created",
        variant_id=billing_service._pro_variant,
        customer_id="42",
        sub_id="sub_abc",
        user_id=registered_user.user_id,
    )
    billing_service._sync_subscription(event)

    updated = billing_service.get_or_create_subscription(
        registered_user.user_id
    )
    assert updated.tier == Tier.PRO
    assert updated.ls_customer_id == "42"
    assert updated.ls_subscription_id == "sub_abc"
    assert updated.status == "active"


def test_sync_subscription_falls_back_to_customer_id_lookup(
    billing_service, registered_user
):
    billing_service.get_or_create_subscription(registered_user.user_id)
    billing_service._subs.update_from_ls(
        registered_user.user_id, ls_customer_id="cus_lookup"
    )

    # No user_id in custom_data — must look up by customer_id
    event = _ls_event(
        "subscription_updated",
        variant_id=billing_service._starter_variant,
        customer_id="cus_lookup",
        sub_id="sub_xyz",
        status="past_due",
    )
    billing_service._sync_subscription(event)

    updated = billing_service.get_or_create_subscription(
        registered_user.user_id
    )
    assert updated.ls_subscription_id == "sub_xyz"
    assert updated.status == "past_due"


def test_sync_subscription_with_unknown_customer_is_noop(
    billing_service, registered_user
):
    billing_service.get_or_create_subscription(registered_user.user_id)

    event = _ls_event(
        "subscription_created",
        variant_id=billing_service._pro_variant,
        customer_id="cus_nobody",
        sub_id="sub_nobody",
    )
    billing_service._sync_subscription(event)

    sub = billing_service.get_or_create_subscription(registered_user.user_id)
    assert sub.ls_customer_id is None  # unchanged


# ---------------------------------------------------------------------------
# Webhook: _cancel_subscription
# ---------------------------------------------------------------------------


def test_cancel_subscription_marks_subscription_cancelled(
    billing_service, registered_user
):
    billing_service.get_or_create_subscription(registered_user.user_id)
    billing_service._subs.update_from_ls(
        registered_user.user_id,
        ls_customer_id="cus_cancel",
        tier=Tier.PRO,
        status="active",
    )

    event = _ls_event(
        "subscription_cancelled",
        variant_id=billing_service._pro_variant,
        customer_id="cus_cancel",
        sub_id="sub_cancel",
        status="cancelled",
        user_id=registered_user.user_id,
    )
    billing_service._cancel_subscription(event)

    cancelled = billing_service.get_or_create_subscription(
        registered_user.user_id
    )
    assert cancelled.status == "cancelled"
    assert cancelled.tier == Tier.STARTER


# ---------------------------------------------------------------------------
# Cancelled / Pro limit enforcement
# ---------------------------------------------------------------------------


def test_cancelled_subscription_reports_starter_limits(
    billing_service, registered_user
):
    billing_service.get_or_create_subscription(registered_user.user_id)
    billing_service._subs.update_from_ls(
        registered_user.user_id,
        ls_customer_id="cus_was_pro",
        tier=Tier.PRO,
        status="active",
    )
    event = _ls_event(
        "subscription_cancelled",
        variant_id=billing_service._pro_variant,
        customer_id="cus_was_pro",
        sub_id="sub_x",
        status="cancelled",
        user_id=registered_user.user_id,
    )
    billing_service._cancel_subscription(event)

    limit = billing_service.get_prospects_limit(registered_user.user_id)
    assert limit == TIER_LIMITS[Tier.STARTER]["prospects_per_run"]


def test_pro_tier_prospects_limit_is_higher_than_starter(
    billing_service, registered_user
):
    billing_service.get_or_create_subscription(registered_user.user_id)
    billing_service._subs.update_from_ls(
        registered_user.user_id,
        ls_customer_id="cus_pro",
        tier=Tier.PRO,
        status="active",
    )
    limit = billing_service.get_prospects_limit(registered_user.user_id)
    assert limit == TIER_LIMITS[Tier.PRO]["prospects_per_run"]
    assert limit > TIER_LIMITS[Tier.STARTER]["prospects_per_run"]


# ---------------------------------------------------------------------------
# Webhook signature verification
# ---------------------------------------------------------------------------


def test_verify_signature_returns_true_for_correct_signature(billing_service):
    import hashlib
    import hmac as _hmac

    secret = "webhook_secret_test"
    payload = b'{"meta":{"event_name":"subscription_created"}}'
    sig = _hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    assert billing_service._verify_signature(payload, sig, secret) is True


def test_verify_signature_returns_false_for_wrong_signature(billing_service):
    payload = b'{"meta":{"event_name":"subscription_created"}}'
    assert (
        billing_service._verify_signature(payload, "bad_sig", "secret")
        is False
    )


def test_handle_webhook_raises_on_invalid_signature(billing_service):
    import pytest

    payload = b'{"meta":{"event_name":"subscription_created"}}'
    with pytest.raises(ValueError, match="signature"):
        billing_service.handle_webhook(payload, "badsig", "secret")


def test_handle_webhook_is_noop_when_ls_not_configured(sub_repo, game_repo):
    from app.billing.service import BillingService

    svc = BillingService(sub_repo, game_repo)  # no api key
    svc.handle_webhook(b"{}", "any", "any")  # should not raise
