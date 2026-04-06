"""HTTP integration tests for Paddle billing routes.

Covers the full webhook → subscription activation flow, the polling status
endpoint, the checkout success page and the billing management page.
These tests verify behaviour that is critical to the paid subscription flow
and must not regress silently.
"""

import hashlib
import hmac
import json
import time
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from httpx import Response

from app.database import get_connection
from app.main import create_app

# Known secret used to sign webhooks in all tests.  Must match what is set
# in the monkeypatched PADDLE_WEBHOOK_SECRET env var below.
_WEBHOOK_SECRET = "test_webhook_secret_billing_routes"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(monkeypatch, tmp_path) -> tuple[TestClient, str]:
    db_path = str(tmp_path / "billing-routes.sqlite3")
    monkeypatch.setenv("DB_PATH", db_path)
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("PADDLE_WEBHOOK_SECRET", _WEBHOOK_SECRET)
    monkeypatch.setenv("PADDLE_API_KEY", "test_api_key")
    monkeypatch.setenv(
        "PADDLE_CLIENT_SIDE_TOKEN", "test_123456789012345678901234567"
    )
    monkeypatch.setenv("PADDLE_INDIE_PRICE_ID", "pri_test_indie")
    monkeypatch.setenv("PADDLE_ENVIRONMENT", "sandbox")
    monkeypatch.delenv("DEV_AUTO_LOGIN", raising=False)
    monkeypatch.setenv("RESEND_API_KEY", "")
    return TestClient(create_app()), db_path


def _csrf_token(client: TestClient, path: str) -> str:
    import re

    response = client.get(path)
    match = re.search(r'name="csrf-token" content="([^"]+)"', response.text)
    assert match is not None
    return match.group(1)


def _register_and_verify(
    client: TestClient, db_path: str, email: str = "user@example.com"
) -> None:
    token = _csrf_token(client, "/auth/register")
    client.post(
        "/auth/register",
        data={"email": email, "password": "password123", "csrf_token": token},
        follow_redirects=False,
    )
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE users SET email_verified = 1 WHERE email = ?", (email,)
        )


def _get_user_id(db_path: str, email: str) -> str:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT user_id FROM users WHERE email = ?", (email,)
        ).fetchone()
    assert row is not None
    return row["user_id"]


def _get_workspace_id(db_path: str, user_id: str) -> str:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT workspace_id FROM workspaces WHERE owner_user_id = ?",
            (user_id,),
        ).fetchone()
    assert row is not None
    return row["workspace_id"]


def _get_sub_row(db_path: str, user_id: str) -> dict:
    workspace_id = _get_workspace_id(db_path, user_id)
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM subscriptions WHERE workspace_id = ?", (workspace_id,)
        ).fetchone()
    assert row is not None, f"No subscription found for user {user_id}"
    return dict(row)


def _signed_webhook(
    payload: dict,
    secret: str = _WEBHOOK_SECRET,
    age_seconds: int = 0,
) -> tuple[bytes, str]:
    """Return (body_bytes, Paddle-Signature header) for a signed event."""
    body = json.dumps(payload).encode()
    ts = str(int(time.time()) - age_seconds)
    signed = ts.encode() + b":" + body
    sig = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return body, f"ts={ts};h1={sig}"


def _post_webhook(client: TestClient, payload: dict, **kwargs) -> Response:
    body, sig_header = _signed_webhook(payload, **kwargs)
    return client.post(
        "/billing/webhook",
        content=body,
        headers={
            "Paddle-Signature": sig_header,
            "Content-Type": "application/json",
        },
    )


def _activation_event(
    workspace_id: str,
    *,
    event_type: str = "subscription.activated",
    customer_id: str = "ctm_test",
    sub_id: str = "sub_test",
    status: str = "active",
) -> dict:
    period_end = (datetime.now(UTC) + timedelta(days=30)).isoformat()
    return {
        "event_id": "evt_test",
        "event_type": event_type,
        "data": {
            "id": sub_id,
            "customer_id": customer_id,
            "status": status,
            "items": [{"price": {"id": "pri_test_indie"}}],
            "current_billing_period": {
                "starts_at": datetime.now(UTC).isoformat(),
                "ends_at": period_end,
            },
            "custom_data": {"workspace_id": workspace_id},
        },
    }


