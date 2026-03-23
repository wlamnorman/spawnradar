# Creator Signup & Research Programme

## Why We're Building This

SpawnRadar's core value is connecting indie developers with the right content creators. Right now, discovery is entirely outbound — we scrape and score creators who haven't asked to be found. This works, but it has a ceiling.

The missing piece is a directory of creators who *want* to be approached.

This unlocks two things simultaneously:

**1. A better signal for developers**
A creator who has explicitly opted in, declared their genre interests and specified how they like to be contacted is worth ten scraped contacts with inferred data. Response rates should be dramatically higher because the intent is declared, not assumed.

**2. Research data that makes the whole product smarter**
By asking creators survey questions when they sign up, we build a dataset on what actually drives responses to indie dev pitches. This is data no one else has in a structured form. It improves our scoring model and becomes a publishable report that drives SEO and authority ("We asked 500 gaming creators what makes them respond to indie game pitches").

---

## What the Signup Page Does

Creators land on `/creators` and fill out a single form that serves double duty: it registers them in our opted-in directory AND answers our research questions.

The framing for creators: "Get discovered by indie developers whose games actually match your content. We'll only connect you with games that fit what you cover."

Fields collected:

### Identity
- Display name (how they want to be addressed in pitches)
- Email address (for notifications when a matching game is added)
- YouTube channel handle
- Twitch handle
- TikTok handle
- Reddit username
- Bluesky handle

At least one platform handle is required.

### What They Cover
- Game genres they're open to (multi-select: action, puzzle, RPG, roguelike, horror, strategy, simulation, platformer, narrative, sports, racing, fighting, sandbox, other)
- Preferred platform type (PC, console, mobile, browser, any)
- Approximate audience size (Under 5K / 5K–20K / 20K–100K / 100K+)

### Outreach Preferences
- Do they accept review keys? (Yes / Sometimes / No)
- Preferred contact method (Email / YouTube DM / Twitch whisper / Reddit DM / Twitter DM)
- How much lead time they prefer before a game's launch (1 week / 2–3 weeks / 1 month / No preference)

### Research Questions (the survey)
These are the questions we genuinely want answered — framed as helping us match them with developers more accurately:

1. **What's the first thing you check in a pitch email?** (free text, short)
2. **What immediately makes you delete a pitch?** (free text, short)
3. **What would make you more likely to cover an unknown indie game?** (multi-select: strong trailer, clear genre fit, personal connection in the message, no-obligation key offer, prior relationship with the dev, interesting concept, demo available)
4. **Do you prefer to be contacted before or after a game launches?** (Before only / After only / Either / No preference)
5. **Anything else you want developers to know before reaching out?** (optional free text)

---

## What Happens After Signup

1. Creator is added to the `creator_signups` table
2. Confirmation email sent: "You're on the SpawnRadar creator list. We'll notify you when an indie dev with a matching game wants to connect."
3. Creator appears in the opted-in directory (visible to logged-in developers as a bonus signal in the queue)
4. Aggregate survey responses feed into our research report

When we have enough responses (target: 100+), we publish a post: "We asked [N] gaming creators what makes them respond to indie dev outreach — here's what they said." This becomes the most useful resource in the genre and drives signups on both sides.

---

## What Developers See

Opted-in creators show up in the prospect queue with a "Verified opt-in" badge. This is a filter option: "Show only opted-in creators." Their preferred contact method and genre interests are pre-populated and the draft message respects their stated preferences.

This gives developers a curated shortlist of warm leads alongside the standard scraped-and-scored results.

---

## Go-to-Market

To seed the directory before launch:

1. Post in r/gamedev, r/indiegaming, r/letsplay — "We built a free opt-in list for gaming creators who want to be contacted by indie devs. If you're a creator who wants discovery deals, sign up here."
2. Tweet / Bluesky post at gaming creators directly.
3. Mention it in the blog posts as a CTA.
4. Add a link from the existing blog posts (they already get SEO traffic).

The landing page is also an SEO target: "indie game creator network", "gaming creators open to review keys", "gaming YouTube channel directory".

---

## Implementation Notes

- **No authentication required** for creators to sign up — friction kills conversion
- Email confirmation is sent but not required (we still record the signup, just mark `email_verified = false`)
- Creators can edit their profile via a magic link (email → edit link, no password needed)
- The table is `creator_signups` in SQLite
- The route module is `app/routes/creators.py`
- Public-facing page at `/creators`
- Admin view of all signups at `/admin` (existing admin dashboard)
