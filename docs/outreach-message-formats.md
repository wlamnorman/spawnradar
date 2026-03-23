# Outreach Message Formats

This note turns the guidance in [blogpost1.md](/Users/wlam/code/spawnradar/blogpost1.md) and [blogpost2.md](/Users/wlam/code/spawnradar/blogpost2.md) into a product and implementation plan for SpawnRadar.

The main conclusion is simple:

- good outreach messages should come from a small set of structured formats
- most of the message should be deterministic and reusable
- LLM help is most valuable in the creator-specific hook, angle selection and tone adaptation
- fully freeform AI-written outreach is not the right default

## Product Goal

SpawnRadar should not try to be a magic email writer. It should help users send messages that are:

- short
- specific
- honest
- grounded in real creator research
- easy to review quickly before sending

The product value is not "AI writes a perfect email." The value is:

1. find strong-fit creators
2. surface the evidence for that fit
3. generate a message in a format that matches the contact context
4. let the developer review and send without starting from a blank page

## Core Product Principle

We should separate:

- `format`
- `facts`
- `personalization`

That means every draft should be assembled from:

1. a format type
2. trusted game facts
3. trusted creator facts
4. optional personalized language

This is better than one large prompt because it reduces hallucination, keeps messages short and makes the drafts easier to validate.

## Formats We Should Support

We do not need dozens of formats. We need a few high-quality ones.

### 1. Creator Outreach Email

This should be the default for YouTube creators and other creators with a visible business email.

Structure:

1. subject line
2. greeting
3. one-sentence creator-specific hook
4. one- or two-sentence game pitch
5. clear offer
6. trailer link
7. press kit link
8. short signoff

Constraints:

- under 200 words in the body
- one concrete reason for the fit
- one clear ask
- no long backstory about the developer
- no more than two links in the body by default

Recommended shape:

```text
Subject: [Game Name] - [genre] game, key available for [Creator Name]

Hi [Name],

[Specific reason this creator was chosen.]

I'm reaching out about [Game Name], a [genre] game about [premise]. [One differentiator and release timing.]

I'd be happy to send over a key. No coverage obligation if it's not a fit.

Trailer: [link]
Press kit: [link]

Happy to answer any questions.

[Sender]
```

### 2. Streamer Outreach Email

This is similar to creator email, but the hook and pitch should emphasize live suitability.

Structure differences:

- creator-specific hook references stream moments, chat interaction, tension, replayability, or short-session loops
- game pitch includes why it works live
- optional line offering availability for questions during stream

This should only be selected when the platform or evidence suggests live content matters.

### 3. Short Contact / DM Format

Some creators have a business form, social DM, or other constrained channel where a full email is too long.

This is not just a shorter email. It should be a separate format.

Structure:

1. greeting
2. very short creator-specific hook
3. one-sentence game pitch
4. offer
5. one link
6. optional follow-up line

Constraints:

- 60-100 words
- one link only
- no press kit and trailer together unless the channel clearly supports it

This format matters because many good opportunities will not be classic email outreach.

### 4. Community / Forum Post

This is a different product surface and should not be treated as creator outreach with a different greeting.

Structure:

1. title
2. opener establishing context honestly
3. game description
4. "why I made this" line
5. specific relevance to the community
6. links
7. invitation for discussion

Constraints:

- must sound like sharing, not pitching
- must not fake prior participation
- should be grounded in community norms

This should be a distinct draft type in the product because it serves a different job.

### 5. Follow-Up Message

This should be built explicitly, not improvised by the user.

Structure:

1. short reminder
2. mention original message date or topic
3. restate offer briefly
4. no pressure

Constraints:

- under 60 words
- only one follow-up draft by default
- only available after a time delay, not immediately

## Recommended Draft Schema

Right now a draft is mostly `subject_line` plus `body_text`. That is enough to send a message, but not enough to build a strong drafting product.

The drafting layer should think in terms of structured fields like:

- `format_type`
- `channel_type`
- `subject_line`
- `greeting`
- `personalized_hook`
- `game_pitch`
- `offer_line`
- `links`
- `signoff`
- `follow_up_variant`
- `supporting_evidence`
- `warnings`

Why this matters:

- the UI can show users where the personalization actually is
- validation becomes easier
- regeneration can target only one part, such as the hook
- the system can fall back cleanly if evidence is weak

The user experience should feel like reviewing a composed message, not staring at an opaque AI paragraph.

## Evidence Requirements

The blogs are clear on this point: the message only works if the specific reference is real.

So personalization should only happen when we have evidence like:

- recent video titles
- recent stream titles
- recent post text
- genre overlap
- platform overlap
- format overlap
- a known public contact channel

Recommended rule:

- only generate a creator-specific hook if the system has at least one concrete recent content signal
- if the evidence is weak, fall back to a lighter but still honest line such as "Your channel regularly covers tactics and strategy games"
- never fabricate a specific reference to a video, stream, or opinion

This is one of the places where SpawnRadar can be stricter than a raw LLM.

## Deterministic vs LLM-Generated Content

The right system is hybrid.

### Deterministic Parts

These should be assembled from stored game and prospect data:

