"""Steam adapter for the standalone game-import subsystem.

This adapter uses deterministic Steam endpoints only. It fetches Steam app
details JSON and the public store page HTML, extracts fields that are useful
for setup prefill and returns both raw source data and a normalized draft.

No LLM is used here. Summary generation is a lightweight deterministic fallback
based on Steam's own short description and body text.
"""

from __future__ import annotations

import html
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from selectolax.parser import HTMLParser

from app.game_import.models import (
    ImportedGameDraft,
    ImportedGamePreview,
    ImportedGameSourceData,
)
from app.game_import.registry import register_adapter
from app.game_import.steam_tag_mapping import map_steam_tags_to_setup_fields
from app.games.constants import MAX_SUMMARY_LENGTH
from app.steam_parsing import (
    dedupe_preserve_order,
    extract_store_tags,
    platform_labels,
    steam_api_descriptions,
)

_STEAM_APP_URL_RE = re.compile(
    r"^https?://store\.steampowered\.com/app/(?P<app_id>\d+)(?:/[^/?#]*)?",
    re.IGNORECASE,
)


def _clean_text(value: str | None) -> str:
    if not value:
        return ""
    parser = HTMLParser(html.unescape(value))
    text = parser.text(separator=" ", strip=True)
    return " ".join(text.split())


