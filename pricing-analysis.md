# Pricing Analysis

This document examines whether the current pricing ($10 Starter / $25 Pro) makes economic sense, estimates the actual cost to serve users, and compares against the competitive landscape.

---

## Current Pricing

| Tier | Price | Games | Prospects/run |
|---|---|---|---|
| Starter | $10/mo | 1 | 50 |
| Pro | $25/mo | 5 | 500 |

Trial: 3-day trial on Starter only.

---

## Cost to Serve

### Infrastructure (Fly.io)

A single-machine Fly.io deployment running FastAPI + SQLite:

| Resource | Cost |
|---|---|
| 1 shared-CPU machine (256 MB RAM) | ~$3–5/mo |
| 2 GB persistent volume (SQLite) | ~$0.30/mo |
| Bandwidth (low at this scale) | ~$0 |
| **Total infra** | **~$4–6/mo base** |

This is essentially flat until concurrency or data volume forces a machine upgrade. SQLite on a single machine is very cost-efficient at this scale.

### Claude Haiku (LLM Scoring)

From `llm_engine.py` estimates: ~$0.0016 per channel scored.

| Tier | Games | Runs/month | Channels/run | Monthly LLM cost |
|---|---|---|---|---|
| Starter | 1 | 4 (weekly) | 50 | ~$0.32 |
| Pro | 5 | 20 (weekly each) | 500 | ~$16.00 |

Haiku is extremely cheap. The Pro tier is the one where LLM cost becomes meaningful — 20 runs × 500 channels = 10,000 channels/month × $0.0016 = **$16/user/month** at max usage.

This is the number that matters for Pro pricing. At $25/mo, if a Pro user runs at full capacity every week, LLM alone costs $16, leaving $9 gross margin before infra.

### YouTube Data API

YouTube API quota: 10,000 units/day (free). Each search costs ~100 units; fetching video details for 10 channels costs ~30 units. A typical run costs ~300–500 units. At 4 runs/month per game:

- Starter (1 game, 4 runs): ~1,600–2,000 units/month → well within free tier
- Pro (5 games, 20 runs): ~6,000–10,000 units/month → may hit quota on heavy days

Quota is per project, not per user. At 100 Pro users all running simultaneously, quota becomes a shared constraint. **This is the scaling bottleneck, not cost.**

Solution path: YouTube Data API v3 offers paid quota at $4.50 per 1,000 units beyond the free tier. At scale, budget $5–20/month per 1,000 active Pro users for YouTube quota.

### Stripe Fees

Stripe charges 2.9% + $0.30 per successful payment.

| Tier | Gross | Stripe fee | Net |
|---|---|---|---|
| Starter | $10.00 | $0.59 | $9.41 |
| Pro | $25.00 | $1.03 | $23.97 |

### Email (Resend)

Resend free tier: 3,000 emails/month. This covers transactional auth emails for the first ~500–1,000 users. Paid tier ($20/mo) starts at 50,000 emails/month — far beyond early-stage needs.

---

## Unit Economics

### At 10 paying users (7 Starter, 3 Pro)

| | Amount |
|---|---|
| Revenue | 7×$9.41 + 3×$23.97 = $137.78 |
| Infra | $5 |
| LLM (avg half-capacity) | 7×$0.64 + 3×$8.00 = $28.48 |
| Total COGS | ~$34 |
| **Gross margin** | **~75%** |

### At 100 paying users (70 Starter, 30 Pro)

| | Amount |
|---|---|
| Revenue | 70×$9.41 + 30×$23.97 = $1,377.80 |
| Infra | ~$10 (more volume) |
| LLM (avg half-capacity) | 70×$0.64 + 30×$8.00 = $284.80 |
| Resend | $0 (still in free tier) |
| Total COGS | ~$295 |
| **Gross margin** | **~79%** |

### At 1,000 paying users (700 Starter, 300 Pro)

