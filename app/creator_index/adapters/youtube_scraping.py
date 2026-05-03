"""YouTube HTML scraping helpers shared by the source-index YouTube adapter.

Extracted from the former app.ingestion.sources.youtube module.
"""

from __future__ import annotations

import json
from typing import Any

from selectolax.parser import HTMLParser

YOUTUBE_SEARCH_URL = "https://www.youtube.com/results"
CHANNEL_FILTER = "EgIQAg%3D%3D"  # YouTube search filter: channels only

# Browser-like headers + consent cookie for HTML scraping.
# SOCS cookie bypasses YouTube's GDPR consent gate without an account.
YT_SCRAPE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Cookie": "SOCS=CAISEwgDEgk2NjY2NjY2NjYaAmVuIAEaBgiAnNqnBg; CONSENT=YES+yt.472869719.en+FX+756",
}


def extract_initial_data(html: str) -> dict[str, Any]:
    """Extract the ytInitialData JSON blob from a YouTube HTML page."""
    marker = "var ytInitialData = "
    tree = HTMLParser(html)
    for script in tree.css("script"):
        text = script.text(deep=False)
        if marker not in text:
            continue
        start = text.index(marker) + len(marker)
        data, _ = json.JSONDecoder().raw_decode(text, start)
        return data  # type: ignore[return-value]
    raise RuntimeError("Could not locate ytInitialData in YouTube HTML.")


def iter_renderers(node: Any, key: str):
    """Recursively yield all dicts keyed by *key* in *node*."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key and isinstance(v, dict):
                yield v
            else:
                yield from iter_renderers(v, key)
    elif isinstance(node, list):
        for item in node:
            yield from iter_renderers(item, key)
