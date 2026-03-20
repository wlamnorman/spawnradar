# SEO and Website Launch Preparation

This document covers what to fix before launch weekend and what to build toward over the first few months.

---

## 1. Meta Tags (fix this weekend)

Every public page needs a unique `<title>`, `<meta name="description">`, and Open Graph tags. Currently `base.html` only has a generic title block with no description or OG tags.

### Add to `base.html` `<head>`

```html
<!-- Default meta — override per-page via block -->
{% block meta_description %}
<meta name="description" content="SpawnRadar helps indie game developers find and contact the right YouTube creators, streamers, and communities for their game." />
{% endblock %}

<!-- Open Graph (controls how links look on social/Discord/Slack) -->
<meta property="og:site_name" content="SpawnRadar" />
<meta property="og:title" content="{% block og_title %}SpawnRadar — Find Creators For Your Indie Game{% endblock %}" />
<meta property="og:description" content="{% block og_description %}SpawnRadar surfaces the right YouTubers, streamers, and communities for your game, then helps you reach out with scored drafts.{% endblock %}" />
<meta property="og:type" content="{% block og_type %}website{% endblock %}" />
<meta property="og:url" content="{{ request.url }}" />
<meta property="og:image" content="{% block og_image %}https://spawnradar.app/static/og-default.png{% endblock %}" />

<!-- Twitter card -->
<meta name="twitter:card" content="summary_large_image" />
<meta name="twitter:title" content="{% block twitter_title %}SpawnRadar — Find Creators For Your Indie Game{% endblock %}" />
<meta name="twitter:description" content="{% block twitter_description %}Scored creator discovery and outreach drafts for indie game developers.{% endblock %}" />
```

### Per-page targets

| Page | Title | Description |
|---|---|---|
| `/` | SpawnRadar — Find the Right Creators for Your Indie Game | Surface YouTubers, streamers, and communities that match your game's genre and audience. Scored outreach queue included. |
| `/pricing` | Pricing — SpawnRadar | Free plan available. Upgrade to automate discovery for multiple games. |
| `/blog` | Blog — SpawnRadar | Guides on creator outreach and game marketing for indie developers. |
| `/blog/[slug]` | [Post title] — SpawnRadar | [Post excerpt] |
| `/auth/register` | Start Free — SpawnRadar | Create a free SpawnRadar account and run your first creator discovery in minutes. |

### OG image

Create a single 1200×630px image (`/static/og-default.png`) for link previews. Dark background, SpawnRadar logo, one-line value prop. This shows up in Discord, Slack, Twitter, LinkedIn whenever someone pastes a link.

---

## 2. Sitemap and Robots (fix this weekend)

### `sitemap.xml`

Add a `/sitemap.xml` route that returns a dynamic sitemap. At minimum include:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://spawnradar.app/</loc><changefreq>weekly</changefreq><priority>1.0</priority></url>
  <url><loc>https://spawnradar.app/pricing</loc><changefreq>monthly</changefreq><priority>0.8</priority></url>
  <url><loc>https://spawnradar.app/blog</loc><changefreq>weekly</changefreq><priority>0.9</priority></url>
  <!-- one entry per blog post -->
</urlset>
```

### `robots.txt`

Add a `/robots.txt` route:

```
User-agent: *
Allow: /
Disallow: /admin
Disallow: /games
Disallow: /auth