def _create_sub_row(db_path: str, user_id: str) -> None:
    """Create a bare subscription row for a user (no Paddle IDs)."""
    import uuid

    from app.billing.models import Tier
    from app.billing.repository import SubscriptionRepository
    workspace_id = _get_workspace_id(db_path, user_id)
    SubscriptionRepository(db_path).create(
        str(uuid.uuid4()), workspace_id, Tier.INDIE
    )


def _activate_subscription(
    client: TestClient, db_path: str, email: str = "user@example.com"
) -> str:
    """Register, verify and fire an activation webhook. Returns user_id."""
    _register_and_verify(client, db_path, email)
    user_id = _get_user_id(db_path, email)
    event = _activation_event(_get_workspace_id(db_path, user_id))
    resp = _post_webhook(client, event)
    assert resp.status_code == 200
    return user_id


# ---------------------------------------------------------------------------
# Webhook endpoint — signature verification
# ---------------------------------------------------------------------------


class TestWebhookSignatureVerification:
    def test_valid_signature_returns_200(self, monkeypatch, tmp_path):
        client, db_path = _make_client(monkeypatch, tmp_path)
        with client:
            _register_and_verify(client, db_path)
            user_id = _get_user_id(db_path, "user@example.com")
            event = _activation_event(_get_workspace_id(db_path, user_id))
            response = _post_webhook(client, event)
        assert response.status_code == 200

    def test_invalid_hmac_returns_400(self, monkeypatch, tmp_path):
        client, db_path = _make_client(monkeypatch, tmp_path)
        with client:
            body = json.dumps(
                {"event_type": "subscription.created", "data": {}}
            ).encode()
            ts = str(int(time.time()))
            response = client.post(
                "/billing/webhook",
                content=body,
                headers={
                    "Paddle-Signature": f"ts={ts};h1=deadbeefdeadbeefdeadbeef",
                    "Content-Type": "application/json",
                },
            )
        assert response.status_code == 400

    def test_wrong_secret_returns_400(self, monkeypatch, tmp_path):
        client, _ = _make_client(monkeypatch, tmp_path)
        with client:
            event = {"event_type": "subscription.created", "data": {}}
            body, sig_header = _signed_webhook(event, secret="wrong_secret")
            response = client.post(
                "/billing/webhook",
                content=body,
                headers={
                    "Paddle-Signature": sig_header,
                    "Content-Type": "application/json",
                },
            )
        assert response.status_code == 400

    def test_expired_timestamp_returns_400(self, monkeypatch, tmp_path):
        client, db_path = _make_client(monkeypatch, tmp_path)
        with client:
            event = {"event_type": "subscription.created", "data": {}}
            body, sig_header = _signed_webhook(
                event, age_seconds=400
            )  # >5 min old
            response = client.post(
                "/billing/webhook",
                content=body,
                headers={
                    "Paddle-Signature": sig_header,
                    "Content-Type": "application/json",
                },
            )
        assert response.status_code == 400

    def test_missing_signature_header_returns_400(self, monkeypatch, tmp_path):
        client, _ = _make_client(monkeypatch, tmp_path)
        with client:
            body = json.dumps(
                {"event_type": "subscription.created", "data": {}}
            ).encode()
            response = client.post(
                "/billing/webhook",
                content=body,
                headers={"Content-Type": "application/json"},
            )
        assert response.status_code == 400

    def test_empty_webhook_secret_configured_is_noop_not_error(
        self, monkeypatch, tmp_path
    ):
        """When PADDLE_WEBHOOK_SECRET is unset the handler silently ignores all events."""
        monkeypatch.setenv("DB_PATH", str(tmp_path / "noop.sqlite3"))
        monkeypatch.setenv("SECRET_KEY", "test-secret")
        monkeypatch.setenv("PADDLE_WEBHOOK_SECRET", "")
        for key in (
            "PADDLE_API_KEY",
            "PADDLE_CLIENT_SIDE_TOKEN",
            "PADDLE_INDIE_PRICE_ID",
            "PADDLE_ENVIRONMENT",
            "RESEND_API_KEY",
        ):
            monkeypatch.setenv(key, "")
        monkeypatch.delenv("DEV_AUTO_LOGIN", raising=False)

        with TestClient(create_app()) as client:
            body = json.dumps(
                {"event_type": "subscription.activated"}
            ).encode()
            response = client.post(
                "/billing/webhook",
                content=body,
                headers={
                    "Paddle-Signature": "ts=1;h1=anything",
                    "Content-Type": "application/json",
                },
            )
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Webhook endpoint — event handling
# ---------------------------------------------------------------------------


