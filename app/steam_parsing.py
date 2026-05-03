"""Shared Steam store parsing helpers."""

from __future__ import annotations

from typing import Any

from selectolax.parser import HTMLParser


def dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = value.strip()
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


def extract_store_tags(store_html: str) -> list[str]:
    parser = HTMLParser(store_html)
    tags = [
        node.text(strip=True)
        for node in parser.css("a.app_tag")
        if node.text(strip=True)
    ]
    if tags:
        return dedupe_preserve_order(tags)

    # Some Steam page variants omit the class but still expose tag links.
    fallback_tags = [
        node.text(strip=True)
        for node in parser.css('a[href*="/tags/en/"]')
        if node.text(strip=True)
    ]
    return dedupe_preserve_order(fallback_tags)


def platform_labels(data: dict[str, Any]) -> list[str]:
    platforms = data.get("platforms")
    if not isinstance(platforms, dict):
        return []
    result: list[str] = []
    if bool(platforms.get("windows")):
        result.append("Windows")
    if bool(platforms.get("mac")):
        result.append("macOS")
    if bool(platforms.get("linux")):
        result.append("Linux")
    return result


def steam_api_descriptions(data: dict[str, Any], key: str) -> list[str]:
    items = data.get(key)
    if not isinstance(items, list):
        return []
    values: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        description = str(item.get("description") or "").strip()
        if description:
            values.append(description)
    return dedupe_preserve_order(values)


def html_to_text(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    parser = HTMLParser(raw)
    text = parser.text(separator=" ", strip=True)
    cleaned = " ".join(text.split())
    return cleaned or None
