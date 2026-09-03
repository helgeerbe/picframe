"""Infrastructure adapter: plugin manifest loader for the overlay (#739).

Scans a configured ``plugin_dir`` for plugin sub-directories, reads each
``plugin.json`` manifest, and returns a list of ``PluginDescriptor`` objects.
This adapter is pure filesystem IO — it never imports WebKitGTK/GTK. The
overlay controller (Phase 1) and the API layer use it as the source of truth
for discovered plugins.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from picframe.core.models.overlay import PluginConfigError, PluginDescriptor

logger = logging.getLogger(__name__)

_MANIFEST_FILENAME = "plugin.json"


class PluginLoader:
    """Load overlay plugin descriptors from a plugin directory."""

    def __init__(self, plugin_dir: str | Path) -> None:
        self._plugin_dir = Path(plugin_dir).expanduser()

    @property
    def plugin_dir(self) -> Path:
        return self._plugin_dir

    def list_plugins(self) -> list[PluginDescriptor]:
        """Return discovered plugin descriptors sorted by id.

        A missing or empty ``plugin_dir`` yields an empty list. Malformed
        manifests are skipped with a warning so a single bad plugin never
        breaks discovery.
        """
        if not self._plugin_dir.is_dir():
            return []

        descriptors: list[PluginDescriptor] = []
        for entry in sorted(self._plugin_dir.iterdir(), key=lambda p: p.name):
            if not entry.is_dir():
                continue
            manifest = entry / _MANIFEST_FILENAME
            if not manifest.is_file():
                continue
            try:
                raw = manifest.read_text(encoding="utf-8")
                data = json.loads(raw)
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Skipping plugin manifest %s: %s", manifest, exc)
                continue
            try:
                descriptors.append(_descriptor_from_manifest(entry, data))
            except PluginConfigError as exc:
                logger.warning("Skipping invalid plugin in %s: %s", entry, exc)
                continue
        return descriptors


def _descriptor_from_manifest(directory: Path, data: Any) -> PluginDescriptor:
    """Build a ``PluginDescriptor`` from a parsed ``plugin.json`` mapping."""
    if not isinstance(data, dict):
        raise PluginConfigError("plugin.json must be a JSON object")

    plugin_id = str(data.get("id") or directory.name)
    if not plugin_id:
        raise PluginConfigError("plugin id must not be empty")

    raw_size = data.get("size")
    size: dict[str, int] | None = None
    if isinstance(raw_size, dict):
        size = {
            "w": int(raw_size.get("w", 0)),
            "h": int(raw_size.get("h", 0)),
        }

    raw_schema = data.get("config_schema", {})
    if raw_schema is None:
        raw_schema = {}
    if not isinstance(raw_schema, dict):
        raise PluginConfigError("config_schema must be an object")
    config_schema: dict[str, dict[str, Any]] = {}
    for field_name, field_schema in raw_schema.items():
        if not isinstance(field_schema, dict):
            raise PluginConfigError(f"config_schema field '{field_name}' must be an object")
        config_schema[str(field_name)] = dict(field_schema)

    raw_requires = data.get("requires", [])
    if raw_requires is None:
        raw_requires = []
    requires = [str(item) for item in raw_requires] if isinstance(raw_requires, list) else []

    return PluginDescriptor(
        id=plugin_id,
        name=str(data.get("name", plugin_id)),
        description=str(data.get("description", "")),
        icon=str(data.get("icon", "")),
        trigger=str(data.get("trigger", "icon")),
        position=str(data.get("position", "top-right")),
        size=size,
        requires=requires,
        config_schema=config_schema,
        entry=str(data.get("entry", "index.html")),
        directory=str(directory),
    )