Sitemap: https://spawnradar.app/sitemap.xml
```

Both of these are simple FastAPI routes returning `PlainTextResponse`.

---

## 3. Canonical URLs

Add `<link rel="canonical" href="{{ request.url }}" />` to `base.html`. This prevents duplicate content penalties if the same page is reachable at multiple URLs (http vs https, trailing slash, etc.).

---

## 4. Page Speed

Run [PageSpeed Insights](https://pagespeed.web.dev/) on the homepage before launch. Common quick wins:

- **Font loading**: The Google Fonts link in `base.html` uses `preconnect` (already there). Add `font-display: swap` if it isn't already in the CSS to prevent FOIT.
- **No render-blocking JS**: Currently no JS dependencies, which is ideal.
- **Image formats**: Any images in static should be WebP where possible.
- **CSS size**: The current single `style.css` is fine at this scale. Consider adding `<link rel="preload" as="style">` if it grows large.

---

## 5. Keyword Strategy

### Primary keywords to target

These have meaningful search volume from indie developers:

| Keyword | Intent | Where to target |
|---|---|---|
| indie game creator outreach | Informational | Blog post 1 |
| how to contact youtubers about your game | Informational | Blog post 1 |
| game developer outreach email template | Informational | Blog post 2 |
| how to get streamers to play your indie game | Informational | Blog post 2 |
| indie game marketing tool | Commercial | Homepage, pricing |
| find gaming youtubers for indie game | Commercial | Homepage |
| game press kit | Informational | Future blog post |

### Secondary cluster

These are lower volume but very high intent (people actively looking for a solution):

- "how to find gaming youtubers to promote my game"
- "indie game influencer outreach tool"
- "youtube gaming channel discovery tool"
- "gaming creator outreach software"

### Content to write next

Based on search volume and product fit:

1. **"How to Build a Game Press Kit That Creators Actually Use"** — targets a high-volume keyword, directly relevant to the outreach workflow, natural CTA to SpawnRadar
2. **"The Best Subreddits to Share Your Indie Game"** — very high intent, easy to rank for, sets up Reddit as a source SpawnRadar covers
3. **"How to Find Gaming YouTubers for Your Indie Game (Without an Agency)"** — commercial intent, directly competitive with paid PR tools
4. **"What Makes a Good Game Trailer for Creator Coverage"** — upstream of the outreach workflow, positions SpawnRadar as the authoritative source on the full process

---

## 6. Structured Data

Add JSON-LD to blog posts for Google to show rich results (date, author, breadcrumbs).

Add to `blog_post.html`:

```html
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "BlogPosting",
  "headline": "{{ post.title }}",
  "description": "{{ post.excerpt }}",
  "datePublished": "{{ post.date }}",
  "author": {
    "@type": "Organization",
    "name": "SpawnRadar"
  },
  "publisher": {
    "@type": "Organization",
    "name": "SpawnRadar",
    "url": "https://spawnradar.app"
  }
}
</script>
```

---

## 7. Internal Linking

Every blog post already links to `/auth/register` at the bottom. Also add:

- Link from the homepage hero to `/blog` ("Read our outreach guides →")
- Link between blog posts where topics are adjacent (post 1 references templates → link to post 2)
- Link from the pricing page to the most relevant blog post

Internal links help Google understand site structure and distribute authority to important pages.

---

## 8. Domain and HTTPS

Before launch:
- Confirm the domain resolves correctly with and without `www`
- Confirm HTTPS is enforced (redirect HTTP → HTTPS)
- Confirm no mixed-content warnings in the browser console
- Set up Google Search Console on the domain and submit the sitemap

---

## 9. Analytics

Add before launch (pick one):

- **Plausible** (privacy-friendly, no cookie banner required, $9/mo) — recommended given the indie dev audience who tend to block Google Analytics
- **Fathom** (similar, $14/mo)
- **Google Analytics 4** (free, but requires cookie consent banner in EU)

Add the script tag to `base.html` once you have an account.

---

## 10. Launch Weekend Checklist

- [ ] Meta description on every public page
- [ ] OG image created and tested (paste URL into [Twitter Card Validator](https://cards-dev.twitter.com/validator) and Discord)
- [ ] `robots.txt` live
- [ ] `sitemap.xml` live and submitted to Google Search Console
- [ ] Canonical tag in `base.html`
- [ ] HTTPS enforced
- [ ] Analytics script installed
- [ ] PageSpeed score above 90 on mobile
- [ ] Blog live at `/blog` with at least 2 posts
- [ ] Navbar has Blog link (done)
- [ ] All blog posts have a CTA to sign up
- [ ] `/auth/register` page title and description are set correctly

---

## After Launch

- Post both blog posts in relevant subreddits (r/gamedev, r/indiegaming, r/gamemarketing) — do not make it feel like an ad, just share the resource
- Share on Bluesky and Twitter with the #indiedev #gamedev tags
- Watch Google Search Console for first impressions (usually 2–4 weeks after launch)
- Write the next blog post within 2 weeks while the content rhythm is warm
