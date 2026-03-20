"""Blog post data and routes."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

router = APIRouter()

# ---------------------------------------------------------------------------
# Post registry — add new posts here, body_html is the rendered content.
# The source-of-truth markdown lives in blogpost*.md at the repo root.
# ---------------------------------------------------------------------------

_POSTS: list[dict] = [
    {
        "slug": "indie-developer-creator-outreach-checklist",
        "title": "The Indie Developer's Checklist for Contacting Content Creators",
        "date": "2026-03-20",
        "read_time": "5 min read",
        "excerpt": (
            "Most developer outreach fails before the email is even opened. "
            "Here is the checklist we use to make sure everything is in place "
            "before a single message gets sent."
        ),
        "body_html": """
<p>You finished your game. Now you need people to actually see it.</p>
<p>Content creators — YouTubers, Twitch streamers, short-form video makers — are one of the few channels that can move the needle for an indie game in a meaningful way. A single well-placed video from the right creator can generate more wishlists than a month of social posting. But most developers approach outreach without a system, send generic emails, and wonder why nobody responds.</p>
<p>This guide gives you the checklist we use at SpawnRadar to evaluate outreach readiness before a single message gets sent.</p>

<hr>

<h2>Before You Contact Anyone</h2>
<p>These are not optional. If you skip them, you are wasting your time and burning goodwill.</p>

<h3>✅ Your press kit is ready</h3>
<p>Creators make thumbnails. Thumbnails need assets. If you don't give creators the right raw materials, they either skip your game or produce a thumbnail that undersells it — which means fewer clicks, which means less value for both of you.</p>
<p>Your press kit should include:</p>
<ul>
  <li><strong>Key art</strong> — high resolution, ideally with the character isolated on a transparent background so it can be composited into thumbnails</li>
  <li><strong>Logo</strong> — clean, no drop shadows baked in, with and without background</li>
  <li><strong>Gameplay screenshots</strong> — actual gameplay, not cutscenes, at least 1920×1080</li>
  <li><strong>A trailer</strong> — gameplay-first, under 90 seconds, with the most interesting 10 seconds in the first 10 seconds</li>
  <li><strong>A short factsheet</strong> — release date, platform, genre, one-line description, your contact info</li>
</ul>
<p>If your assets are on a Google Drive folder, make sure it is set to anyone-with-link. Creators will not request access.</p>

<h3>✅ You have keys ready to send</h3>
<p>Do not reach out if you cannot immediately send a key when a creator says yes. Asking someone to wait kills momentum. More importantly, if you reach out to twenty creators and ten respond the same week, you need to be able to fulfill all of them.</p>
<p>Use Keymailer, Woovit, or Lurkit if you want to batch this. But for direct outreach — which works better — just be ready to send keys manually.</p>

<h3>✅ You know your release window</h3>
<p>Timing matters. The rough principle:</p>
<ul>
  <li><strong>More than 4 weeks out:</strong> too early for most creators to commit, but fine for awareness outreach</li>
  <li><strong>2–4 weeks out:</strong> ideal window for requesting coverage timed to launch</li>
  <li><strong>Less than 1 week out:</strong> too late unless you are offering day-one keys with no expectations</li>
</ul>
<p>For games with low replay value, send keys 3–5 days before launch so creators can play and publish close to release. For high-replay games — roguelikes, strategy, sandbox — earlier access builds more genuine enthusiasm.</p>

<h3>✅ Your music is YouTube-safe</h3>
<p>This is a common and costly oversight. If your game uses licensed music with an active Content ID claim, a creator's video will be demonetized or muted the moment they upload it. Creators who have been burned by this before will simply not cover your game.</p>
<p>Check every track. If anything is questionable, either get a license that covers third-party YouTube use or swap the track.</p>

<hr>

<h2>Finding the Right Creators</h2>

<h3>Target genre first, size second</h3>
<p>The biggest mistake developers make is going straight for subscriber count. A 500K gaming channel that covers AAA action games is less useful to you than a 15K channel that exclusively covers puzzle games and posts every week.</p>
<p>Search YouTube for your closest genre comparisons. Look at who has covered those games recently. Those creators already have an audience pre-qualified for your game.</p>

<h3>Size ranges to think about</h3>
<table>
  <thead><tr><th>Tier</th><th>Subscriber Range</th><th>Notes</th></tr></thead>
  <tbody>
    <tr><td>Micro</td><td>1K – 20K</td><td>High response rate, genuine enthusiasm, loyal communities</td></tr>
    <tr><td>Mid</td><td>20K – 150K</td><td>Best balance of reach and response rate</td></tr>
    <tr><td>Large</td><td>150K – 500K</td><td>Much lower response rate, but worth trying if the fit is perfect</td></tr>
    <tr><td>Major</td><td>500K+</td><td>PR agencies or strong personal connections only</td></tr>
  </tbody>
