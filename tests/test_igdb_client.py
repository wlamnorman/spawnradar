from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.igdb.client import IGDBClient
from app.igdb.taxonomy import IGDBGenre, IGDBTheme


@pytest.fixture
def client():
    return IGDBClient(client_id="test_id", client_secret="test_secret")


@pytest.mark.anyio
async def test_fetch_games_parses_response(client):
    mock_token = MagicMock()
    mock_token.json.return_value = {
        "access_token": "tok",
        "expires_in": 9999,
    }
    mock_token.raise_for_status = MagicMock()
    mock_games = MagicMock()
    mock_games.json.return_value = [
        {
            "id": 1994,
            "name": "Hades",
            "slug": "hades",
            "summary": "Roguelite",
            "genres": [
                {"id": 12, "name": "Role-playing (RPG)"},
                {"id": 32, "name": "Indie"},
            ],
            "themes": [
                {"id": 1, "name": "Action"},
                {"id": 17, "name": "Fantasy"},
            ],
            "first_release_date": 1600300800,
        }
    ]
    mock_games.raise_for_status = MagicMock()
    with patch("httpx.AsyncClient") as mock_cls:
        mock_http = AsyncMock()
        mock_cls.return_value.__aenter__.return_value = mock_http
        mock_http.post.side_effect = [mock_token, mock_games]
        games = await client.fetch_games(limit=500, offset=0)
    assert len(games) == 1
    g = games[0]
    assert g.igdb_id == 1994
    assert IGDBGenre.ROLE_PLAYING in g.genre_ids
    assert IGDBTheme.FANTASY in g.theme_ids


@pytest.mark.anyio
async def test_fetch_games_returns_empty_on_empty_response(client):
    mock_token = MagicMock()
    mock_token.json.return_value = {
        "access_token": "tok",
        "expires_in": 9999,
    }
    mock_token.raise_for_status = MagicMock()
    mock_games = MagicMock()
    mock_games.json.return_value = []
    mock_games.raise_for_status = MagicMock()
    with patch("httpx.AsyncClient") as mock_cls:
        mock_http = AsyncMock()
        mock_cls.return_value.__aenter__.return_value = mock_http
        mock_http.post.side_effect = [mock_token, mock_games]
        assert await client.fetch_games(limit=500, offset=0) == []


@pytest.mark.anyio
async def test_fetch_game_by_id_parses_response(client):
    mock_token = MagicMock()
    mock_token.json.return_value = {
        "access_token": "tok",
        "expires_in": 9999,
    }
    mock_token.raise_for_status = MagicMock()
    mock_game = MagicMock()
    mock_game.json.return_value = [
        {
            "id": 296831,
            "name": "Slay the Spire II",
            "slug": "slay-the-spire-ii",
            "summary": "Deckbuilder sequel",
            "genres": [{"id": 15, "name": "Strategy"}],
            "themes": [{"id": 1, "name": "Action"}],
            "first_release_date": 1760000000,
        }
    ]
    mock_game.raise_for_status = MagicMock()
    with patch("httpx.AsyncClient") as mock_cls:
        mock_http = AsyncMock()
        mock_cls.return_value.__aenter__.return_value = mock_http
        mock_http.post.side_effect = [mock_token, mock_game]
        game = await client.fetch_game_by_id(296831)

    assert game is not None
    assert game.igdb_id == 296831
    assert game.name == "Slay the Spire II"
    assert IGDBGenre.STRATEGY in game.genre_ids


@pytest.mark.anyio
async def test_fetch_games_by_tags_builds_membership_query(client):
    mock_token = MagicMock()
    mock_token.json.return_value = {
        "access_token": "tok",
        "expires_in": 9999,
    }
    mock_token.raise_for_status = MagicMock()
    mock_games = MagicMock()
    mock_games.json.return_value = [
        {
            "id": 119133,
            "name": "Elden Ring",
            "slug": "elden-ring",
            "summary": "Soulslike RPG",
            "genres": [{"id": 12, "name": "Role-playing (RPG)"}],
            "themes": [{"id": 1, "name": "Action"}],
            "first_release_date": 1645747200,
        }
    ]
    mock_games.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_cls:
        mock_http = AsyncMock()
        mock_cls.return_value.__aenter__.return_value = mock_http
        mock_http.post.side_effect = [mock_token, mock_games]

        games = await client.fetch_games_by_tags(
            genre_ids=(12,),
            theme_ids=(1,),
            limit=10,
            offset=20,
        )

    assert len(games) == 1
    assert games[0].igdb_id == 119133
    _, kwargs = mock_http.post.call_args_list[1]
    assert "where genres = 12 & themes = 1;" in kwargs["content"]
    assert "limit 10; offset 20;" in kwargs["content"]


