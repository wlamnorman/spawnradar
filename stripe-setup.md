# Lemon Squeezy Setup Guide

This document covers how to configure Lemon Squeezy for local development and production. Lemon Squeezy acts as the Merchant of Record, handling EU VAT, US sales tax, and all payment compliance automatically.

---

## 1. Create a Lemon Squeezy Account

Go to [lemonsqueezy.com](https://www.lemonsqueezy.com) and create an account. Once inside, create a **Store** — give it your brand name (SpawnRadar). The store ID is shown in the URL when you're inside the store dashboard.

---

## 2. Create Products and Variants

In your store: **Products → Add product**

Create two products:

| Product | Price | Billing | Type |
|---|---|---|---|
| SpawnRadar Starter | $10.00 / month | Recurring | Subscription |
| SpawnRadar Pro | $49.00 / month | Recurring | Subscription |

Each product has one **variant** (the specific billing configuration). After saving, open each variant and copy its **Variant ID** (a number, visible in the URL or the variant settings panel). You need both.

---

## 3. Set Environment Variables

Add the following to your `.env` file:

```bash
# From app.lemonsqueezy.com → Settings → API
LEMONSQUEEZY_API_KEY=eyJ0eXAiOiJ...

# From the webhook setup below
LEMONSQUEEZY_WEBHOOK_SECRET=your_webhook_secret

# From your store dashboard URL (e.g. app.lemonsqueezy.com/stores/12345)
LEMONSQUEEZY_STORE_ID=12345

# Variant IDs from the products you created
LEMONSQUEEZY_STARTER_VARIANT_ID=111111
LEMONSQUEEZY_PRO_VARIANT_ID=222222

# The base URL for redirect links after checkout
BASE_URL=http://localhost:8000
```

The API key is found under **Settings → API** in your Lemon Squeezy dashboard.

---

## 4. Set Up Local Webhook Forwarding

Lemon Squeezy sends webhook events to your server. For local development, use their test mode and a tunnel tool like [ngrok](https://ngrok.com) or the Lemon Squeezy CLI.

**Option A — ngrok:**

```bash
ngrok http 8000
```

This gives you a public URL like `https://abc123.ngrok.io`. Use that as your webhook endpoint URL.

**Option B — Lemon Squeezy test mode:**

In the LS dashboard, go to **Settings → Webhooks → Add webhook**:
- URL: your ngrok URL + `/billing/webhook`
- Secret: any string you choose (copy into `LEMONSQUEEZY_WEBHOOK_SECRET`)
- Events to enable: see below

Leave ngrok and the dev server running while testing.

---

## 5. Webhook Events We Handle

Register these events when creating your webhook in the LS dashboard:

| Event | What happens |
|---|---|
| `subscription_created` | Local subscription is synced with tier, status, and customer ID |
| `subscription_updated` | Same — handles plan changes, renewals, trial conversions |
| `subscription_resumed` | Reactivates a previously paused subscription |
| `subscription_unpaused` | Same as resumed |
| `subscription_cancelled` | Subscription marked cancelled, tier reverts to Starter |
| `subscription_expired` | Same as cancelled |
| `subscription_paused` | Status updated to paused |

All other event types are silently ignored.

---

## 6. Test the Checkout Flow Locally

With the dev server and ngrok both running:

1. Register an account and go to `/pricing`
2. Click **Upgrade**
3. You are redirected to Lemon Squeezy's hosted checkout page
4. In test mode, use the test card provided in the LS dashboard (usually `4242 4242 4242 4242`)
5. After completing checkout, LS fires `subscription_created` to your webhook URL
6. The subscription record in the local DB is updated with the customer ID and tier

To test a cancellation: go into the LS dashboard, find the test subscription, and cancel it manually. The `subscription_cancelled` event will fire to your webhook.

---

## 7. Customer Portal

Lemon Squeezy provides a hosted customer portal where subscribers can:
- View billing history
- Update payment method
- Cancel or pause their subscription

Unlike Stripe, there's nothing to configure in advance — the portal URL is returned dynamically from the subscription object via the LS API whenever a user clicks "Manage billing" in the app.

---

## 8. Going Live

When ready to go live:

1. Remove test products and create live products with the correct prices
2. Add a live webhook in the LS dashboard: **Settings → Webhooks → Add webhook**
   - URL: `https://spawnradar.app/billing/webhook`
   - Enable all subscription events listed above
   - Set a strong random webhook secret
3. Update all env vars with live values in Fly.io:

```bash
fly secrets set LEMONSQUEEZY_API_KEY=eyJ0eXAi...
fly secrets set LEMONSQUEEZY_WEBHOOK_SECRET=your_live_secret
fly secrets set LEMONSQUEEZY_STORE_ID=12345
fly secrets set LEMONSQUEEZY_STARTER_VARIANT_ID=111111
fly secrets set LEMONSQUEEZY_PRO_VARIANT_ID=222222
```

---

## 9. VAT and Tax

Nothing to do. Lemon Squeezy is the Merchant of Record. They collect and remit VAT for EU customers, handle US state sales tax, and issue compliant invoices. You receive revenue net of fees and taxes. No OSS registration, no quarterly VAT filings.

---

## 10. Verification

With everything configured, verify the integration:

```bash
# Check that billing service reports as enabled
curl -s http://localhost:8000/pricing | grep -i "billing"

# Confirm the webhook endpoint responds
curl -s -X POST http://localhost:8000/billing/webhook \
  -H "Content-Type: application/json" \
  -H "x-signature: badsig" \
  -d '{}' | python3 -m json.tool
# Should return 400 with signature error (proving the endpoint is reachable)
```