</table>
<p>Do not dismiss micro creators. They are often the most thorough, the most responsive, and the most likely to build a long-term relationship with a game they love.</p>

<h3>Verify before you send</h3>
<p>Scammers exist. Before sending a key to anyone unfamiliar, check:</p>
<ul>
  <li>Do they have a history of actually publishing videos about indie games?</li>
  <li>Is their channel active and growing, or dormant?</li>
  <li>Does their engagement look real relative to their subscriber count?</li>
</ul>

<hr>

<h2>The Outreach Checklist</h2>

<p><strong>Preparation</strong></p>
<ul>
  <li>Press kit is complete and publicly accessible</li>
  <li>Keys are ready to send immediately upon request</li>
  <li>Release date is confirmed or at least narrowed to a week</li>
  <li>Music licensing is confirmed YouTube-safe</li>
</ul>

<p><strong>Creator selection</strong></p>
<ul>
  <li>This creator has covered games similar to mine in the last 3 months</li>
  <li>I have watched at least one of their recent videos before writing to them</li>
  <li>Their audience size is realistic for direct outreach (under 500K)</li>
  <li>Their engagement looks genuine</li>
</ul>

<p><strong>The message itself</strong></p>
<ul>
  <li>I addressed them by the name they actually go by</li>
  <li>I explained why I specifically chose them — not just "I love your content"</li>
  <li>I included a link to a trailer, not just text describing the game</li>
  <li>I included a link to the press kit</li>
  <li>I made the ask clear — am I offering a key? Requesting coverage? Both?</li>
  <li>I kept it under 200 words in the body</li>
  <li>I did not BCC multiple creators on the same email</li>
</ul>

<p><strong>After sending</strong></p>
<ul>
  <li>I logged who I contacted, when, and what I sent</li>
  <li>I have a reminder set to follow up once if I don't hear back within 10–14 days</li>
  <li>I am not sending more than one follow-up</li>
</ul>

<hr>

<h2>The Mistakes Worth Highlighting</h2>
<p><strong>Reaching out publicly.</strong> Posting on Twitter "hey @CreatorName check out my game!" is almost always a mistake unless you have a prior relationship.</p>
<p><strong>Contacting during bad timing windows.</strong> Avoid launching or reaching out during major Steam sales, Nintendo Directs, major game releases in your genre, and summer or holiday content droughts.</p>
<p><strong>Sending the same email to twenty people at once.</strong> Creators talk to each other. Generic blasts get noticed and remembered for the wrong reasons.</p>
<p><strong>Treating a non-response as a rejection.</strong> Creators get dozens of pitches a week. A non-response usually means they didn't see it, not that they declined. One polite follow-up after two weeks is fine.</p>

<hr>

<h2>A Note on Scale</h2>
<p>Doing this well takes time. Researching creators, personalising messages, tracking responses — it adds up fast when you are also trying to ship a game.</p>
<p>This is the problem SpawnRadar is built to solve. We surface creators who are a strong genre and audience fit for your specific game, score them against your profile, and draft outreach messages you can review and send. The research step gets compressed from hours to minutes.</p>
<p>If you want to try it, <a href="/auth/register">start a free trial here</a>.</p>
""",
    },
    {
        "slug": "creator-outreach-message-templates",
        "title": "How to Write Creator Outreach Messages That Actually Get Read",
        "date": "2026-03-20",
        "read_time": "6 min read",
        "excerpt": (
            "Most outreach emails for indie games get deleted in under five seconds. "
            "Here is the structure that works — and three templates you can start using today."
        ),
        "body_html": """
<p>Most outreach emails for indie games get deleted in under five seconds.</p>
<p>Not because creators are dismissive. Because most emails look identical: a long paragraph about how much work went into the game, a vague description of the genre, and a request for coverage that offers nothing specific to that creator.</p>
<p>This guide breaks down the structure of a message that actually gets read, with templates for YouTube, streaming, and community outreach.</p>

<hr>

<h2>Why Most Pitches Fail</h2>
<p><strong>They are not personalised.</strong> Saying "I love your content" without referencing anything specific signals immediately that you sent the same message to fifty people.</p>
<p><strong>They lead with the developer, not the creator.</strong> The first paragraph is often about how long the game took to make, or how passionate the team is. The creator does not know you. They need a reason to care about your game before they care about you.</p>
<p><strong>They are too long.</strong> A creator opening email between videos is not going to read four paragraphs. They will read the first two sentences and decide.</p>
<p><strong>The ask is unclear.</strong> Ending with "let me know what you think!" is not an ask. Creators want to know exactly what you are offering and what you are requesting.</p>

<hr>

