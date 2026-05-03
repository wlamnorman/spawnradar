"""Sitemap and robots.txt routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, PlainTextResponse, Response

from app.routes.blog import POSTS

router = APIRouter()

_ROBOTS_PATH = (
    Path(__file__).parent.parent / "frontend" / "static" / "robots.txt"
)


def _build_sitemap_xml() -> str:
    """Return the sitemap XML body shared by GET and HEAD handlers."""
    base = "https://spawnradar.com"

    static_urls = [
        f"<url><loc>{base}/</loc><changefreq>weekly</changefreq><priority>1.0</priority></url>",
        f"<url><loc>{base}/how-it-works</loc><changefreq>monthly</changefreq><priority>0.9</priority></url>",
        f"<url><loc>{base}/pricing</loc><changefreq>monthly</changefreq><priority>0.8</priority></url>",
        f"<url><loc>{base}/blog</loc><changefreq>weekly</changefreq><priority>0.9</priority></url>",
        f"<url><loc>{base}/terms</loc><changefreq>yearly</changefreq><priority>0.4</priority></url>",
        f"<url><loc>{base}/privacy</loc><changefreq>yearly</changefreq><priority>0.4</priority></url>",
        f"<url><loc>{base}/refunds</loc><changefreq>yearly</changefreq><priority>0.4</priority></url>",
    ]

    post_urls = [
        f"<url><loc>{base}/blog/{post['slug']}</loc>"
        f"<lastmod>{post['date']}</lastmod>"
        f"<changefreq>monthly</changefreq>"
        f"<priority>0.7</priority></url>"
        for post in POSTS
    ]

    body = "\n  ".join(static_urls + post_urls)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"  {body}\n"
        "</urlset>"
    )


@router.get("/robots.txt")
async def robots_txt() -> FileResponse:
    return FileResponse(_ROBOTS_PATH, media_type="text/plain")


@router.head("/robots.txt")
async def robots_txt_head() -> Response:
    """Allow crawler HEAD probes for robots.txt."""
    return Response(status_code=200, media_type="text/plain")


@router.get("/sitemap.xml", response_class=PlainTextResponse)
async def sitemap_xml() -> PlainTextResponse:
    return PlainTextResponse(
        _build_sitemap_xml(), media_type="application/xml"
    )


@router.head("/sitemap.xml")
async def sitemap_xml_head() -> PlainTextResponse:
    """Allow crawler HEAD probes for the sitemap."""
    return PlainTextResponse(
        _build_sitemap_xml(), media_type="application/xml"
    )