@pytest.mark.anyio
async def test_fetch_games_by_name_builds_search_query(client):
    mock_token = MagicMock()
    mock_token.json.return_value = {"access_token": "tok", "expires_in": 9999}
    mock_token.raise_for_status = MagicMock()
    mock_games = MagicMock()
    mock_games.json.return_value = [
        {
            "id": 1994,
            "name": "Hades",
            "slug": "hades",
            "summary": "Roguelite",
            "genres": [{"id": 12, "name": "Role-playing (RPG)"}],
            "themes": [{"id": 1, "name": "Action"}],
            "first_release_date": 1600300800,
        }
    ]
    mock_games.raise_for_status = MagicMock()
    with patch("httpx.AsyncClient") as mock_cls:
        mock_http = AsyncMock()
        mock_cls.return_value.__aenter__.return_value = mock_http
        mock_http.post.side_effect = [mock_token, mock_games]
        games = await client.fetch_games_by_name("Hades", limit=3)
    assert len(games) == 1
    _, kwargs = mock_http.post.call_args_list[1]
    assert 'search "Hades"' in kwargs["content"]
    assert "keywords.id,keywords.name" in kwargs["content"]


@pytest.mark.anyio
async def test_fetch_games_by_keywords_builds_query(client):
    mock_token = MagicMock()
    mock_token.json.return_value = {"access_token": "tok", "expires_in": 9999}
    mock_token.raise_for_status = MagicMock()
    mock_games = MagicMock()
    mock_games.json.return_value = []
    mock_games.raise_for_status = MagicMock()
    with patch("httpx.AsyncClient") as mock_cls:
        mock_http = AsyncMock()
        mock_cls.return_value.__aenter__.return_value = mock_http
        mock_http.post.side_effect = [mock_token, mock_games]
        await client.fetch_games_by_keywords(
            [100, 200], genre_ids=[12], theme_ids=[1], limit=25
        )
    _, kwargs = mock_http.post.call_args_list[1]
    query = kwargs["content"]
    assert "keywords = (100,200)" in query
    assert "version_parent = null" in query
    assert "category = 0" not in query
    assert "sort total_rating_count desc" in query


@pytest.mark.anyio
async def test_fetch_games_by_keywords_drops_indie(client):
    mock_token = MagicMock()
    mock_token.json.return_value = {"access_token": "tok", "expires_in": 9999}
    mock_token.raise_for_status = MagicMock()
    mock_games = MagicMock()
    mock_games.json.return_value = []
    mock_games.raise_for_status = MagicMock()
    with patch("httpx.AsyncClient") as mock_cls:
        mock_http = AsyncMock()
        mock_cls.return_value.__aenter__.return_value = mock_http
        mock_http.post.side_effect = [mock_token, mock_games]
        await client.fetch_games_by_keywords(
            [100], genre_ids=[32, 15], limit=10
        )
    _, kwargs = mock_http.post.call_args_list[1]
    query = kwargs["content"]
    # Indie (32) should be dropped; only Strategy (15) remains
    assert "genres = (15)" in query
    assert "32" not in query


def test_keyword_names_parsed(client):
    item = {
        "id": 999,
        "name": "Test Game",
        "slug": "test-game",
        "summary": "A test",
        "genres": [{"id": 12, "name": "Role-playing (RPG)"}],
        "themes": [{"id": 1, "name": "Action"}],
        "keywords": [
            {"id": 50, "name": "roguelike"},
            {"id": 51, "name": "permadeath"},
        ],
        "first_release_date": 1600300800,
    }
    game = IGDBClient._parse(item)
    assert game.keyword_names == ["roguelike", "permadeath"]


def test_keyword_names_defaults_empty(client):
    item = {
        "id": 999,
        "name": "Test Game",
        "slug": "test-game",
        "summary": "A test",
        "genres": [],
        "themes": [],
        "first_release_date": None,
    }
    game = IGDBClient._parse(item)
    assert game.keyword_names == []
