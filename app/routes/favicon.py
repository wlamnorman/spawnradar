from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Response
from fastapi.responses import FileResponse

router = APIRouter()

_APP_DIR = Path(__file__).resolve().parents[1]
_FRONTEND_STATIC_DIR = _APP_DIR / "frontend" / "static"

_ROOT_FAVICON_ASSETS: tuple[tuple[str, str], ...] = (
    ("/favicon.ico", "favicon/favicon.ico"),
    ("/favicon.svg", "favicon/favicon.svg"),
    ("/favicon-96x96.png", "favicon/favicon-96x96.png"),
    ("/apple-touch-icon.png", "favicon/apple-touch-icon.png"),
    (
        "/web-app-manifest-192x192.png",
        "favicon/web-app-manifest-192x192.png",
    ),
    (
        "/web-app-manifest-512x512.png",
        "favicon/web-app-manifest-512x512.png",
    ),
    ("/site.webmanifest", "favicon/site.webmanifest"),
)


def _register_root_favicon_asset(route_path: str, asset_path: str) -> None:
    asset_file = _FRONTEND_STATIC_DIR / asset_path

    async def _serve_asset() -> FileResponse:
        return FileResponse(asset_file)

    router.add_api_route(
        route_path,
        _serve_asset,
        methods=["GET", "HEAD"],
        include_in_schema=False,
    )


for route_path, asset_path in _ROOT_FAVICON_ASSETS:
    _register_root_favicon_asset(route_path, asset_path)


@router.get(
    "/.well-known/appspecific/com.chrome.devtools.json",
    include_in_schema=False,
)
async def chrome_devtools_appspecific() -> Response:
    """Silence harmless Chrome DevTools discovery probes."""
    return Response(status_code=204)