def _truncate_sentence(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    sentence_end = value.rfind(".", 0, limit)
    if sentence_end >= max(40, int(limit * 0.4)):
        return value[: sentence_end + 1].strip()
    return value[: limit - 1].rstrip() + "…"


def _extract_app_id(url: str) -> str | None:
    match = _STEAM_APP_URL_RE.match(url.strip())
    if match is None:
        return None
    return match.group("app_id")


def _steam_api_tags(data: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for key in ("genres", "categories"):
        result.extend(steam_api_descriptions(data, key))
    return dedupe_preserve_order(result)


def _supported_languages(data: dict[str, Any]) -> list[str]:
    text = _clean_text(str(data.get("supported_languages") or ""))
    if not text:
        return []
    parts = re.split(r",|/|;", text)
    languages = [part.strip() for part in parts if part.strip()]
    return dedupe_preserve_order(languages)


def _build_summary(
    name: str, short_description: str, full_description: str
) -> str:
    if short_description:
        return _truncate_sentence(short_description, MAX_SUMMARY_LENGTH)
    if full_description:
        return _truncate_sentence(full_description, MAX_SUMMARY_LENGTH)
    return _truncate_sentence(f"{name} on Steam.", MAX_SUMMARY_LENGTH)


def _build_description(short_description: str, full_description: str) -> str:
    if full_description:
        return full_description
    if short_description:
        return short_description
    return ""


@asynccontextmanager
async def _maybe_owned_client(
    client: httpx.AsyncClient | None,
) -> AsyncIterator[httpx.AsyncClient]:
    if client is not None:
        yield client
        return
    async with httpx.AsyncClient(
        timeout=20, follow_redirects=True
    ) as owned_client:
        yield owned_client


@register_adapter
class SteamStoreAdapter:
    """Imports Steam app pages into raw source data plus a normalized draft."""

    source_kind = "steam"

    def matches_url(self, url: str) -> bool:
        return _extract_app_id(url) is not None

    async def fetch(
        self, url: str, client: httpx.AsyncClient | None = None
    ) -> ImportedGamePreview:
        app_id = _extract_app_id(url)
        if app_id is None:
            raise ValueError(f"Unsupported Steam URL: {url}")

        canonical_url = f"https://store.steampowered.com/app/{app_id}/"
        async with _maybe_owned_client(client) as http_client:
            api_payload = await self._fetch_app_details(http_client, app_id)
            store_html = await self._fetch_store_page(
                http_client, canonical_url
            )

        source = self._build_source_data(
            source_url=canonical_url,
            source_id=app_id,
            api_payload=api_payload,
            store_html=store_html,
        )
        draft = self._build_draft(source)
        return ImportedGamePreview(source=source, draft=draft)

    async def _fetch_app_details(
        self, client: httpx.AsyncClient, app_id: str
    ) -> dict[str, Any]:
        response = await client.get(
            "https://store.steampowered.com/api/appdetails",
            params={"appids": app_id, "l": "english"},
        )
        response.raise_for_status()
        payload = response.json()
        app_container = payload.get(app_id)
        if not isinstance(app_container, dict) or not bool(
            app_container.get("success")
        ):
            raise ValueError(
                f"Steam appdetails lookup failed for app_id={app_id}"
            )
        data = app_container.get("data")
        if not isinstance(data, dict):
            raise ValueError(
                f"Steam appdetails returned invalid data for app_id={app_id}"
            )
        return data

    async def _fetch_store_page(
        self, client: httpx.AsyncClient, url: str
    ) -> str:
        response = await client.get(url)
        response.raise_for_status()
        return response.text

    def _build_source_data(
        self,
        *,
        source_url: str,
        source_id: str,
        api_payload: dict[str, Any],
        store_html: str,
    ) -> ImportedGameSourceData:
        name = str(api_payload.get("name") or "").strip() or None
        short_description = _clean_text(
            str(api_payload.get("short_description") or "")
        )
        full_description = _clean_text(
            str(
                api_payload.get("detailed_description")
                or api_payload.get("about_the_game")
                or ""
            )
        )
        platform_labels_value = platform_labels(api_payload)
        api_genre_labels = steam_api_descriptions(api_payload, "genres")
        api_category_labels = steam_api_descriptions(api_payload, "categories")
        raw_tags = dedupe_preserve_order(
            extract_store_tags(store_html) + _steam_api_tags(api_payload)
        )
        supported_languages = _supported_languages(api_payload)
        release_date_payload = api_payload.get("release_date")
        release_date = None
        if isinstance(release_date_payload, dict):
            release_date = (
                str(release_date_payload.get("date") or "").strip() or None
            )

        return ImportedGameSourceData(
            source_kind=self.source_kind,
            source_url=source_url,
            source_id=source_id,
            name=name,
            short_description=short_description or None,
            full_description=full_description or None,
            platform_labels=platform_labels_value,
            api_genre_labels=api_genre_labels,
            api_category_labels=api_category_labels,
            raw_tags=raw_tags,
            website_url=str(api_payload.get("website") or "").strip() or None,
            image_url=str(api_payload.get("header_image") or "").strip()
            or None,
            release_date=release_date,
            supported_languages=supported_languages,
            raw_payload=api_payload,
        )

    def _build_draft(
        self, source: ImportedGameSourceData
    ) -> ImportedGameDraft:
        name = source.name or "Imported Steam game"
        short_description = source.short_description or ""
        full_description = source.full_description or ""
        description = _build_description(short_description, full_description)
        summary = _build_summary(name, short_description, full_description)
        mapped_tags = map_steam_tags_to_setup_fields(
            api_genre_labels=source.api_genre_labels,
            api_category_labels=source.api_category_labels,
            raw_tags=source.raw_tags,
            text_blobs=[short_description, full_description],
        )
        notes = ["Imported draft applied. Review and edit before saving."]
        return ImportedGameDraft(
            source_kind=source.source_kind,
            source_url=source.source_url,
            source_id=source.source_id,
            name=name,
            summary=summary,
            description=description,
            platform_labels=source.platform_labels,
            igdb_genre_ids=mapped_tags.igdb_genre_ids,
            igdb_theme_ids=mapped_tags.igdb_theme_ids,
            igdb_game_mode_ids=mapped_tags.igdb_game_mode_ids,
            igdb_keyword_ids=mapped_tags.igdb_keyword_ids,
            tag_candidates=source.raw_tags,
            website_url=source.website_url,
            image_url=source.image_url,
            notes=notes,
        )