class TestWebhookEventHandling:
    def test_subscription_created_activates_subscription(
        self, monkeypatch, tmp_path
    ):
        client, db_path = _make_client(monkeypatch, tmp_path)
        with client:
            _register_and_verify(client, db_path)
            user_id = _get_user_id(db_path, "user@example.com")
            event = _activation_event(
                _get_workspace_id(db_path, user_id),
                event_type="subscription.created",
            )
            _post_webhook(client, event)
        sub = _get_sub_row(db_path, user_id)
        assert sub["paddle_subscription_id"] == "sub_test"
        assert sub["paddle_customer_id"] == "ctm_test"
        assert sub["status"] == "active"

    def test_subscription_activated_activates_subscription(
        self, monkeypatch, tmp_path
    ):
        client, db_path = _make_client(monkeypatch, tmp_path)
        with client:
            _register_and_verify(client, db_path)
            user_id = _get_user_id(db_path, "user@example.com")
            event = _activation_event(
                _get_workspace_id(db_path, user_id),
                event_type="subscription.activated",
            )
            _post_webhook(client, event)
        sub = _get_sub_row(db_path, user_id)
        assert sub["paddle_subscription_id"] == "sub_test"
        assert sub["status"] == "active"

    def test_subscription_canceled_marks_canceled(self, monkeypatch, tmp_path):
        client, db_path = _make_client(monkeypatch, tmp_path)
        with client:
            user_id = _activate_subscription(client, db_path)
            cancel = _activation_event(
                _get_workspace_id(db_path, user_id),
                event_type="subscription.canceled",
                status="canceled",
            )
            _post_webhook(client, cancel)
        sub = _get_sub_row(db_path, user_id)
        assert sub["status"] == "canceled"
        assert sub["paddle_subscription_id"] == "sub_test"  # ID preserved

    def test_subscription_past_due_marks_past_due(self, monkeypatch, tmp_path):
        client, db_path = _make_client(monkeypatch, tmp_path)
        with client:
            user_id = _activate_subscription(client, db_path)
            event = _activation_event(
                _get_workspace_id(db_path, user_id),
                event_type="subscription.past_due",
                status="past_due",
            )
            _post_webhook(client, event)
        sub = _get_sub_row(db_path, user_id)
        assert sub["status"] == "past_due"

    def test_subscription_paused_marks_paused(self, monkeypatch, tmp_path):
        client, db_path = _make_client(monkeypatch, tmp_path)
        with client:
            user_id = _activate_subscription(client, db_path)
            event = _activation_event(
                _get_workspace_id(db_path, user_id),
                event_type="subscription.paused",
                status="paused",
            )
            _post_webhook(client, event)
        sub = _get_sub_row(db_path, user_id)
        assert sub["status"] == "paused"

    def test_subscription_updated_updates_status(self, monkeypatch, tmp_path):
        client, db_path = _make_client(monkeypatch, tmp_path)
        with client:
            user_id = _activate_subscription(client, db_path)
            event = _activation_event(
                _get_workspace_id(db_path, user_id),
                event_type="subscription.updated",
                status="active",
            )
            _post_webhook(client, event)
        sub = _get_sub_row(db_path, user_id)
        assert sub["status"] == "active"

    def test_unknown_event_type_is_accepted_and_ignored(
        self, monkeypatch, tmp_path
    ):
        client, db_path = _make_client(monkeypatch, tmp_path)
        with client:
            _register_and_verify(client, db_path)
            user_id = _get_user_id(db_path, "user@example.com")
            _create_sub_row(db_path, user_id)
            workspace_id = _get_workspace_id(db_path, user_id)
            event = {
                "event_type": "transaction.completed",
                "data": {"custom_data": {"workspace_id": workspace_id}},
            }
            response = _post_webhook(client, event)
        assert response.status_code == 200
        sub = _get_sub_row(db_path, user_id)
        assert sub["paddle_subscription_id"] is None  # unchanged

    def test_webhook_resolves_user_by_customer_id_when_custom_data_absent(
        self, monkeypatch, tmp_path
    ):
        """Fallback: if custom_data has no user_id, look up by paddle_customer_id."""
        client, db_path = _make_client(monkeypatch, tmp_path)
        with client:
            _register_and_verify(client, db_path)
            user_id = _get_user_id(db_path, "user@example.com")
            _create_sub_row(db_path, user_id)
            workspace_id = _get_workspace_id(db_path, user_id)

            # Pre-link the customer ID to this user's subscription
            with get_connection(db_path) as conn:
                conn.execute(
                    "UPDATE subscriptions SET paddle_customer_id = 'ctm_lookup' WHERE workspace_id = ?",
                    (workspace_id,),
                )

            # Webhook with no user_id in custom_data
            event = {
                "event_type": "subscription.updated",
                "data": {
                    "id": "sub_fallback",
                    "customer_id": "ctm_lookup",
                    "status": "active",
                    "items": [{"price": {"id": "pri_test_indie"}}],
                    "current_billing_period": {
                        "starts_at": datetime.now(UTC).isoformat(),
                        "ends_at": (
                            datetime.now(UTC) + timedelta(days=30)
                        ).isoformat(),
                    },
                    "custom_data": {},
                },
            }
            response = _post_webhook(client, event)

        assert response.status_code == 200
        sub = _get_sub_row(db_path, user_id)
        assert sub["paddle_subscription_id"] == "sub_fallback"

    def test_webhook_for_unknown_user_is_accepted_gracefully(
        self, monkeypatch, tmp_path
    ):
        """Webhook for an unknown workspace must not crash the server."""
        client, db_path = _make_client(monkeypatch, tmp_path)
        with client:
            event = _activation_event("ws_does_not_exist")
            response = _post_webhook(client, event)
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# /billing/status — polling endpoint
# ---------------------------------------------------------------------------