- subject line skeleton
- greeting
- genre and premise sentence
- release timing
- offer language
- links
- signoff

These are formulaic and that is fine. The user does not need AI to rewrite "Trailer: [link]".

### LLM-Helpful Parts

This is where model assistance can materially improve quality:

- the creator-specific opener
- choosing the best differentiator for this creator
- adapting the pitch for archive-first vs live-first content
- compressing the message so it reads naturally rather than mechanically
- rewriting a draft in a user's preferred tone without losing the facts

This is the 20 percent of the message that contains most of the product magic.

### Parts LLMs Should Not Invent

- whether the creator covered a specific game if we do not have evidence
- release dates
- key availability
- multiplayer claims
- creator preferences we have not observed
- prior relationship language

## Recommendation: Do Not Generate Entire Messages From Scratch

A fully freeform prompt will look impressive in demos, but it has several product problems:

- harder to validate
- easier to hallucinate
- harder to keep concise
- harder to explain to users why the message looks the way it does
- harder to edit partially

The better pattern is:

1. select the format
2. fill the stable sections deterministically
3. ask the LLM only for the personalized hook and maybe one rewritten full-body pass
4. validate length and factual grounding
5. show the evidence next to the draft

## What LLM Personalization Could Improve

Used well, LLM assistance could improve the product materially.

The likely gains are:

- higher perceived quality of drafts
- better fit between creator style and message tone
- fewer robotic messages
- more confidence from the user that the draft is worth sending
- better adaptation across YouTube, Twitch, Bluesky, forums and future channels

The biggest improvement is probably not raw wording quality. It is the ability to convert structured evidence into a sentence that sounds like a human actually watched the creator's content.

That is exactly where templates tend to feel weak.

## What LLM Personalization Probably Will Not Fix

It will not rescue:

- weak creator targeting
- bad release timing
- no press kit
- no trailer
- unclear offer
- bad game positioning

This matters product-wise. SpawnRadar should not oversell AI drafting as the main value. Discovery quality and evidence quality still matter more.

## Cost vs Value

The rough tradeoff looks favorable if we use LLM assistance narrowly.

Inference based on the current semantic scoring setup in [app/scoring/llm_engine.py](/Users/wlam/code/spawnradar/app/scoring/llm_engine.py#L1):

- cheap models are already viable for per-prospect scoring
- message drafting prompts will likely be somewhat longer than scoring prompts
- but drafting only needs to happen for shortlisted prospects, not every candidate

So the right comparison is not "LLM cost per run." It is "LLM cost per reviewed draft that a user actually cares about."

That makes the economics much better.

Recommended cost-control strategy:

- no LLM drafting during broad ingestion
- only draft for queued items
- only personalize the top `N` drafts automatically
- cache generated drafts unless the user explicitly regenerates
- let users request a stronger rewrite on demand

This is likely cheap enough to include in a paid plan and probably premium enough to help justify Pro.

## Recommended Packaging

### Basic

- structured deterministic outreach drafts
- format selection by contact context
- editable subject and body
- one basic variant per prospect

### Pro

- AI-personalized hook
- tone rewrite options
- channel-specific format adaptation
- regenerate draft
- alternate subject lines
- follow-up draft generation

This is a good Pro feature because it is easy to understand and directly tied to user-visible output.

## Product Risks

### 1. False personalization

This is the biggest risk. If the AI sounds specific but is wrong, the draft becomes worse than a generic template.

Mitigation:

- ground hooks in stored evidence only
- show the evidence next to the draft
- allow the user to see which recent title or post the hook came from

### 2. Overly polished spam

A system that makes it too easy to blast many creators can hurt product reputation and user outcomes.

Mitigation:

- keep drafts concise and evidence-based
- encourage user review
- track outcomes
- avoid language that sounds mass-produced or manipulative

### 3. Too many formats too early

This can make the product messy.

Mitigation:

- start with creator email
- add streamer variant
- add forum/community post as a separate draft family
- add short-form / DM later

## Suggested Product Flow

1. discovery surfaces strong-fit prospects
2. queue item shows fit evidence and recent content
3. user clicks `Generate draft`
4. system chooses format based on platform and contact channel
5. deterministic scaffold is assembled
6. optional LLM personalization generates the hook and final polish
7. validation checks run:
   - length
   - link count
   - factual fields present
   - no unsupported claims
8. user reviews and edits
9. system stores the sent draft and later offers one follow-up

## What We Should Build First

### Phase 1

- one strong creator email format
- deterministic assembly from game + creator data
- short evidence-backed personalized hook if possible
- otherwise safe generic opener

This gets most of the value quickly.

### Phase 2

- streamer-specific variant
- short-form contact variant
- follow-up format
- tone options such as `more direct` or `more warm`

### Phase 3

- community/forum post drafts
- cross-channel adaptation
- advanced AI rewrite and subject-line variants

## Concrete Recommendation

If we want strong message quality without overengineering the first version:

1. build a format registry with `creator_email`, `streamer_email`, `short_contact` and later `community_post`
2. assemble most fields deterministically
3. use LLMs only for the hook and optional polish
4. require evidence for any specific creator reference
5. make AI personalization a Pro feature

That is the best balance of product quality, trust and cost.
