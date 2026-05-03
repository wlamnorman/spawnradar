"""Steam store fetch helpers for cached-game enrichment.

This intentionally uses Steam's own public store surfaces:

- search suggestions for app candidate discovery
- appdetails JSON for structured metadata
- public store HTML for community/store tags

It does not depend on SteamDB app-page scraping, which is currently bot
protected.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from selectolax.parser import HTMLParser

from app.steam_enrichment.models import SteamSearchCandidate, SteamStoreGame
from app.steam_parsing import (
    dedupe_preserve_order,
    extract_store_tags,
    html_to_text,
    platform_labels,
    steam_api_descriptions,
)

_BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

_BASE_COOKIES = {
    # Request the normal app page instead of the age-gated variant when Steam
    # allows it. Without these, some mature games only expose a truncated HTML
    # view with missing or heavily reduced tags.
    "birthtime": "315532801",  # 1980-01-01 UTC
    "lastagecheckage": "1-January-1980",
    "wants_mature_content": "1",
}


def _developers(data: dict[str, Any]) -> list[str]:
    values = data.get("developers")
    if not isinstance(values, list):
        return []
    return dedupe_preserve_order(
        [str(value).strip() for value in values if str(value).strip()]
    )


@asynccontextmanager
async def _maybe_owned_client(
    client: httpx.AsyncClient | None,
) -> AsyncIterator[httpx.AsyncClient]:
    if client is not None:
        yield client
        return
    async with httpx.AsyncClient(
        timeout=20,
        follow_redirects=True,
        headers=_BASE_HEADERS,
        cookies=_BASE_COOKIES,
    ) as owned_client:
        yield owned_client


class SteamStoreClient:
    """Small client for Steam app search and metadata fetches."""

    async def search_candidates(
        self,
        name: str,
        *,
        limit: int = 8,
        client: httpx.AsyncClient | None = None,
    ) -> list[SteamSearchCandidate]:
        async with _maybe_owned_client(client) as http_client:
            response = await http_client.get(
                "https://store.steampowered.com/search/suggest",
                params={
                    "term": name,
                    "f": "games",
                    "cc": "US",
                    "l": "english",
                    "realm": "1",
                },
            )
            response.raise_for_status()
        parser = HTMLParser(response.text)
        candidates: list[SteamSearchCandidate] = []
        for node in parser.css("a.match")[:limit]:
            raw_app_id = node.attributes.get("data-ds-appid")
            name_node = node.css_first(".match_name")
            if not raw_app_id or name_node is None:
                continue
            try:
                app_id = int(raw_app_id)
            except ValueError:
                continue
            candidates.append(
                SteamSearchCandidate(
                    app_id=app_id,
                    name=name_node.text(strip=True),
                    store_url=f"https://store.steampowered.com/app/{app_id}/",
                )
            )
        return candidates

    async def fetch_store_game(
        self,
        app_id: int,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> SteamStoreGame:
        store_url = f"https://store.steampowered.com/app/{app_id}/"
        async with _maybe_owned_client(client) as http_client:
            details_response = await http_client.get(
                "https://store.steampowered.com/api/appdetails",
                params={"appids": str(app_id), "l": "english"},
            )
            details_response.raise_for_status()
            payload = details_response.json()
            app_container = payload.get(str(app_id))
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
            store_response = await http_client.get(store_url)
            store_response.raise_for_status()

        release_date_payload = data.get("release_date")
        release_date = None
        if isinstance(release_date_payload, dict):
            release_date = (
                str(release_date_payload.get("date") or "").strip() or None
            )
        return SteamStoreGame(
            app_id=app_id,
            name=str(data.get("name") or "").strip(),
            store_url=store_url,
            developers=tuple(_developers(data)),
            release_date=release_date,
            platform_labels=tuple(platform_labels(data)),
            short_description=html_to_text(data.get("short_description")),
            detailed_description=html_to_text(
                data.get("detailed_description") or data.get("about_the_game")
            ),
            raw_tags=tuple(extract_store_tags(store_response.text)),
            api_genre_labels=tuple(steam_api_descriptions(data, "genres")),
            api_category_labels=tuple(
                steam_api_descriptions(data, "categories")
            ),
        )