<h2>The Structure That Works</h2>
<p>A high-performing outreach message has five components, in this order:</p>
<ol>
  <li><strong>Their name</strong> — correct and specific</li>
  <li><strong>Why you chose them specifically</strong> — one sentence, referencing their actual content</li>
  <li><strong>What the game is</strong> — genre, premise, one hook sentence</li>
  <li><strong>The offer</strong> — what you are giving them (key, press access, exclusive window)</li>
  <li><strong>The links</strong> — trailer and press kit, nothing else</li>
</ol>
<p>The whole thing should be readable in 20–30 seconds. If it is not, cut it until it is.</p>

<hr>

<h2>Template 1: YouTube Channel Outreach</h2>

<div class="blog-template-block">
<p><strong>Subject:</strong> [Game Name] — [Genre] game, key available for [Channel Name]</p>
<p>Hi [Creator Name],</p>
<p>Watched your recent video on [specific game they covered] — your breakdown of [something specific] was exactly the kind of coverage I was hoping to find.</p>
<p>I'm reaching out about [Game Name], a [genre] game about [one-sentence premise]. It's [one clear differentiator]. Releases [date / "this month"].</p>
<p>I'd love to offer you a key. No coverage obligation — if it's not a fit for your channel, no worries at all.</p>
<p>Trailer: [link]<br>Press kit: [link]</p>
<p>Happy to answer any questions.<br>[Your name] · [Studio name] · [Email]</p>
</div>

<p>The subject line includes the channel name — this signals immediately that the email is not a blast, and makes it easy to find later. The reference to a specific video is the most important sentence. It needs to be real. Creators can tell when someone watched something versus when someone read the title.</p>
<p>"No coverage obligation" lowers friction significantly. It reframes the email from a transaction to a genuine offer.</p>

<hr>

<h2>Template 2: Twitch Streamer Outreach</h2>
<p>Streamers think differently than YouTubers. Streaming is live-first — the value is in the moment and in clips. Adjust accordingly.</p>

<div class="blog-template-block">
<p><strong>Subject:</strong> [Game Name] — live-friendly [genre], key for [Channel Name]</p>
<p>Hey [Creator Name],</p>
<p>I've been watching your streams of [specific genre or game] — the way your chat reacts to [specific moment type] made me think [Game Name] could be a strong fit.</p>
<p>[Game Name] is a [genre] game that [one-sentence premise]. It's designed to [one thing that makes it good for streaming — e.g. "generate strong chat moments", "has short sessions that work well between breaks", "has a clear tension arc per run"].</p>
<p>Key available now, no strings attached. Happy to be available during a stream if you have questions.</p>
<p>Trailer: [link]<br>Press kit: [link]</p>
<p>[Your name] · [Email]</p>
</div>

<p>The "designed to [streaming quality]" line matters a lot. Streamers are always thinking about how a game will feel for their audience in real time. Tell them explicitly why it will work live.</p>

<hr>

<h2>Template 3: Community Post</h2>
<p>When posting in a subreddit, Discord, or forum, the format is different. You are not pitching — you are sharing. It should feel like a member of the community, not an ad.</p>

<div class="blog-template-block">
<p><strong>Title:</strong> I made a [genre] game for people who like [specific reference point] — would love feedback from this community</p>
<p>Hey everyone,</p>
<p>I've been lurking in [community name] for a while and wanted to share something I've been working on.</p>
<p>[Game Name] is a [genre] game that [one-sentence premise]. I built it because [genuine reason relevant to this community].</p>
<p>It's [release status — demo available / launching soon / just launched]. [One thing that's specifically relevant to this community's interests.]</p>
<p>Demo / store page: [link]<br>Trailer: [link]</p>
<p>Happy to answer questions about the design, the development, anything. Genuinely interested in feedback from people in this community.</p>
</div>

<p>Community posts live or die by authenticity. The "I built it because" line is the most important — it gives the community a reason to care that is rooted in shared taste, not marketing.</p>
<p>Do not post and disappear. Reply to comments. This is what turns a one-time spike into ongoing community presence.</p>

<hr>

<h2>What Actually Needs to Change Per Message</h2>
<p>Most of the body can stay the same across contacts. What must change:</p>
<ul>
  <li><strong>The creator's name</strong> — double-check the spelling</li>
  <li><strong>The specific video or content reference</strong> — this is non-negotiable</li>
  <li><strong>The subject line</strong> — include their channel name or handle</li>
  <li><strong>The streaming-specific hook</strong> — if contacting a streamer vs. a YouTuber</li>
</ul>
<p>Everything else — the game description, the offer, the links — can be templated.</p>

<hr>

<h2>After You Send</h2>
<p>Keep a simple log. A spreadsheet is fine. One follow-up after 10–14 days is fine. Keep it short:</p>
<div class="blog-template-block">
<p>"Hey [name], just following up on my message from [date] about [Game Name]. Happy to send a key if you're interested — no pressure either way."</p>
</div>
<p>That is all. Do not send a third message. Move on.</p>

