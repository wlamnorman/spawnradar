"""Tests for the authenticated matches load-test helper."""

import pytest

from app.devtools.matches_load_test import (
    _extract_csrf_token,
    _extract_error_message,
    _percentile,
)


def test_extract_csrf_token_reads_hidden_field() -> None:
    html = """
    <form method="post">
        <input type="hidden" name="csrf_token" value="csrf-123" />
    </form>
    """

    assert _extract_csrf_token(html) == "csrf-123"


def test_extract_error_message_reads_alert_copy() -> None:
    html = """
    <div class="alert alert-error">
        Invalid email or password.
    </div>
    """

    assert _extract_error_message(html) == "Invalid email or password."


def test_percentile_interpolates_between_points() -> None:
    assert _percentile([0.5, 1.0, 2.0, 4.0], 0.95) == pytest.approx(3.7)
