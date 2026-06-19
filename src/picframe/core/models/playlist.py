"""Playlist query models."""

from dataclasses import dataclass

SHUFFLE_MODE_STANDARD = "standard"
SHUFFLE_MODE_FEWER_REPEATS = "fewer_repeats"
SUPPORTED_SHUFFLE_MODES = {
    SHUFFLE_MODE_STANDARD,
    SHUFFLE_MODE_FEWER_REPEATS,
}


def normalize_shuffle_mode(value: object) -> str:
    """Return a supported shuffle mode, falling back to standard."""
    mode = str(value or "").strip().lower()
    if mode in SUPPORTED_SHUFFLE_MODES:
        return mode
    return SHUFFLE_MODE_STANDARD


@dataclass(frozen=True)
class PlaylistCriteria:
    """Configuration-derived media selection criteria."""

    pic_dir: str = "~/Pictures"
    subdirectory: str = ""
    date_from: str | float | int | None = ""
    date_to: str | float | int | None = ""
    location_filter: str = ""
    tags_filter: str = ""
    location_language: str = "en"
    shuffle: bool = True
    shuffle_mode: str = SHUFFLE_MODE_STANDARD
    sort_cols: str = "fname ASC"
    recent_n: int = 0