<hr>

<h2>How SpawnRadar Helps</h2>
<p>The hardest part of outreach is not the templates — it is knowing who to contact in the first place, and then keeping track of it all.</p>
<p>SpawnRadar surfaces creators who match your game's genre and audience profile, scores them so you know where to spend your time, and generates personalised draft messages you can review and edit before sending.</p>
<p><a href="/auth/register">Start a free trial</a> and run your first discovery in a few minutes.</p>
""",
    },
    {
        "slug": "game-press-kit-for-creators",
        "title": "How to Build a Game Press Kit That Creators Actually Use",
        "date": "2026-03-20",
        "read_time": "6 min read",
        "excerpt": (
            "A press kit isn't about impressing journalists. "
            "It's about making a creator's job easier — and most developers "
            "get the format wrong in ways that cost them coverage."
        ),
        "body_html": """
<p>A press kit is not about impressing journalists. It is about making a creator's job easier.</p>
<p>When a YouTuber or streamer decides to cover your game, they immediately need a thumbnail image, a logo, footage or screenshots, and enough information to write a description and title. If any of those are hard to find or the wrong format, they improvise — and the result is a thumbnail that undersells your game, a title that doesn't match your genre, and coverage that drives fewer clicks than it could have.</p>

<hr>

<h2>What Belongs in a Press Kit</h2>

<h3>Key Art</h3>
<p>This is the most important asset. Creators who make YouTube thumbnails composite your character or game imagery against a custom background. What they need:</p>
<ul>
  <li><strong>Transparent PNG of your main character or key visual</strong> — no background, no drop shadow baked in, no hard edge antialiasing that will look bad on a colored background</li>
  <li><strong>Horizontal banner version</strong> — a wide crop that works for YouTube channel art and stream overlays</li>
  <li><strong>At least 2000px on the longest edge</strong> — most thumbnails render at 1280×720, but creators work larger to maintain quality when cropping</li>
</ul>
<p>If you only have a flat key art image with a background, that is significantly less useful. Many developers provide both the full composition and an isolated character layer.</p>

<h3>Logo</h3>
<p>Provide your logo in at least three variants:</p>
<ul>
  <li>Full color on transparent background (PNG)</li>
  <li>White on transparent background (for dark backgrounds)</li>
  <li>Dark on transparent background (for light backgrounds)</li>
</ul>
<p>Avoid logos with drop shadows or complex gradients built in — these look wrong when placed over arbitrary backgrounds. Flat or simple logos composite far better.</p>

<h3>Screenshots</h3>
<p>Rules:</p>
<ul>
  <li><strong>Actual gameplay, not cutscenes or menus</strong> — creators need to show viewers what the game feels like to play</li>
  <li><strong>1920×1080 minimum</strong>, 4K if available</li>
  <li><strong>At least 5 screenshots</strong>, covering different environments, situations, or mechanics</li>
  <li><strong>No debug overlays, no watermarks</strong></li>
</ul>
<p>One screenshot should be a "hero shot" — your strongest image, the one that best communicates what makes your game interesting.</p>

<h3>Trailer</h3>
<p>Every press kit needs a trailer link. The link should go directly to the video, not to a page that requires login or approval.</p>
<p>What makes a trailer work for creator purposes:</p>
<ul>
  <li><strong>Gameplay in the first 5 seconds</strong> — creators use your trailer to decide quickly whether to cover you</li>
  <li><strong>No intro logo animations</strong> — cut them or move them to the end</li>
  <li><strong>Under 90 seconds</strong> — for a game that isn't out yet, 60–75 seconds is ideal</li>
  <li><strong>Music that matches the game's tone</strong> — and confirm that music is royalty-free or licensed for third-party YouTube use before sending</li>
</ul>
<p>If your trailer contains any music with active Content ID claims, it may cause a creator's video to be demonetized. Check every track before including the trailer in outreach.</p>

<h3>Factsheet</h3>
<p>A factsheet is a single short document or section with structured information. This is what gets copy-pasted into video descriptions and tweets. Keep it factual and concise:</p>
<ul>
  <li>Game name, developer, genre</li>
  <li>Platform, release date, price</li>
  <li>Store page link and contact email</li>
</ul>

<hr>

<h2>How to Host It</h2>

<h3>Google Drive or Dropbox</h3>
<p>The simplest option. Create a folder, add all assets, and set the folder to <strong>Anyone with the link can view</strong>.</p>
<p>The single most common mistake: creators click the link and hit an access request screen because the developer forgot to change the sharing settings. Test this yourself in a private browser window before sending.</p>

