"""Business logic for creator-authored Bluesky drafts."""

from __future__ import annotations

from app.bluesky_posts.models import BlueskyPostDraft
from app.bluesky_posts.repository import BlueskyPostDraftRepository

BLUESKY_MAX_CHARS = 300
BLUESKY_DEFAULT_HASHTAGS = ("#gamedev", "#indiegame", "indiedev")
_ALLOWED_IMAGE_MEDIA_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
}
_MAX_IMAGE_BYTES = 4 * 1024 * 1024


def _normalize_handle(handle: str | None) -> str | None:
    if handle is None:
        return None
    normalized = handle.strip()
    if not normalized:
        return None
    if not normalized.startswith("@"):
        normalized = "@" + normalized
    return normalized


def build_bluesky_draft_body(
    *,
    game_name: str,
    post_summary: str,
    creator_handle: str | None,
) -> str:
    """Build the draft body within Bluesky's 300-char limit."""
    header = f"New on SpawnRadar: {game_name}"
    trailer_parts = [
        _normalize_handle(creator_handle),
        *BLUESKY_DEFAULT_HASHTAGS,
    ]
    trailer = " ".join(part for part in trailer_parts if part)
    max_summary_length = BLUESKY_MAX_CHARS - len(header) - len(trailer) - 4
    if max_summary_length < 1:
        raise ValueError(
            "Game title is too long to fit a Bluesky draft with tags."
        )

    normalized_summary = post_summary.strip()
    if not normalized_summary:
        raise ValueError(
            "Bluesky post summary is required when post consent is enabled."
        )
    if len(normalized_summary) > max_summary_length:
        raise ValueError(
            f"Bluesky post summary must be {max_summary_length} characters or fewer for this game title."
        )
    return f"{header}\n\n{normalized_summary}\n\n{trailer}"


class BlueskyDraftService:
    """Create and review creator-authored Bluesky drafts."""

    def __init__(self, repo: BlueskyPostDraftRepository) -> None:
        self._repo = repo

    def create_game_draft(
        self,
        *,
        customer_game_id: str,
        source_game_slug: str,
        workspace_id: str,
        game_name: str,
        default_summary: str | None,
        creator_summary: str | None,
        creator_handle: str | None,
        image_filename: str | None = None,
        image_media_type: str | None = None,
        image_bytes: bytes | None = None,
    ) -> BlueskyPostDraft:
        """Create the single allowed queue entry for one game-owned draft."""
        if self._repo.get_by_game_id(customer_game_id) is not None:
            raise ValueError(
                "A Bluesky draft has already been created for this game."
            )
        if self._repo.get_by_game_slug(source_game_slug) is not None:
            raise ValueError(
                "A Bluesky draft has already been created for this game slug."
            )

        if image_bytes is not None:
            self._validate_image(
                image_filename=image_filename,
                image_media_type=image_media_type,
                image_bytes=image_bytes,
            )

        summary_text = (creator_summary or default_summary or "").strip()
        body = build_bluesky_draft_body(
            game_name=game_name,
            post_summary=summary_text,
            creator_handle=creator_handle,
        )

        return self._repo.create_for_game(
            customer_game_id=customer_game_id,
            source_game_slug=source_game_slug,
            workspace_id=workspace_id,
            creator_summary=summary_text,
            body=body,
            hashtags=list(BLUESKY_DEFAULT_HASHTAGS),
            creator_handle=_normalize_handle(creator_handle),
            image_filename=image_filename if image_bytes is not None else None,
            image_media_type=image_media_type
            if image_bytes is not None
            else None,
            image_bytes=image_bytes if image_bytes is not None else None,
            image_alt_text=game_name,
        )

    def review_draft(
        self,
        draft_id: str,
        *,
        body: str,
        status: str,
    ) -> BlueskyPostDraft:
        """Apply an admin review decision to a draft."""
        normalized_body = body.strip()
        if not normalized_body:
            raise ValueError("Bluesky draft body cannot be empty.")
        if len(normalized_body) > BLUESKY_MAX_CHARS:
            raise ValueError(
                "Bluesky draft body must be 300 characters or fewer."
            )
        return self._repo.update_body_and_status(
            draft_id,
            body=normalized_body,
            status=status,
        )

    def _validate_image(
        self,
        *,
        image_filename: str | None,
        image_media_type: str | None,
        image_bytes: bytes,
    ) -> None:
        if not image_filename:
            raise ValueError("Uploaded Bluesky image must include a filename.")
        if image_media_type not in _ALLOWED_IMAGE_MEDIA_TYPES:
            raise ValueError(
                "Bluesky image must be a PNG, JPEG, or WebP file."
            )
        if len(image_bytes) > _MAX_IMAGE_BYTES:
            raise ValueError("Bluesky image must be 4 MB or smaller.")
