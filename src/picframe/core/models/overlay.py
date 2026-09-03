"""Domain model for the WebKitGTK overlay plugin system (issue #739).

This module holds the pure, IO-free pieces of the overlay feature:

* ``PluginDescriptor`` — an immutable description of a discovered plugin,
  produced by the manifest loader (infrastructure adapter) and consumed by the
  API layer and the overlay controller port.
* ``plugin_config_defaults`` / ``validate_plugin_config`` — helpers that turn a
  plugin's ``config_schema`` into default values and validate user-supplied
  per-plugin config against that schema.

No WebKitGTK / GTK imports live here: the loader and the out-of-process worker
are the only components that touch the browser engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Allowed ``type`` values in a plugin ``config_schema`` field definition. Kept
# narrow on purpose; extend when a real plugin needs more.
_CONFIG_FIELD_TYPES: dict[str, tuple[type[Any], ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
}


class PluginConfigError(ValueError):
    """Raised when a plugin manifest or per-plugin config payload is invalid."""


@dataclass(frozen=True)
class PluginDescriptor:
    """Immutable description of a discovered overlay plugin.

    Attributes:
        id: Stable plugin identifier (defaults to the plugin directory name).
        name: Human-readable display name.
        description: Short description shown in the web UI.
        icon: Emoji or short label used for the dock icon.
        trigger: How the plugin is activated (``"icon"`` = dock icon tap).
        position: Default screen position (e.g. ``"top-right"``).
        size: Optional ``{"w": int, "h": int}`` preferred size.
        requires: Optional capability requirements (informational).
        config_schema: Mapping of field name -> field definition describing the
            per-plugin user configuration form and validation rules.
        entry: HTML entry file relative to the plugin directory.
        directory: Absolute path to the plugin directory on disk.
    """

    id: str
    name: str = ""
    description: str = ""
    icon: str = ""
    trigger: str = "icon"
    position: str = "top-right"
    size: dict[str, int] | None = None
    requires: list[str] = field(default_factory=list)
    config_schema: dict[str, dict[str, Any]] = field(default_factory=dict)
    entry: str = "index.html"
    directory: str = ""


def plugin_config_defaults(config_schema: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Return the default config values declared by a plugin ``config_schema``."""
    defaults: dict[str, Any] = {}
    for field_name, field_schema in config_schema.items():
        if not isinstance(field_schema, dict):
            continue
        if "default" in field_schema:
            defaults[field_name] = field_schema["default"]
    return defaults


def _coerce_field_type(field_name: str, field_schema: dict[str, Any], value: Any) -> Any:
    declared_type = str(field_schema.get("type", "string"))
    if declared_type not in _CONFIG_FIELD_TYPES:
        raise PluginConfigError(
            f"Plugin config field '{field_name}' has unsupported type '{declared_type}'"
        )
    # ``bool`` is a subclass of ``int`` in Python; exclude it from integer/number.
    if isinstance(value, bool) and declared_type in {"integer", "number"}:
        raise PluginConfigError(f"Plugin config field '{field_name}' must be {declared_type}")
    allowed = _CONFIG_FIELD_TYPES[declared_type]
    if not isinstance(value, allowed):
        raise PluginConfigError(f"Plugin config field '{field_name}' must be {declared_type}")
    enum_values = field_schema.get("enum")
    if enum_values is not None and value not in enum_values:
        raise PluginConfigError(f"Plugin config field '{field_name}' must be one of {enum_values}")
    return value


def validate_plugin_config(
    config_schema: dict[str, dict[str, Any]],
    payload: Any,
) -> dict[str, Any]:
    """Validate a per-plugin config payload against its ``config_schema``.

    Returns the effective config: manifest defaults merged with the validated
    user payload. Unknown keys are rejected; required fields must be present;
    declared types and ``enum`` constraints are enforced.
    """
    if not isinstance(payload, dict):
        raise PluginConfigError("Plugin config must be an object")

    unknown = sorted(set(payload) - set(config_schema))
    if unknown:
        raise PluginConfigError(f"Plugin config has unknown fields: {', '.join(unknown)}")

    result: dict[str, Any] = plugin_config_defaults(config_schema)
    for field_name, field_schema in config_schema.items():
        if not isinstance(field_schema, dict):
            raise PluginConfigError(f"Plugin config field '{field_name}' must be an object")
        required = bool(field_schema.get("required", False))
        if field_name in payload:
            result[field_name] = _coerce_field_type(field_name, field_schema, payload[field_name])
        elif field_name in result:
            # A default is already present; keep it.
            continue
        elif required:
            raise PluginConfigError(f"Plugin config field '{field_name}' is required")
    return result