<h3>A Dedicated Press Kit Page</h3>
<p>If you have a website, a dedicated <code>/presskit</code> page is more professional. The open-source tool <a href="https://github.com/pixelnest/presskit.html">presskit()</a> generates a static page from a simple config file. The advantage over a Drive folder is that you can update assets without breaking links.</p>

<hr>

<h2>Common Mistakes</h2>
<p><strong>Assets that are too small.</strong> A 500px logo PNG is unusable for any professional-looking thumbnail. When in doubt, bigger.</p>
<p><strong>Everything zipped.</strong> A single ZIP is fine as a download option, but also provide direct access to individual assets. Creators on mobile may not want to download everything.</p>
<p><strong>No contact information in the kit itself.</strong> If someone finds your press kit without your email, they should still be able to reach you.</p>
<p><strong>Screenshots that are all the same situation.</strong> Five screenshots of the combat system doesn't give creators a sense of the full game. Include variety.</p>
<p><strong>A trailer that starts with a 5-second logo animation.</strong> Your strongest imagery goes first.</p>

<hr>

<h2>The Pre-Outreach Checklist</h2>
<ul>
  <li>Key art includes a transparent PNG of the main character or visual</li>
  <li>Logo provided in at least two variants (dark and light)</li>
  <li>At least 5 gameplay screenshots at 1920×1080 or higher</li>
  <li>Trailer is publicly accessible without login</li>
  <li>Trailer music is confirmed royalty-free or YouTube-licensed</li>
  <li>Factsheet includes genre, platform, release date, and contact email</li>
  <li>Google Drive folder is set to anyone-with-link</li>
  <li>Link tested in a private browser to confirm access works</li>
</ul>

<hr>

<p>SpawnRadar helps you discover which creators are the right fit for your game — but the press kit is what closes the deal once they're interested. <a href="/auth/register">Start a free trial</a> and run your first creator discovery today.</p>
""",
    },
    {
        "slug": "how-to-evaluate-youtube-channels",
        "title": "How to Evaluate a YouTube Channel Before Reaching Out",
        "date": "2026-03-20",
        "read_time": "6 min read",
        "excerpt": (
            "Subscriber count is the wrong metric. Here's what to actually look at "
            "when deciding whether a creator is worth contacting — and the red flags "
            "that tell you to move on."
        ),
        "body_html": """
<p>Most developers find a channel, see a subscriber count, and send an email.</p>
<p>This is the wrong order of operations. Subscriber count is close to the least useful signal when evaluating whether a creator is worth contacting. A channel with 80,000 subscribers that covers your genre every week is far more valuable than a 400,000-subscriber channel that covered one similar game two years ago.</p>

<hr>

<h2>The Signals That Actually Matter</h2>

<h3>Recent genre fit</h3>
<p>The most important question: has this creator covered games meaningfully similar to mine in the last 60–90 days? Not "do they ever play indie games" — but have they recently covered something with the same genre, tone, or audience profile as your game? A creator who covered five puzzle games last month is a warm lead. A creator who covered one roguelike two years ago is not.</p>
<p>Check their upload history, not just their channel description. Channels drift over time. A creator who built their audience on survival games might now be focused on MOBAs. The history tells you what they actually make.</p>

<h3>View-to-subscriber ratio on relevant videos</h3>
<p>A channel's total subscriber count matters far less than how many views their gaming content actually gets. Look at their last 10 videos and calculate the rough average view count. Then compare it to their subscriber count.</p>
<p>Healthy ratios for gaming channels in general:</p>
<ul>
  <li><strong>Micro channels (1K–20K):</strong> 20–80% view-to-sub ratio is common</li>
  <li><strong>Mid channels (20K–150K):</strong> 5–25%</li>
  <li><strong>Large channels (150K–500K):</strong> 1–8%</li>
</ul>
<p>A 300K channel averaging 8,000 views per video has an audience that is not actively engaged. A 25K channel averaging 15,000 views per video has an unusually active one. Views drive discoverability — a video that gets watched generates YouTube recommendations; one that gets 1% engagement gets buried.</p>

<h3>Upload frequency</h3>
<p>An active creator posts at least every two to three weeks. Look at the gap between the last five videos. Frequency matters because active creators are more likely to be checking email, and because their audience expects new content regularly — a video from an active creator gets seen within days of posting.</p>

<h3>Comment quality and engagement</h3>
<p>Open three or four recent videos and read the comments. This takes three minutes and tells you a lot. Are there comments from real people discussing the game? Does the creator reply? Do the comments reflect genuine engagement ("I tried this game after watching and it's great") or is it mostly emoji and generic praise?</p>
<p>A creator with 50,000 subscribers and 200 thoughtful comments per video has a better relationship with their audience than one with 200,000 subscribers and 40 bot-adjacent comments. The former community will actually act on a recommendation.</p>

