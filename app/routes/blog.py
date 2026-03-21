"""Blog routes — posts are loaded from app/content/blog/*.md at startup."""
from __future__ import annotations

import math
from pathlib import Path

import frontmatter
import markdown as md
from fastapi import APIRouter, HTTPException, Request

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


_POSTS = _load_posts()
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