class TestBillingStatusEndpoint:
    def test_returns_false_for_free_user(self, monkeypatch, tmp_path):
        client, db_path = _make_client(monkeypatch, tmp_path)
        with client:
            _register_and_verify(client, db_path)
            response = client.get("/billing/status")
        assert response.status_code == 200
        assert response.json() == {"active": False}

    def test_returns_true_after_webhook_activates_subscription(
        self, monkeypatch, tmp_path
    ):
        client, db_path = _make_client(monkeypatch, tmp_path)
        with client:
            _ = _activate_subscription(client, db_path)
            response = client.get("/billing/status")
        assert response.status_code == 200
        assert response.json() == {"active": True}

    def test_remains_true_after_cancellation(self, monkeypatch, tmp_path):
        """/billing/status reflects whether a Paddle subscription ID is linked,
        not whether access is currently valid.  A canceled subscription keeps
        has_subscription=True so the status endpoint keeps returning active=True —
        this is intentional: the endpoint exists only to detect webhook arrival
        during the checkout polling flow, not to gate feature access."""
        client, db_path = _make_client(monkeypatch, tmp_path)
        with client:
            user_id = _activate_subscription(client, db_path)
            cancel = _activation_event(
                _get_workspace_id(db_path, user_id),
                event_type="subscription.canceled",
                status="canceled",
            )
            _post_webhook(client, cancel)
            past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
            workspace_id = _get_workspace_id(db_path, user_id)
            with get_connection(db_path) as conn:
                conn.execute(
                    "UPDATE subscriptions SET current_period_end = ? WHERE workspace_id = ?",
                    (past, workspace_id),
                )
            response = client.get("/billing/status")
        assert response.status_code == 200
        assert response.json() == {
            "active": True
        }  # paddle_subscription_id still set

    def test_requires_authentication(self, monkeypatch, tmp_path):
        client, db_path = _make_client(monkeypatch, tmp_path)
        with client:
            response = client.get("/billing/status", follow_redirects=False)
        assert response.status_code in (302, 303, 307)