| | Amount |
|---|---|
| Revenue | 700×$9.41 + 300×$23.97 = $13,778 |
| Infra | ~$30–50 (multiple machines or larger) |
| LLM (avg half-capacity) | 700×$0.64 + 300×$8.00 = $2,848 |
| YouTube API quota overages | ~$200 |
| Resend (~30K emails/mo) | $0 |
| Total COGS | ~$3,100 |
| **Gross margin** | **~78%** |

The margin profile is healthy and improves slightly with scale due to the flat infra base. The main variable cost is the LLM, which scales roughly linearly with Pro usage.

---

## The Pro Pricing Problem

The biggest concern with the current pricing is **Pro at $25/mo**.

At full usage (5 games, weekly runs, 500 channels each), LLM alone costs $16/user/month. That leaves only $9 before infra, Stripe fees, and YouTube quota. If Pro users are heavy users — which they likely are, because they're running 5 games — margins compress significantly.

**Options:**

1. **Raise Pro to $49/mo** — still cheap vs. alternatives (see below), improves margin to ~50–60% even at full usage. The value of 5-game management + 500 prospects/run is easily worth $49 to a studio with a portfolio.

2. **Add a run-count limit** — e.g., 20 discovery runs/month for Pro. This caps the LLM cost ceiling without changing the headline price.

3. **Reduce Pro LLM scope** — run LLM scoring only on the top 50 candidates per run (by keyword score), not all 500. Cost drops to ~$1.60/run = ~$32/mo at 20 runs. This is already somewhat addressed by `_has_scoreable_text`.

4. **Move to token-based pricing** — "X discovery credits" per tier, additional credits purchasable. More flexible but more complex to explain.

---

## Competitive Landscape

| Tool | Price | What it does |
|---|---|---|
| **Keymailer** | Free (limited) / custom | Key distribution + creator database |
| **Woovit / Lurkit** | Free + revenue share | Key distribution, PR management |
| **Prowly** | $189–$359/mo | PR management for agencies |
| **GamePressKit.io** | ~$19/mo | Press kit hosting only |
| **PR Newswire (gaming)** | $400–800/release | Press release distribution |
| **Indie game PR agencies** | $500–3,000/mo retainer | Full-service outreach |

Key observation: **there is no direct competitor at the $10–25 price point** doing what SpawnRadar does (scored creator discovery + draft generation). The nearest alternatives are either free with no scoring (Keymailer) or $100+ for agency-grade tools.

This suggests pricing can be higher, not lower. The $10 Starter price may be **underselling the value** — a single well-placed YouTube video can generate 500–2,000 wishlists, which for an indie launch is worth thousands of dollars.

---

## Recommendations

### Near-term (before launch)

1. **Keep Starter at $10/mo** — low enough to be a no-brainer for a developer in active launch mode. It's a gateway to Pro.

2. **Raise Pro to $49/mo** — justified by the multi-game use case and significantly healthier margins. Position it as "portfolio management," not just more of the same.

3. **Extend trial to 7 days** — 3 days is too short to run a full ingestion cycle, review the queue, and see value. 7 days is the SaaS standard. Change `TRIAL_DAYS = 3` → `TRIAL_DAYS = 7` in `billing/models.py`.

4. **Add a free tier** (consider) — one game, 10 prospects/run, no LLM scoring. This removes friction for developers who won't pay for a trial. It also generates organic word-of-mouth. Downside: support burden and potential abuse.

### Medium-term

5. **Add per-run credit limits to Pro** (e.g., 30 runs/month) to cap LLM cost ceiling without hurting most users.

6. **YouTube quota management** — at scale, consider pooling quotas across a rotation of API keys or building a shared queue with rate limiting.

---

## Summary

The economics work at current pricing, but the margin on Pro is thin if users are heavy. The strategic concern is not profitability (70–80% gross margin is solid) but leaving money on the table — indie developers would pay more for a tool that demonstrably helps them get coverage.

**The single most impactful change: raise Pro from $25 to $49.**

The trial length (3 days) is the other thing to fix before launch — it's not enough time for a developer to complete a discovery run, review results, and see a draft message worth sending.
