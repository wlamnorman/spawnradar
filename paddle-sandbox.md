# Paddle Sandbox Testing

## Test Cards

| Card type              | Card number          | CVC | Name | Expiry date   |
|------------------------|----------------------|-----|------|---------------|
| Valid card without 3DS | 4242 4242 4242 4242  | 100 | Any  | Any in future |
| Valid card with 3DS    | 4000 0038 0000 0446  | 100 | Any  | Any in future |
| Declined card          | 4000 0000 0000 0002  | 100 | Any  | Any in future |

## Local Webhook Testing with Hookdeck

Paddle webhooks can't reach localhost directly. Use the Hookdeck CLI to forward them.

### One-time setup

1. Install the CLI:
   ```bash
   brew install hookdeck/hookdeck/hookdeck
   ```

2. Log in (creates/links a free Hookdeck account):
   ```bash
   hookdeck login
   ```

3. In the Paddle sandbox dashboard (sandbox.paddle.com):
   - Go to **Notifications** → **New destination**
   - URL: the Hookdeck source URL printed by the CLI (e.g. `https://hkdk.events/xxxx`)
   - Secret key: copy this value into `.env` as `PADDLE_WEBHOOK_SECRET`
   - Events: `subscription.created`, `subscription.updated`, `subscription.activated`, `subscription.canceled`

### Every dev session

In a separate terminal, before starting the server:
```bash
hookdeck listen 8000 paddle --path /billing/webhook
```

Then start the server as normal:
```bash
make run
```

The Hookdeck CLI terminal shows each webhook event as it arrives. Press `r` on a failed event to replay it without going through checkout again.

### Troubleshooting

- **400 errors on webhook**: `PADDLE_WEBHOOK_SECRET` in `.env` doesn't match the secret on the Paddle notification destination. Copy the full secret (starts with `pdl_ntfset_`) from the Paddle sandbox dashboard and paste it into `.env`, then fully restart `make run` (uvicorn `--reload` does not pick up `.env` changes).
- **Subscription not activating after checkout**: The webhook may not have arrived yet. The success page polls automatically — wait a few seconds. If it times out, check the Hookdeck terminal for failed events and replay with `r`.
- **Hookdeck source URL changes**: If you create a new source, update the notification destination URL in the Paddle sandbox dashboard.
