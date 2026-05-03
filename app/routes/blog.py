"""Blog routes — posts are loaded from app/content/blog/*.md at startup."""

from __future__ import annotations

import math
from pathlib import Path

import frontmatter
import markdown as md
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from app.ownership.dependencies import get_ownership_context
from app.ownership.service import OwnershipContext

router = APIRouter()

_BLOG_DIR = Path(__file__).parent.parent / "content" / "blog"

_MD = md.Markdown(extensions=["tables", "fenced_code"])


def _load_posts() -> list[dict]:
    posts = []
    for path in sorted(_BLOG_DIR.glob("*.md")):
        post = frontmatter.load(str(path))
        _MD.reset()
        body_html = _MD.convert(post.content)
        word_count = len(post.content.split())
        read_time = f"{max(1, math.ceil(word_count / 200))} min read"
        excerpt = str(post["excerpt"]).strip()
        posts.append(
            {
                "slug": path.stem,
                "title": post["title"],
                "date": post["date"],
                "read_time": post.get("read_time", read_time),
                "excerpt": excerpt,
                "body_html": body_html,
            }
        )
    # Sort newest-first by date string (ISO format sorts correctly)
    posts.sort(key=lambda p: p["date"], reverse=True)
    return posts


POSTS = _load_posts()
POST_BY_SLUG = {p["slug"]: p for p in POSTS}


@router.get("/blog")
async def blog_index(
    request: Request,
    ownership: OwnershipContext = Depends(get_ownership_context),
):
    return request.app.state.templates.TemplateResponse(
        request,
        "marketing/blog.html",
        {"user": ownership.actor, "posts": POSTS},
    )


@router.head("/blog")
async def blog_index_head() -> Response:
    """Allow crawler HEAD probes for the blog index."""
    return Response(status_code=200)


@router.get("/blog/{slug}")
async def blog_post(
    slug: str,
    request: Request,
    ownership: OwnershipContext = Depends(get_ownership_context),
):
    post = POST_BY_SLUG.get(slug)
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")
    return request.app.state.templates.TemplateResponse(
        request,
        "marketing/blog_post.html",
        {"user": ownership.actor, "post": post},
    )


@router.head("/blog/{slug}")
async def blog_post_head(slug: str) -> Response:
    """Allow crawler HEAD probes for public blog posts."""
    if slug not in POST_BY_SLUG:
        raise HTTPException(status_code=404, detail="Post not found")
    return Response(status_code=200)
