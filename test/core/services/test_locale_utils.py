"""Tests for locale helper functions."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

from picframe.core.services.locale_utils import (
    format_datetime_for_locale,
    language_from_locale,
)


def test_language_from_locale_normalizes_locale_names() -> None:
    assert language_from_locale("de_DE.utf8") == "de"
    assert language_from_locale("en_US.UTF-8") == "en"
    assert language_from_locale("C.utf8") == "en"
    assert language_from_locale("POSIX") == "en"


def test_format_datetime_for_locale_temporarily_sets_lc_time() -> None:
    calls: list[tuple[int, str | None]] = []

    def fake_setlocale(category: int, value: str | None = None) -> str:
        calls.append((category, value))
        return "C" if value is None else value

    with patch(
        "picframe.core.services.locale_utils.locale.setlocale",
        side_effect=fake_setlocale,
    ):
        result = format_datetime_for_locale(
            datetime(2024, 3, 9, 12, 0, 0),
            "%Y-%m-%d",
            "de_DE.utf8",
        )

    assert result == "2024-03-09"
    assert [value for _, value in calls] == [None, "de_DE.utf8", "C"]