<h3>Audience buying habits</h3>
<p>Check whether their gaming content overlaps with your game's price point. A creator who primarily covers free-to-play mobile games is playing to a different economic profile than one covering $20–$30 Steam indie games. Even if the genre fits, the audience's buying habits may not.</p>

<hr>

<h2>Red Flags to Filter Out</h2>
<p><strong>Ghost channels.</strong> A channel with 50K subscribers and 200 views per video has almost certainly bought followers, lost their audience, or abandoned the niche.</p>
<p><strong>Key collectors.</strong> Some smaller channels request keys consistently but rarely publish, or publish very low-quality content clearly not aimed at discovery. Signs: irregular post history, videos under 2 minutes, very low comment engagement.</p>
<p><strong>Wrong-audience channels.</strong> A gaming news and commentary channel is not the same as one that plays and reviews games. The former audience is interested in the industry; the latter is looking for new games to play.</p>
<p><strong>Dormant channels.</strong> If the last video was more than two months ago with no announcement of a break, treat the channel as inactive.</p>

<hr>

<h2>What to Look for in the Video Itself</h2>
<p>Before contacting any creator, watch at least one of their recent videos in your genre, from start to finish. This gives you the specific reference you need for a personalised email — and tells you what kind of coverage they produce.</p>
<p>Ask yourself:</p>
<ul>
  <li>Do they play and react, or do they script and review?</li>
  <li>How long do they play before forming an opinion?</li>
  <li>Do they highlight what is interesting about a game, or do they narrate gameplay?</li>
  <li>Would your game look good in their format?</li>
</ul>
<p>A creator who spends 40 minutes methodically exploring a game is a different fit from one who does a 10-minute highlight reel. Neither is better — but one may be a better fit for your specific game.</p>

<hr>

<h2>The Evaluation Checklist</h2>
<p>Before adding any creator to your outreach list, verify:</p>
<ul>
  <li>They have covered games in my genre within the last 60 days</li>
  <li>Their view-to-subscriber ratio on gaming content is healthy</li>
  <li>They have posted at least twice in the last six weeks</li>
  <li>Comment engagement looks genuine, not bot-driven</li>
  <li>I have watched at least one recent video in my genre end to end</li>
  <li>I have a specific reference from that video for my outreach message</li>
  <li>Their audience appears to buy games in my price range</li>
  <li>The channel is not dormant</li>
</ul>

<hr>

<p>Doing this evaluation manually for twenty or thirty creators is a significant time investment. SpawnRadar runs this analysis automatically — scoring channels against your game's genre, audience profile, and activity signals so you can focus on the creators who are already a strong fit. <a href="/auth/register">Start a free trial</a> and run your first creator discovery in a few minutes.</p>
""",
    },
    {
        "slug": "best-subreddits-for-indie-games",
        "title": "The Best Subreddits to Share Your Indie Game (And How to Do It Right)",
        "date": "2026-03-20",
        "read_time": "5 min read",
        "excerpt": (
            "Reddit is one of the most effective free channels for indie game visibility — "
            "and one of the easiest to get wrong. Here's which communities work "
            "and how to post without looking like spam."
        ),
        "body_html": """
<p>Reddit is one of the most effective free channels for indie game visibility — and one of the easiest to get wrong.</p>
<p>Done well, a single post in the right subreddit can drive thousands of page views, genuine feedback, and a real boost to your wishlist. Done badly, it looks like spam, gets removed, and damages your credibility in communities you'll want access to for years.</p>

<hr>

<h2>The Subreddits Worth Your Time</h2>

<h3>r/gamedev (2.1M members)</h3>
<p>The largest general indie game development community on Reddit. Most members are developers, not players — so this is the place to share process, lessons, and devlogs, not to market a finished product.</p>
<p><strong>What works:</strong> Behind-the-scenes posts about development decisions, technical breakdowns, or "what I learned shipping my first game." A GIF or short video showing something interesting about your game's development, with a few paragraphs of genuine context.</p>
<p><strong>What doesn't work:</strong> "Hey everyone, my game just launched on Steam!" with a store link.</p>

<h3>r/indiegaming (240K members)</h3>
<p>Primarily players, not developers. Members here are actively looking for games to play. A completed or near-completed game can get real traction here.</p>
<p><strong>What works:</strong> Gameplay GIFs, trailers, or screenshots with a genuine developer pitch. "I spent three years making this — here's what it looks like" performs far better than a store link with no context.</p>
<p><strong>What doesn't work:</strong> Posts that read like press releases.</p>

<h3>r/indiegames (420K members)</h3>
<p>Similar audience to r/indiegaming but slightly more open to developer posts. The community tends to be generous with feedback. Demo announcements, gameplay reveals, and "just launched" posts with genuine developer context all work here.</p>

