"""Tests for the standalone game-import subsystem."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import TypedDict

import httpx
import pytest

from app.game_import.registry import build_registered_adapters, match_adapter
from app.game_import.service import GameImportService, load_builtin_adapters
from app.game_import.steam import SteamStoreAdapter
from app.game_import.steam_tag_mapping import map_steam_tags_to_setup_fields


class SteamImportCase(TypedDict):
    url: str
    app_id: str
    name: str
    short_description: str
    detailed_description: str
    platforms: dict[str, bool]
    genres: list[str]
    categories: list[str]
    store_tags: list[str]


STEAM_IMPORT_CASES: tuple[SteamImportCase, ...] = (
    {
        "url": "https://store.steampowered.com/app/4309620/Strife_of_Stars/",
        "app_id": "4309620",
        "name": "Strife of Stars",
        "short_description": (
            "A tactical sci-fi roguelike deckbuilder about climbing a deadly tower."
        ),
        "detailed_description": (
            "<p>Build your squad, tune your deck and fight upward through a"
            " shifting space-fantasy tower.</p>"
        ),
        "platforms": {"windows": True, "mac": False, "linux": False},
        "genres": ["Indie", "Strategy"],
        "categories": ["Single-player"],
        "store_tags": ["Deckbuilding", "Roguelike", "Sci-fi"],
    },
    {
        "url": "https://store.steampowered.com/app/2195140/Volgarr_the_Viking_II/",
        "app_id": "2195140",
        "name": "Volgarr the Viking II",
        "short_description": (
            "A brutal action platformer built for players who want exacting combat."
        ),
        "detailed_description": (
            "<p>Leap, slash and survive a merciless retro-inspired challenge.</p>"
        ),
        "platforms": {"windows": True, "mac": False, "linux": False},
        "genres": ["Action", "Indie"],
        "categories": ["Single-player"],
        "store_tags": ["Action", "Platformer", "Difficult"],
    },
    {
        "url": "https://store.steampowered.com/app/2868840/Slay_the_Spire_2/",
        "app_id": "2868840",
        "name": "Slay the Spire 2",
        "short_description": (
            "The next deckbuilding roguelike climb for players who love synergy and risk."
        ),
        "detailed_description": (
            "<p>Climb the Spire again with new cards, new relics and deadlier routes.</p>"
        ),
        "platforms": {"windows": True, "mac": True, "linux": False},
        "genres": ["Strategy", "Indie"],
        "categories": ["Single-player"],
        "store_tags": ["Deckbuilding", "Roguelite", "Turn-Based Strategy"],
    },
)


def _steam_appdetails_payload(case: SteamImportCase) -> dict[str, object]:
    app_id = case["app_id"]
    genres = [
        {"id": str(index), "description": genre}
        for index, genre in enumerate(case["genres"], start=1)
    ]
    categories = [
        {"id": str(index), "description": category}
        for index, category in enumerate(case["categories"], start=100)
    ]
    return {
        app_id: {
            "success": True,
            "data": {
                "name": case["name"],
                "short_description": case["short_description"],
                "detailed_description": case["detailed_description"],
                "website": f"https://example.com/{app_id}",
                "header_image": f"https://cdn.example.com/{app_id}.jpg",
                "platforms": case["platforms"],
                "genres": genres,
                "categories": categories,
                "supported_languages": "English, German, Japanese",
                "release_date": {"date": "1 Jan, 2026"},
            },
        }
    }


def _steam_store_html(tags: Iterable[str]) -> str:
    tag_links = "\n".join(f'<a class="app_tag">{tag}</a>' for tag in tags)
    return f"<html><body>{tag_links}</body></html>"


def _expected_raw_tags(case: SteamImportCase) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for tag in case["store_tags"] + case["genres"] + case["categories"]:
        key = tag.casefold()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(tag)
    return ordered


def test_registry_matches_steam_url() -> None:
    load_builtin_adapters()
    adapters = build_registered_adapters()

    adapter = match_adapter(
        "https://store.steampowered.com/app/12345/example-game/",
        adapters,
    )

    assert adapter is not None
    assert adapter.source_kind == "steam"


@pytest.mark.parametrize("case", STEAM_IMPORT_CASES)
def test_registry_matches_real_steam_urls(case: SteamImportCase) -> None:
    load_builtin_adapters()
    adapters = build_registered_adapters()

    adapter = match_adapter(str(case["url"]), adapters)

    assert adapter is not None
    assert adapter.source_kind == "steam"


def test_import_service_rejects_unknown_urls() -> None:
    service = GameImportService()

    async def run() -> None:
        try:
            await service.import_url("https://example.com/not-supported")
        except ValueError as exc:
            assert "No game import adapter supports URL" in str(exc)
            return
        raise AssertionError("Expected ValueError for unsupported URL")

    asyncio.run(run())


def test_steam_adapter_builds_reviewable_draft() -> None:
    async def run() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/appdetails":
                return httpx.Response(
                    200,
                    request=request,
                    json={
                        "570000": {
                            "success": True,
                            "data": {
                                "name": "Card Quest",
                                "short_description": "A tactical deckbuilder for players who like hard decisions.",
                                "detailed_description": (
                                    "<p>Build a deck, survive grim encounters, "
                                    "and make difficult tactical choices.</p>"
                                ),
                                "website": "https://cardquest.example.com",
                                "header_image": "https://cdn.example.com/cardquest.jpg",
                                "platforms": {
                                    "windows": True,
                                    "mac": False,
                                    "linux": True,
                                },
                                "genres": [
                                    {"id": "23", "description": "Indie"},
                                    {"id": "2", "description": "Strategy"},
                                ],
                                "categories": [
                                    {"id": "2", "description": "Single-player"}
                                ],
                                "supported_languages": "English, German, Japanese",
                                "release_date": {"date": "1 Jan, 2026"},
                            },
                        }
                    },
                )
            return httpx.Response(
                200,
                request=request,
                text="""
                <html>
                  <body>
                    <a class="app_tag">Deckbuilding</a>
                    <a class="app_tag">Roguelite</a>
                    <a class="app_tag">Strategy</a>
                  </body>
                </html>
                """,
            )

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport, base_url="https://store.steampowered.com"
        ) as client:
            adapter = SteamStoreAdapter()
            preview = await adapter.fetch(
                "https://store.steampowered.com/app/570000/card-quest/",
                client=client,
            )

        assert preview.source.source_kind == "steam"
        assert preview.source.source_id == "570000"
        assert preview.source.name == "Card Quest"
        assert preview.source.platform_labels == ["Windows", "Linux"]
        assert preview.source.api_genre_labels == ["Indie", "Strategy"]
        assert preview.source.api_category_labels == ["Single-player"]
        assert preview.source.raw_tags == [
            "Deckbuilding",
            "Roguelite",
            "Strategy",
            "Indie",
            "Single-player",
        ]
        assert preview.draft.name == "Card Quest"
        assert preview.draft.summary.startswith("A tactical deckbuilder")
        assert "Build a deck" in preview.draft.description
        assert preview.draft.igdb_genre_ids == [32, 15]
        assert preview.draft.igdb_game_mode_ids == [1]
        assert preview.draft.igdb_keyword_ids == ["deckbuilder", "roguelite"]
        assert preview.draft.tag_candidates[:2] == [
            "Deckbuilding",
            "Roguelite",
        ]
        assert preview.draft.website_url == "https://cardquest.example.com"
        assert preview.draft.notes == [
            "Imported draft applied. Review and edit before saving."
        ]

    asyncio.run(run())


def test_map_steam_tags_prefills_broad_stable_matches() -> None:
    mapped = map_steam_tags_to_setup_fields(
        api_genre_labels=["Strategy", "Indie"],
        api_category_labels=["Single-player"],
        raw_tags=[
            "Card Game",
            "Roguelike",
            "Deckbuilding",
            "Casual",
            "Arcade",
            "Turn-Based Strategy",
            "Roguelite",
        ],
        text_blobs=[],
    )

    assert mapped.igdb_genre_ids == [15, 32, 35, 16]
    assert mapped.igdb_theme_ids == []
    assert mapped.igdb_game_mode_ids == [1]
    assert mapped.igdb_keyword_ids == [
        "roguelike",
        "deckbuilder",
        "casual",
        "roguelite",
    ]


def test_map_steam_tags_normalizes_spacing_and_hyphen_variants() -> None:
    mapped = map_steam_tags_to_setup_fields(
        api_genre_labels=[],
        api_category_labels=[],
        raw_tags=[
            "rogue like deck builder",
            "rogue-like deckbuilder",
        ],
        text_blobs=[],
    )

    assert mapped.igdb_keyword_ids == ["roguelike", "deckbuilder"]


def test_map_steam_tags_balatro_style_tags_include_keywords_not_arcade() -> (
    None
):
    mapped = map_steam_tags_to_setup_fields(
        api_genre_labels=["Strategy", "Indie"],
        api_category_labels=["Single-player"],
        raw_tags=[
            "Card Game",
            "Roguelike Deckbuilder",
            "Deckbuilding",
            "Roguelite",
            "Arcade",
        ],
        text_blobs=[],
    )

    assert 33 not in mapped.igdb_genre_ids
    assert 35 in mapped.igdb_genre_ids
    assert mapped.igdb_keyword_ids == ["roguelike", "deckbuilder", "roguelite"]


def test_map_steam_tags_skips_description_text_keyword_fallback_after_one_mention() -> (
    None
):
    mapped = map_steam_tags_to_setup_fields(
        api_genre_labels=["Strategy", "Indie"],
        api_category_labels=["Single-player"],
        raw_tags=["Card Game"],
        text_blobs=[
            "The poker roguelike. Balatro is a hypnotically satisfying deckbuilder."
        ],
    )

    assert mapped.igdb_genre_ids == [15, 32, 35]
    assert mapped.igdb_keyword_ids == []


def test_map_steam_tags_uses_description_text_after_two_mentions() -> None:
    mapped = map_steam_tags_to_setup_fields(
        api_genre_labels=["Strategy", "Indie"],
        api_category_labels=["Single-player"],
        raw_tags=["Card Game"],
        text_blobs=[
            "The poker roguelike. Balatro is a hypnotically satisfying deckbuilder.",
            "This deckbuilder roguelike rewards careful planning.",
        ],
    )

    assert mapped.igdb_genre_ids == [15, 32, 35]
    assert set(mapped.igdb_keyword_ids) == {"roguelike", "deckbuilder"}


@pytest.mark.parametrize("case", STEAM_IMPORT_CASES)
def test_steam_adapter_imports_known_store_urls(case: SteamImportCase) -> None:
    async def run() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/appdetails":
                return httpx.Response(
                    200,
                    request=request,
                    json=_steam_appdetails_payload(case),
                )
            return httpx.Response(
                200,
                request=request,
                text=_steam_store_html(case["store_tags"]),
            )

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport, base_url="https://store.steampowered.com"
        ) as client:
            preview = await SteamStoreAdapter().fetch(
                case["url"], client=client
            )

        app_id = case["app_id"]
        canonical_url = f"https://store.steampowered.com/app/{app_id}/"
        expected_name = case["name"]

        assert preview.source.source_kind == "steam"
        assert preview.source.source_id == app_id
        assert preview.source.source_url == canonical_url
        assert preview.source.name == expected_name
        assert preview.source.short_description == case["short_description"]
        assert preview.source.raw_tags == _expected_raw_tags(case)
        assert preview.draft.name == expected_name
        assert preview.draft.summary.startswith(case["short_description"][:20])
        assert preview.draft.description == (
            case["detailed_description"].replace("<p>", "").replace("</p>", "")
        )
        assert preview.draft.tag_candidates == preview.source.raw_tags
        assert preview.draft.website_url == f"https://example.com/{app_id}"

    asyncio.run(run())
