"""Runtime resource path resolution for Picframe-managed assets."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from picframe.core.repositories.interfaces import IConfigRepository

PICFRAME_DATA_TOKEN = "${PICFRAME_DATA}"

_LEGACY_RESOURCE_DEFAULTS = {
    "viewer.font_file": {
        "~/.picframe/data/fonts/NotoSans-Regular.ttf": (
            f"{PICFRAME_DATA_TOKEN}/fonts/NotoSans-Regular.ttf"
        ),
        "~/picframe_data/data/fonts/NotoSans-Regular.ttf": (
            f"{PICFRAME_DATA_TOKEN}/fonts/NotoSans-Regular.ttf"
        ),
    },
    "viewer.shader": {
        "~/.picframe/data/shaders/blend_new": f"{PICFRAME_DATA_TOKEN}/shaders/blend_new",
        "~/picframe_data/data/shaders/blend_new": f"{PICFRAME_DATA_TOKEN}/shaders/blend_new",
    },
    "viewer.mat_resource_folder": {
        "~/.picframe/data/mat": f"{PICFRAME_DATA_TOKEN}/mat",
        "~/picframe_data/data/mat": f"{PICFRAME_DATA_TOKEN}/mat",
    },
    "model.no_files_img": {
        "~/.picframe/data/no_pictures.jpg": f"{PICFRAME_DATA_TOKEN}/no_pictures.jpg",
        "~/picframe_data/data/no_pictures.jpg": f"{PICFRAME_DATA_TOKEN}/no_pictures.jpg",
    },
}


@dataclass(frozen=True)
class ResourcePaths:
    """Resolve Picframe-managed runtime resource paths for an active base dir."""

    base_dir: Path

    @classmethod
    def from_base_dir(cls, base_dir: str | os.PathLike[str]) -> ResourcePaths:
        return cls(Path(base_dir).expanduser().resolve(strict=False))

    @property
    def data_dir(self) -> Path:
        return self.base_dir / "data"

    @property
    def html_dir(self) -> Path:
        return self.base_dir / "html"

    @staticmethod
    def packaged_data_dir() -> Path:
        """Return the immutable package data directory bundled with Picframe."""
        import picframe

        return Path(picframe.__file__).parent / "data"

    @staticmethod
    def packaged_no_files_img() -> Path:
        """Return the packaged fallback image used when no media is available."""
        return ResourcePaths.packaged_data_dir() / "no_pictures.jpg"

    def resolve(self, value: Any) -> str:
        """Resolve supported runtime tokens and home-relative paths."""
        text = "" if value is None else str(value).strip()
        if not text:
            return text
        if text == PICFRAME_DATA_TOKEN:
            return str(self.data_dir)
        if text.startswith(f"{PICFRAME_DATA_TOKEN}/"):
            return str(self.data_dir / text[len(PICFRAME_DATA_TOKEN) + 1 :])
        return os.path.expanduser(text)

    def tokenized(self, path: Path) -> str:
        """Return a display path, preferring ${PICFRAME_DATA} under data_dir."""
        resolved = path.expanduser().resolve(strict=False)
        try:
            relative = resolved.relative_to(self.data_dir)
        except ValueError:
            return str(resolved)
        if str(relative) == ".":
            return PICFRAME_DATA_TOKEN
        return f"{PICFRAME_DATA_TOKEN}/{relative.as_posix()}"


def repair_legacy_resource_defaults(config_repository: IConfigRepository) -> None:
    """Rewrite exact legacy managed-resource defaults to portable tokens."""
    for key, replacements in _LEGACY_RESOURCE_DEFAULTS.items():
        current_value = config_repository.get_app_config(key)
        if not isinstance(current_value, str):
            continue
        replacement = replacements.get(current_value)
        if replacement is not None:
            config_repository.set_app_config(key, replacement)