<h3>r/gamemarketing (28K members)</h3>
<p>A smaller community specifically for developers discussing marketing strategy. Share what you've learned, not your game directly. Case studies, data from your launches, and honest retrospectives perform well. "I emailed 50 creators — here's what worked and what didn't" will get genuine engagement.</p>

<h3>r/playmygame (116K members)</h3>
<p>Explicitly for promoting playable games. If you have a demo or a browser-playable version, this is one of the few subreddits where direct promotion is welcome. Link directly to the playable build, not a Steam wishlist page.</p>

<h3>Genre-specific subreddits</h3>
<p>Often overlooked, these can outperform general gaming subreddits for the right game:</p>
<table>
  <thead><tr><th>Genre</th><th>Subreddit</th></tr></thead>
  <tbody>
    <tr><td>Roguelikes / roguelites</td><td>r/roguelikes, r/roguelikedev</td></tr>
    <tr><td>Strategy</td><td>r/strategy, r/4Xgaming</td></tr>
    <tr><td>Horror</td><td>r/horrorgaming</td></tr>
    <tr><td>Puzzle</td><td>r/PuzzleGames</td></tr>
    <tr><td>Metroidvania / platformers</td><td>r/metroidvania</td></tr>
    <tr><td>RPG</td><td>r/JRPG, r/CRPG</td></tr>
    <tr><td>Simulation / tycoon</td><td>r/tycoon</td></tr>
  </tbody>
</table>
<p>A 15K-member subreddit full of people who love your exact genre will outperform a 500K-member general subreddit where you are noise.</p>

<hr>

<h2>How to Post Without Looking Like Spam</h2>

<h3>Read before you post</h3>
<p>Spend 15 minutes reading the top posts in any subreddit before you post. Look at what gets upvoted, what gets removed, and how successful developers frame their posts. Every community has its own tone.</p>

<h3>Check the rules</h3>
<p>Every major subreddit has rules about self-promotion frequency, link policies, and required flairs. r/gamedev requires self-promotion to be accompanied by substantial discussion. Breaking these rules results in removal without warning.</p>

<h3>Post as a developer, not a marketer</h3>
<p>The most effective Reddit posts from developers are honest. "I've been working on this for two years and today I finally released it" is not a marketing tagline — it's a human moment. Communities respond to it because it's real. Pick one thing that's genuine and specific. Don't try to cover all your game's features.</p>

<h3>Time your posts</h3>
<p>Reddit has peak traffic windows. In general:</p>
<ul>
  <li><strong>Best time:</strong> Tuesday through Thursday, 9am–2pm Eastern</li>
  <li><strong>Avoid:</strong> Late Friday through Sunday — you'll be buried</li>
</ul>

<h3>Reply to every comment</h3>
<p>The developers who get the most out of Reddit are the ones who treat it as a conversation. Reply to every comment, answer questions, thank people for feedback, engage with criticism thoughtfully. Communities notice developers who show up.</p>

<hr>

<h2>What to Expect</h2>
<p>A well-executed Reddit post in the right community can generate 1,000–10,000 profile views, 20–200 genuine wishlists, and direct feedback from players who are actually your target audience. It's not a substitute for creator outreach — but it's free, sustainable, and builds community presence that compounds over time.</p>

<hr>

<p>SpawnRadar surfaces the right YouTubers and streamers for your game so your Reddit effort builds community awareness while your outreach queue targets people who can generate real coverage. <a href="/auth/register">Try SpawnRadar free</a> and run your first creator discovery today.</p>
""",
    },
    {
        "slug": "creator-outreach-launch-timing",
        "title": "How to Time Your Creator Outreach for Maximum Launch Impact",
        "date": "2026-03-20",
        "read_time": "5 min read",
        "excerpt": (
            "The most common mistake in creator outreach is not the message — it's the timing. "
            "Here's the timeline that gets your game covered during the window that actually matters."
        ),
        "body_html": """
<p>The most common mistake in creator outreach is not the message — it is the timing.</p>
<p>Developers reach out too late, scramble to send keys the week of launch, and wonder why coverage trickles in after the algorithm has already moved on. Or they reach out too early, creators play the game and lose interest before launch, and the coverage lands at the wrong moment for wishlist conversion.</p>
<p>Getting timing right requires thinking through the process in reverse — starting with your launch date and working backwards.</p>

<hr>

<h2>Why Timing Matters So Much</h2>
<p>YouTube gaming coverage has a short half-life for discovery. A video published the week of launch, when your game is appearing in Steam's New Releases section, generates far more traffic than the same video published three weeks later. The algorithm and the coverage need to align.</p>
<p>Creators also have their own production schedules. A YouTuber who posts twice a week has content pre-planned days or weeks in advance. Asking them to drop their existing plan for a same-week key is asking them to do you a favour. Most won't. The ones who do often produce rushed content.</p>

<hr>

