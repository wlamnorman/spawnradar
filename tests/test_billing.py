"""Tests for subscription management and tier limit enforcement."""

from datetime import UTC, datetime, timedelta

from app.billing.models import TIER_LIMITS, Subscription, Tier


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


def test_check_game_limit_returns_true_when_under_limit(
    billing_service, registered_user
):
    # Starter allows 1 game; user has 0 games
    result = billing_service.check_game_limit(registered_user.user_id)
    assert result is True


def test_check_game_limit_returns_false_when_at_limit(
    billing_service, game_service, registered_user
):
    # New subscriptions are in Starter trial (1 game limit).
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
    # New subscriptions are in Starter trial → 50 prospects per run
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


def test_pro_subscription_is_not_treated_as_trialing_with_trial_end():
    future = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    sub = Subscription(
        subscription_id="sub_123",
        user_id="user_123",
        stripe_customer_id=None,
        stripe_subscription_id=None,
        tier=Tier.PRO,
        status="active",
        current_period_end=None,
        trial_ends_at=future,
        created_at=future,
        updated_at=future,
    )

    assert sub.is_trialing is False
    assert sub.effective_tier == Tier.PRO


def test_utc_timestamp_to_iso_returns_timezone_aware_string(billing_service):
    iso_value = billing_service._utc_timestamp_to_iso(1_700_000_000)

    assert iso_value is not None
    assert iso_value.endswith("+00:00")
    assert datetime.fromisoformat(iso_value).tzinfo == UTC


def test_utc_timestamp_to_iso_returns_none_for_invalid_values(
    billing_service,
):
    assert billing_service._utc_timestamp_to_iso(None) is None
    assert billing_service._utc_timestamp_to_iso("1700000000") is None
    assert billing_service._utc_timestamp_to_iso(0) is None


def test_sync_subscription_updates_existing_subscription_from_customer_id(
    billing_service, registered_user
):
    original = billing_service.get_or_create_subscription(
        registered_user.user_id
    )
    billing_service._subs.update_from_stripe(
        registered_user.user_id,
        stripe_customer_id="cus_123",
    )

    billing_service._sync_subscription(
        {
            "customer": "cus_123",
            "id": "sub_123",
            "status": "active",
            "current_period_end": 1_700_000_000,
            "items": {
                "data": [
                    {"price": {"id": billing_service._pro_price}},
                ]
            },
            "metadata": {},
        }
    )

    updated = billing_service.get_or_create_subscription(
        registered_user.user_id
    )
    assert updated.subscription_id == original.subscription_id
    assert updated.stripe_customer_id == "cus_123"
    assert updated.stripe_subscription_id == "sub_123"
    assert updated.tier == Tier.PRO
    assert updated.status == "active"
    assert (
        updated.current_period_end
        == datetime.fromtimestamp(1_700_000_000, UTC).isoformat()
    )


def test_sync_subscription_falls_back_to_metadata_user_id(
    billing_service, registered_user
):
    billing_service.get_or_create_subscription(registered_user.user_id)

    billing_service._sync_subscription(
        {
            "customer": "cus_meta",
            "id": "sub_meta",
            "status": "past_due",
            "current_period_end": None,
            "items": {
                "data": [
                    {"price": {"id": billing_service._starter_price}},
                ]
            },
            "metadata": {"user_id": registered_user.user_id},
        }
    )

    updated = billing_service.get_or_create_subscription(
        registered_user.user_id
    )
    assert updated.stripe_customer_id == "cus_meta"
    assert updated.stripe_subscription_id == "sub_meta"
    assert updated.tier == Tier.STARTER
    assert updated.status == "past_due"
    assert updated.current_period_end is None


def test_cancel_subscription_marks_subscription_cancelled(
    billing_service, registered_user
):
    billing_service.get_or_create_subscription(registered_user.user_id)
    billing_service._subs.update_from_stripe(
        registered_user.user_id,
        stripe_customer_id="cus_cancel",
        tier=Tier.PRO,
        status="active",
    )

    billing_service._cancel_subscription({"customer": "cus_cancel"})

    cancelled = billing_service.get_or_create_subscription(
        registered_user.user_id
    )
    assert cancelled.status == "cancelled"
    assert cancelled.tier == Tier.STARTER
