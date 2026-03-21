"""Sitemap and robots.txt routes."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

from app.routes.blog import _POSTS

router = APIRouter()

_ROBOTS = """\
User-agent: *
Allow: /
Disallow: /admin
Disallow: /games
Disallow: /auth

Sitemap: https://spawnradar.com/sitemap.xml
"""


@router.get("/robots.txt", response_class=PlainTextResponse)
async def robots_txt() -> str:
    return _ROBOTS


@router.get("/sitemap.xml", response_class=PlainTextResponse)
async def sitemap_xml(request: Request) -> PlainTextResponse:
    base = "https://spawnradar.com"

    static_urls = [
        f'<url><loc>{base}/</loc><changefreq>weekly</changefreq><priority>1.0</priority></url>',
        f'<url><loc>{base}/pricing</loc><changefreq>monthly</changefreq><priority>0.8</priority></url>',
        f'<url><loc>{base}/blog</loc><changefreq>weekly</changefreq><priority>0.9</priority></url>',
        f'<url><loc>{base}/creators</loc><changefreq>monthly</changefreq><priority>0.8</priority></url>',
        f'<url><loc>{base}/terms</loc><changefreq>yearly</changefreq><priority>0.4</priority></url>',
        f'<url><loc>{base}/privacy</loc><changefreq>yearly</changefreq><priority>0.4</priority></url>',
        f'<url><loc>{base}/refunds</loc><changefreq>yearly</changefreq><priority>0.4</priority></url>',
    ]

    post_urls = [
        f'<url><loc>{base}/blog/{post["slug"]}</loc>'
        f'<lastmod>{post["date"]}</lastmod>'
        f'<changefreq>monthly</changefreq>'
        f'<priority>0.7</priority></url>'
        for post in _POSTS
    ]

    body = "\n  ".join(static_urls + post_urls)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"  {body}\n"
        "</urlset>"
    )
    return PlainTextResponse(xml, media_type="application/xml")
