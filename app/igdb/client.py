from __future__ import annotations

import logging
from collections.abc import Sequence

import httpx

from app.igdb.models import IGDBGame
from app.igdb.taxonomy import IGDBGenre, IGDBTheme

log = logging.getLogger(__name__)
_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
_IGDB_GAMES_URL = "https://api.igdb.com/v4/games"
_IGDB_KEYWORDS_URL = "https://api.igdb.com/v4/keywords"


class IGDBClient:
    def __init__(self, *, client_id: str, client_secret: str) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._token: str | None = None
        self._keyword_id_cache: dict[str, int] = {}

    async def _get_token(self, http: httpx.AsyncClient) -> str:
        if self._token:
            return self._token
        resp = await http.post(
            _TOKEN_URL,
            params={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "grant_type": "client_credentials",
            },
        )
        resp.raise_for_status()
        self._token = resp.json()["access_token"]
        if not isinstance(self._token, str):
            raise ValueError(
                "IGDB token response did not include access_token."
            )
        return self._token

    async def fetch_games(
        self, *, limit: int = 500, offset: int = 0
    ) -> list[IGDBGame]:
        query = self._build_games_query(limit=limit, offset=offset)
        async with httpx.AsyncClient(timeout=30) as http:
            token = await self._get_token(http)
            resp = await http.post(
                _IGDB_GAMES_URL,
                headers={
                    "Client-ID": self._client_id,
                    "Authorization": f"Bearer {token}",
                },
                content=query,
            )
            resp.raise_for_status()
            return [self._parse(item) for item in resp.json()]

    async def fetch_game_by_id(self, igdb_id: int) -> IGDBGame | None:
        query = self._build_single_game_query(igdb_id)
        async with httpx.AsyncClient(timeout=30) as http:
            token = await self._get_token(http)
            resp = await http.post(
                _IGDB_GAMES_URL,
                headers={
                    "Client-ID": self._client_id,
                    "Authorization": f"Bearer {token}",
                },
                content=query,
            )
            resp.raise_for_status()
            items = resp.json()
        if not items:
            return None
        return self._parse(items[0])

    async def fetch_games_by_tags(
        self,
        *,
        genre_ids: tuple[int, ...] = (),
        theme_ids: tuple[int, ...] = (),
        limit: int = 25,
        offset: int = 0,
    ) -> list[IGDBGame]:
        query = self._build_tag_filtered_games_query(
            genre_ids=genre_ids,
            theme_ids=theme_ids,
            limit=limit,
            offset=offset,
        )
        log.debug(
            "IGDB fetch_games_by_tags query: genres=%s themes=%s body=%r",
            list(genre_ids),
            list(theme_ids),
            query,
        )
        async with httpx.AsyncClient(timeout=30) as http:
            token = await self._get_token(http)
            resp = await http.post(
                _IGDB_GAMES_URL,
                headers={
                    "Client-ID": self._client_id,
                    "Authorization": f"Bearer {token}",
                },
                content=query,
            )
            resp.raise_for_status()
            items = resp.json()
        log.debug(
            "IGDB fetch_games_by_tags returned %d rows for genres=%s themes=%s",
            len(items),
            list(genre_ids),
            list(theme_ids),
        )
        return [self._parse(item) for item in items]

    async def resolve_keyword_ids(
        self, keyword_names: Sequence[str]
    ) -> dict[str, int]:
        """Resolve IGDB keyword names to numeric IDs (cached)."""
        result: dict[str, int] = {}
        to_fetch: list[str] = []
        for name in keyword_names:
            if name in self._keyword_id_cache:
                result[name] = self._keyword_id_cache[name]
            else:
                to_fetch.append(name)
        if not to_fetch:
            return result
        async with httpx.AsyncClient(timeout=30) as http:
            token = await self._get_token(http)
            headers = {
                "Client-ID": self._client_id,
                "Authorization": f"Bearer {token}",
            }
            for name in to_fetch:
                safe_name = name.replace('"', '\\"')
                query = f'fields id,name; where name = "{safe_name}"; limit 1;'
                resp = await http.post(
                    _IGDB_KEYWORDS_URL, headers=headers, content=query
                )
                resp.raise_for_status()
                items = resp.json()
                if items:
                    kid = int(items[0]["id"])
                    self._keyword_id_cache[name] = kid
                    result[name] = kid
                else:
                    log.warning("IGDB keyword not found: %s", name)
        return result

    _KEYWORD_FIELDS = (
        "fields id,name,slug,summary,cover.url,genres.id,genres.name,"
        "themes.id,themes.name,keywords.id,keywords.name,"
        "involved_companies.developer,involved_companies.company.name,"
        "platforms.id,platforms.name,first_release_date"
    )

    async def fetch_games_by_name(
        self, name: str, *, limit: int = 3
    ) -> list[IGDBGame]:
        """Search IGDB games by name."""
        safe_name = name.replace('"', '\\"')
        query = f'search "{safe_name}"; {self._KEYWORD_FIELDS}; limit {limit};'
        async with httpx.AsyncClient(timeout=30) as http:
            token = await self._get_token(http)
            resp = await http.post(
                _IGDB_GAMES_URL,
                headers={
                    "Client-ID": self._client_id,
                    "Authorization": f"Bearer {token}",
                },
                content=query,
            )
            resp.raise_for_status()
            return [self._parse(item) for item in resp.json()]

    async def fetch_games_by_keywords(
        self,
        keyword_ids: Sequence[int],
        *,
        genre_ids: Sequence[int] = (),
        theme_ids: Sequence[int] = (),
        limit: int = 50,
    ) -> list[IGDBGame]:
        """Fetch games matching keyword/genre/theme filters."""
        conditions: list[str] = []
        if keyword_ids:
            kid_str = ",".join(str(k) for k in keyword_ids)
            conditions.append(f"keywords = ({kid_str})")
        # Drop Indie genre (32) to avoid overly broad results
        filtered_genres = [g for g in genre_ids if g != 32]
        if filtered_genres:
            gid_str = ",".join(str(g) for g in filtered_genres)
            conditions.append(f"genres = ({gid_str})")
        if theme_ids:
            tid_str = ",".join(str(t) for t in theme_ids)
            conditions.append(f"themes = ({tid_str})")
        # Always exclude DLCs/expansions via version_parent = null
        conditions.append("version_parent = null")
        where_clause = " & ".join(conditions)
        query = (
            f"{self._KEYWORD_FIELDS}; "
            f"where {where_clause}; "
            f"sort total_rating_count desc; "
            f"limit {limit};"
        )
        log.debug("IGDB fetch_games_by_keywords query: %r", query)
        async with httpx.AsyncClient(timeout=30) as http:
            token = await self._get_token(http)
            resp = await http.post(
                _IGDB_GAMES_URL,
                headers={
                    "Client-ID": self._client_id,
                    "Authorization": f"Bearer {token}",
                },
                content=query,
            )
            resp.raise_for_status()
            return [self._parse(item) for item in resp.json()]

    @staticmethod
    def _build_games_query(*, limit: int, offset: int) -> str:
        genre_filter = (
            "(" + ",".join(str(g.value) for g in IGDBGenre.gaming()) + ")"
        )
        return (
            # IGDB genre filtering here is intended as membership, not exact
            # tag-set equality: include games that have any of these genres,
            # even if they also have additional genres or themes.
            "fields id,name,slug,summary,cover.url,genres.id,genres.name,"
            "themes.id,themes.name,involved_companies.developer,"
            "involved_companies.company.name,"
            "platforms.id,platforms.name,first_release_date; "
            f"where genres = {genre_filter} & category = 0; "
            "sort first_release_date desc; "
            f"limit {limit}; offset {offset};"
        )

    @staticmethod
    def _build_single_game_query(igdb_id: int) -> str:
        return (
            "fields id,name,slug,summary,cover.url,genres.id,genres.name,"
            "themes.id,themes.name,involved_companies.developer,"
            "involved_companies.company.name,"
            "platforms.id,platforms.name,first_release_date; "
            f"where id = {igdb_id}; "
            "limit 1;"
        )

    @staticmethod
    def _build_tag_filtered_games_query(
        *,
        genre_ids: tuple[int, ...],
        theme_ids: tuple[int, ...],
        limit: int,
        offset: int,
    ) -> str:
        conditions: list[str] = []
        if genre_ids:
            genre_filter = (
                str(genre_ids[0])
                if len(genre_ids) == 1
                else "("
                + ",".join(str(genre_id) for genre_id in genre_ids)
                + ")"
            )
            # Genre filtering is intended as membership, not exact tag-set
            # equality: include games that have any of these genres.
            conditions.append(f"genres = {genre_filter}")
        if theme_ids:
            theme_filter = (
                str(theme_ids[0])
                if len(theme_ids) == 1
                else "("
                + ",".join(str(theme_id) for theme_id in theme_ids)
                + ")"
            )
            # Theme filtering is also membership-based: include games that
            # have any of these themes, even if other themes are present.
            conditions.append(f"themes = {theme_filter}")
        if not conditions:
            raise ValueError(
                "fetch_games_by_tags requires at least one genre or theme filter."
            )
        return (
            "fields id,name,slug,summary,cover.url,genres.id,genres.name,"
            "themes.id,themes.name,involved_companies.developer,"
            "involved_companies.company.name,"
            "platforms.id,platforms.name,first_release_date; "
            f"where {' & '.join(conditions)}; "
            "sort first_release_date desc; "
            f"limit {limit}; offset {offset};"
        )

    @staticmethod
    def _parse(item: dict) -> IGDBGame:
        genres = item.get("genres") or []
        themes = item.get("themes") or []
        platforms = item.get("platforms") or []
        involved_companies = item.get("involved_companies") or []
        # IGDB returns cover.url as //images.igdb.com/... — normalise to https
        raw_cover = ((item.get("cover") or {}).get("url") or "").strip()
        cover_url: str | None = None
        if raw_cover:
            url = (
                raw_cover
                if raw_cover.startswith("http")
                else f"https:{raw_cover}"
            )
            # Upgrade thumbnail to cover_big (264x374)
            cover_url = url.replace("/t_thumb/", "/t_cover_big/")
        developer_names: list[str] = []
        seen_developers: set[str] = set()
        for company_link in involved_companies:
            if not isinstance(company_link, dict):
                continue
            if not bool(company_link.get("developer")):
                continue
            company = company_link.get("company")
            if not isinstance(company, dict):
                continue
            developer_name = str(company.get("name") or "").strip()
            if not developer_name:
                continue
            key = developer_name.casefold()
            if key in seen_developers:
                continue
            seen_developers.add(key)
            developer_names.append(developer_name)
        return IGDBGame(
            igdb_id=item["id"],
            name=item["name"],
            slug=item.get("slug", ""),
            summary=item.get("summary"),
            cover_url=cover_url,
            developer_names=developer_names,
            genre_ids=[
                IGDBGenre(g["id"])
                for g in genres
                if g["id"] in IGDBGenre._value2member_map_
            ],
            theme_ids=[
                IGDBTheme(t["id"])
                for t in themes
                if t["id"] in IGDBTheme._value2member_map_
            ],
            first_release_date=item.get("first_release_date"),
            platform_ids=[
                int(p["id"])
                for p in platforms
                if isinstance(p, dict) and isinstance(p.get("id"), int)
            ],
            platform_names=[
                str(p["name"]).strip()
                for p in platforms
                if isinstance(p, dict) and str(p.get("name") or "").strip()
            ],
            keyword_names=[
                k["name"]
                for k in (item.get("keywords") or [])
                if isinstance(k, dict) and "name" in k
            ],
        )
