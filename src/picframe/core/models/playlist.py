"""Playlist query models."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PlaylistCriteria:
    """Configuration-derived media selection criteria."""

    pic_dir: str = "~/Pictures"
    subdirectory: str = ""
    date_from: str | float | int | None = ""
    date_to: str | float | int | None = ""
    location_filter: str = ""
    tags_filter: str = ""
    shuffle: bool = True
    sort_cols: str = "fname ASC"
    recent_n: int = 0
