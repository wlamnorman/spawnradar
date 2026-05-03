"""Structured dev-game presets that can be reseeded or snapshotted."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

Preset = dict[str, Any]
PRESET_FILE = Path(__file__).with_name("game_presets.json")


def _clone(value: dict[str, Preset]) -> dict[str, Preset]:
    return json.loads(json.dumps(value))


def load_game_presets(
    preset_path: str | Path | None = None,
) -> dict[str, Preset]:
    """Load structured game presets from disk."""
    path = Path(preset_path) if preset_path is not None else PRESET_FILE
    if not path.exists():
        raise FileNotFoundError(f"Game preset file not found: {path}")
    loaded = json.loads(path.read_text())
    if not isinstance(loaded, dict):
        raise ValueError(f"Game preset file must contain an object: {path}")
    return _clone(loaded)


def save_game_presets(
    presets: dict[str, Preset], preset_path: str | Path | None = None
) -> Path:
    """Persist structured game presets to disk."""
    path = Path(preset_path) if preset_path is not None else PRESET_FILE
    path.write_text(json.dumps(presets, indent=2) + "\n")
    return path
