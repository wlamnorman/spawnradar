"""Small helpers for JSON values stored in SQLite text columns."""

from __future__ import annotations

import json
from typing import Any


def dump_json(value: object) -> str:
    """Serialize a Python value for storage in a JSON text column."""
    return json.dumps(value)


def load_json_object(raw: str | None) -> dict[str, Any]:
    """Deserialize a JSON object, defaulting to an empty object."""
    value = json.loads(raw or "{}")
    return value if isinstance(value, dict) else {}


def load_json_list(raw: str | None) -> list[Any]:
    """Deserialize a JSON array, defaulting to an empty list."""
    value = json.loads(raw or "[]")
    return value if isinstance(value, list) else []


def load_json_string_list(raw: str | None) -> list[str]:
    """Deserialize a JSON array and keep only string elements."""
    return [value for value in load_json_list(raw) if isinstance(value, str)]


def load_json_int_list(raw: str | None) -> list[int]:
    """Deserialize a JSON array and keep only integer elements."""
    return [value for value in load_json_list(raw) if isinstance(value, int)]
