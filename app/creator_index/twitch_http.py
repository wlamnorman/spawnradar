"""Backward-compat shim — canonical module is now app.twitch.http."""

from app.twitch.http import (  # noqa: F401
    TwitchAppAuth,
    twitch_request_json,
)

__all__ = ["TwitchAppAuth", "twitch_request_json"]