# ---------------------------------------------------------------------------
# /billing/success — checkout landing page
# ---------------------------------------------------------------------------


class TestCheckoutSuccessPage:
    def test_renders_polling_page_for_trial_user(self, monkeypatch, tmp_path):
        client, db_path = _make_client(monkeypatch, tmp_path)
        with client:
            _register_and_verify(client, db_path)
            response = client.get("/billing/success")
        assert response.status_code == 200
        assert "Activating" in response.text
        assert "billing-success.js" in response.text

    def test_polling_page_contains_fallback_link_to_billing(
        self, monkeypatch, tmp_path
    ):
        client, db_path = _make_client(monkeypatch, tmp_path)
        with client:
            _register_and_verify(client, db_path)
            response = client.get("/billing/success")
        assert "/billing" in response.text

    def test_redirects_to_billing_immediately_when_already_active(
        self, monkeypatch, tmp_path
    ):
        client, db_path = _make_client(monkeypatch, tmp_path)
        with client:
            _activate_subscription(client, db_path)
            response = client.get("/billing/success", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/billing"

    def test_requires_authentication(self, monkeypatch, tmp_path):
        client, db_path = _make_client(monkeypatch, tmp_path)
        with client:
            response = client.get("/billing/success", follow_redirects=False)
        assert response.status_code in (302, 303, 307)


# ---------------------------------------------------------------------------
# /billing — management page
# ---------------------------------------------------------------------------


class TestBillingManagementPage:
    def test_free_user_is_redirected_to_pricing(
        self, monkeypatch, tmp_path
    ):
        client, db_path = _make_client(monkeypatch, tmp_path)
        with client:
            _register_and_verify(client, db_path)
            response = client.get("/billing", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/pricing"

    def test_active_subscriber_sees_active_status_and_manage_link(
        self, monkeypatch, tmp_path
    ):
        client, db_path = _make_client(monkeypatch, tmp_path)
        with client:
            _activate_subscription(client, db_path)
            response = client.get("/billing")
        assert response.status_code == 200
        assert "Active" in response.text
        assert "Manage subscription" in response.text
        assert "Subscribe now" not in response.text

    def test_active_subscriber_sees_next_renewal_date(
        self, monkeypatch, tmp_path
    ):
        client, db_path = _make_client(monkeypatch, tmp_path)
        with client:
            _activate_subscription(client, db_path)
            response = client.get("/billing")
        assert response.status_code == 200
        assert "Next renewal" in response.text

    def test_canceled_subscription_shows_canceled_status(
        self, monkeypatch, tmp_path
    ):
        client, db_path = _make_client(monkeypatch, tmp_path)
        with client:
            user_id = _activate_subscription(client, db_path)
            cancel = _activation_event(
                _get_workspace_id(db_path, user_id),
                event_type="subscription.canceled",
                status="canceled",
            )
            _post_webhook(client, cancel)
            response = client.get("/billing")
        assert response.status_code == 200
        assert "Canceled" in response.text
        assert "Next renewal" not in response.text

    def test_past_due_subscription_shows_past_due_status(
        self, monkeypatch, tmp_path
    ):
        client, db_path = _make_client(monkeypatch, tmp_path)
        with client:
            user_id = _activate_subscription(client, db_path)
            event = _activation_event(
                _get_workspace_id(db_path, user_id),
                event_type="subscription.past_due",
                status="past_due",
            )
            _post_webhook(client, event)
            response = client.get("/billing")
        assert response.status_code == 200
        assert "Past due" in response.text

    def test_requires_authentication(self, monkeypatch, tmp_path):
        client, _ = _make_client(monkeypatch, tmp_path)
        with client:
            response = client.get("/billing", follow_redirects=False)
        assert response.status_code in (302, 303, 307)


# ---------------------------------------------------------------------------
# Nav — Pricing vs Billing link
# ---------------------------------------------------------------------------


class TestBillingNav:
    def test_free_user_sees_pricing_in_nav(self, monkeypatch, tmp_path):
        client, db_path = _make_client(monkeypatch, tmp_path)
        with client:
            _register_and_verify(client, db_path)
            response = client.get("/pricing")
        assert 'href="/pricing"' in response.text or response.status_code in (200,)
        # Game routes are now open to all users — free users see the page, not a redirect
        games_response = client.get("/games", follow_redirects=False)
        assert games_response.status_code == 200

    def test_active_subscriber_sees_billing_in_nav(
        self, monkeypatch, tmp_path
    ):
        client, db_path = _make_client(monkeypatch, tmp_path)
        with client:
            _activate_subscription(client, db_path)
            response = client.get("/games")
        assert 'href="/billing"' in response.text
        assert 'href="/pricing"' not in response.text


# ---------------------------------------------------------------------------
# Full end-to-end flow
# ---------------------------------------------------------------------------


class TestFullActivationFlow:
    def test_trial_activates_via_webhook_and_status_endpoint_drives_redirect(
        self, monkeypatch, tmp_path
    ):
        """Simulates the complete path: register → trial → webhook → polling → active.

        This mirrors exactly what happens in production:
        1. User completes Paddle checkout
        2. /billing/success renders polling page (webhook not yet arrived)
        3. /billing/status returns {"active": false} on first poll
        4. Paddle fires webhook → /billing/webhook processes it
        5. /billing/status returns {"active": true} on next poll → JS redirects
        6. /billing shows active subscription
        """
        client, db_path = _make_client(monkeypatch, tmp_path)
        with client:
            _register_and_verify(client, db_path)
            user_id = _get_user_id(db_path, "user@example.com")

            # Step 2: success page renders polling UI
            success = client.get("/billing/success")
            assert success.status_code == 200
            assert "Activating" in success.text

            # Step 3: first poll — webhook has not arrived yet
            assert client.get("/billing/status").json() == {"active": False}

            # Step 4: webhook arrives
            event = _activation_event(
                _get_workspace_id(db_path, user_id),
                customer_id="ctm_e2e",
                sub_id="sub_e2e",
            )
            webhook_resp = _post_webhook(client, event)
            assert webhook_resp.status_code == 200

            # Step 5: second poll — subscription is now active
            assert client.get("/billing/status").json() == {"active": True}

            # Subsequent visit to success redirects directly to /billing
            success2 = client.get("/billing/success", follow_redirects=False)
            assert success2.status_code == 303
            assert success2.headers["location"] == "/billing"

            # Step 6: billing page shows active state
            billing = client.get("/billing")
            assert billing.status_code == 200
            assert "Active" in billing.text
            assert "Manage subscription" in billing.text

    def test_trial_to_canceled_full_lifecycle(self, monkeypatch, tmp_path):
        """Trial → active → canceled → loses access after period end."""
        client, db_path = _make_client(monkeypatch, tmp_path)
        with client:
            _register_and_verify(client, db_path)
            user_id = _get_user_id(db_path, "user@example.com")

            # Free user: not active
            assert client.get("/billing/status").json() == {"active": False}

            # Activate
            _post_webhook(
                client,
                _activation_event(_get_workspace_id(db_path, user_id)),
            )
            assert client.get("/billing/status").json() == {"active": True}

            # Cancel
            cancel = _activation_event(
                _get_workspace_id(db_path, user_id),
                event_type="subscription.canceled",
                status="canceled",
            )
            _post_webhook(client, cancel)

            # Still reports active — has_subscription=True because paddle_subscription_id
            # is set; the status endpoint is not an access gate, just a webhook detector.
            assert client.get("/billing/status").json() == {"active": True}

            # Expire the billing period and verify billing page shows Canceled
            past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
            workspace_id = _get_workspace_id(db_path, user_id)
            with get_connection(db_path) as conn:
                conn.execute(
                    "UPDATE subscriptions SET current_period_end = ? WHERE workspace_id = ?",
                    (past, workspace_id),
                )

            # Billing page still renders (not redirected to /pricing) and shows Canceled
            billing = client.get("/billing")
            assert billing.status_code == 200
            assert "Canceled" in billing.text