<h2>The Timeline That Works</h2>

<h3>6–8 weeks before launch: awareness outreach</h3>
<p>At this stage you are not asking for coverage. You are planting seeds with creators you have identified as strong fits. A short email introducing your game, a trailer link, a note that you are planning to send keys to a limited number of creators 3–4 weeks out. You are not asking for a commitment — you are letting them know you exist.</p>
<p>Why this works: creators see hundreds of keys arrive unannounced. A game they heard about in advance, from a developer who seemed thoughtful, is more likely to actually get played.</p>

<h3>3–4 weeks before launch: key distribution</h3>
<p>This is the primary outreach window. The email is short: you are launching on [date], you thought this creator was a strong fit based on [specific reason], here is a key with no coverage obligation, here is the press kit.</p>
<p>Three to four weeks gives creators time to work your game into their schedule without it feeling rushed. For high-replay-value games — roguelikes, strategy, sandbox — this is the minimum. For short narrative games, 1–3 weeks before launch is fine so the first-play experience is still fresh.</p>

<h3>1 week before launch: follow-up window</h3>
<p>If you sent keys 3–4 weeks ago and haven't heard back, one brief follow-up is appropriate. Keep it to two sentences:</p>
<div class="blog-template-block">
<p>"Hey [name], just wanted to check whether [Game Name] landed in your inbox — happy to resend the key if needed. Launch is [date]. No pressure either way."</p>
</div>
<p>Do not ask whether they plan to cover the game. Do not suggest a specific publish date. Just check in.</p>

<h3>Launch week: day-one key offers</h3>
<p>Some creators only cover games that are already out — they don't want to cover pre-release builds. Keep a short list of creators for day-one outreach. The message changes: you are not giving them lead time, you are giving them a chance to be among the first.</p>

<hr>

<h2>Platform-Specific Timing Adjustments</h2>
<table>
  <thead><tr><th>Platform</th><th>Lead time</th><th>Notes</th></tr></thead>
  <tbody>
    <tr><td>YouTube</td><td>3–4 weeks</td><td>Needs time to play, record, edit, schedule</td></tr>
    <tr><td>Twitch</td><td>1–2 weeks</td><td>No editing; streamers work on shorter notice</td></tr>
    <tr><td>Shorts / TikTok</td><td>1–2 weeks</td><td>Fast production cycle; timing less critical</td></tr>
  </tbody>
</table>

<hr>

<h2>What to Avoid</h2>
<p><strong>Reaching out during major releases in your genre.</strong> If a significant game in a similar genre launches the same week, creators will be focused on that. Check the Steam release calendar before setting your launch date.</p>
<p><strong>Launching during Steam sales.</strong> Major sale events dominate player attention. Launches close to sales events get less visibility both in creator content and organic discovery.</p>
<p><strong>Contacting during holidays.</strong> Many creators take time off in late December and in summer. A key sent during a break sits unopened.</p>
<p><strong>Setting tight embargo windows.</strong> Unless your game has a major story that needs protecting, avoid embargo agreements. They create overhead. A note saying "please don't publish before [date]" is usually sufficient.</p>

<hr>

<h2>Building a Launch Calendar</h2>
<p>A simple spreadsheet is enough:</p>
<table>
  <thead><tr><th>Creator</th><th>Key sent</th><th>Follow-up date</th></tr></thead>
  <tbody>
    <tr><td>[name]</td><td>[date]</td><td>[date +14 days]</td></tr>
    <tr><td>[name]</td><td>[date]</td><td>[date +14 days]</td></tr>
  </tbody>
</table>
<p>Track who you contacted, when, whether they responded, and when your follow-up window opens. This prevents the most common failure mode: contacting someone twice because you forgot you already reached out.</p>

<hr>

<p>SpawnRadar helps you build your outreach list before the timing pressure starts — so when your launch window opens, you know exactly who to contact and why. <a href="/auth/register">Start a free trial</a> and run your first discovery today.</p>
""",
    },
]

_POST_BY_SLUG = {p["slug"]: p for p in _POSTS}


@router.get("/blog")
async def blog_index(request: Request):
    session_id = request.cookies.get("session_id")
    user = None
    if session_id:
        user = request.app.state.auth_service.get_user_for_session(session_id)
    return request.app.state.templates.TemplateResponse(
        request,
        "marketing/blog.html",
        {"user": user, "posts": _POSTS},
    )


@router.get("/blog/{slug}")
async def blog_post(slug: str, request: Request):
    post = _POST_BY_SLUG.get(slug)
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")
    session_id = request.cookies.get("session_id")
    user = None
    if session_id:
        user = request.app.state.auth_service.get_user_for_session(session_id)
    return request.app.state.templates.TemplateResponse(
        request,
        "marketing/blog_post.html",
        {"user": user, "post": post},
    )
