"""Helpers for building display overlay text."""

from __future__ import annotations

from typing import Iterable


def apply_geo_suppress_list(location: object, suppress_list: Iterable[object] | None) -> str:
    """Remove configured substrings from a human-readable location string."""
    text = str(location or "").strip()
    if not text:
        return ""

    for raw_item in suppress_list or ():
        item = str(raw_item or "").strip()
        if item:
            text = text.replace(item, "")

    parts = [part.strip(" ,") for part in text.split(",")]
    return ", ".join(part for part in parts if part)
