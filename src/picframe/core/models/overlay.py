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

# Nine-anchor screen positions used for panel placement (``position``) —
# issue #752.
OVERLAY_ANCHORS: tuple[str, ...] = (
    "top-left",
    "top-center",
    "top-right",
    "middle-left",
    "middle-center",
    "middle-right",
    "bottom-left",
    "bottom-center",
    "bottom-right",
)
OVERLAY_DISPLAY_MODES: tuple[str, ...] = ("persistent", "auto_hide")


class PluginConfigError(ValueError):
    """Raised when a plugin manifest or per-plugin config payload is invalid."""


@dataclass(frozen=True)
class PluginDescriptor:
    """Immutable description of a discovered overlay plugin.

    Attributes:
        id: Stable plugin identifier (defaults to the plugin directory name).
        name: Human-readable display name.
        description: Short description shown in the web UI.
        icon: Emoji or short label used for the dock icon (fallback when no
            ``icon_svg`` is present).
        icon_svg: Inline SVG markup (single-color, ``stroke="currentColor"``)
            read from an optional ``icon.svg`` file in the plugin directory.
            When non-empty the dock inlines it so the icon inherits the dock
            text color and renders crisply without an emoji font.
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
    icon_svg: str = ""
    trigger: str = "icon"
    position: str = "top-right"
    size: dict[str, int] | None = None
    # Default duration policy for this plugin's panel; overridden per-plugin by
    # the user-editable ``PluginLayout.display_mode`` (issue #752). Previously
    # this was a single global ``overlay.display_mode``.
    default_display_mode: str = "auto_hide"
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


# ---------------------------------------------------------------------------
# Per-plugin layout (issue #752)
#
# The fixed overlay-plugin layout schema — user-editable position, size,
# content alignment, display mode, idle-hide and z-order — kept separate from
# the plugin-author-owned ``config_schema`` so ``validate_plugin_config`` and
# plugin manifests are unaffected. Layout is persisted under
# ``overlay.plugin_layout.<id>.*`` and applied by the shell per panel.
# ---------------------------------------------------------------------------

# Fields of a PluginLayout, in stable order. ``None`` means "inherit"
# (idle_hide_seconds), "use plugin default" (width/height), or "no scaling"
# (scale, for fill-mode plugins). ``scale`` zooms a scale-mode plugin (one with
# a manifest ``size``); ``width``/``height`` size a fill-mode panel (no ``size``).
_LAYOUT_FIELDS: tuple[str, ...] = (
    "position",
    "width",
    "height",
    "scale",
    "display_mode",
    "idle_hide_seconds",
    "z_order",
)


class PluginLayoutError(ValueError):
    """Raised when a per-plugin layout payload is invalid (issue #752)."""


def plugin_layout_defaults(descriptor: PluginDescriptor) -> dict[str, Any]:
    """Return the default layout for a plugin derived from its manifest.

    A plugin **with** a manifest ``size`` is in *scale mode*: the shell sizes the
    panel to ``design × scale`` (so its aspect matches the widget — no
    contain-fit gaps) and zooms the iframe with ``transform: scale(scale)``.
    ``scale`` defaults to ``1.0``; ``width``/``height`` are unused (``None``).

    A plugin **without** a manifest ``size`` is in *fill mode*: the iframe fills
    the panel (``100% × 100%``) and ``width``/``height`` enlarge the panel (the
    Leaflet map absorbs the extra space). ``scale`` is ``None`` (no transform).

    ``position`` comes from the manifest; ``display_mode`` from
    ``default_display_mode``; ``idle_hide_seconds`` defaults to ``None``
    (inherit the global value); ``z_order`` defaults to ``0``.
    """
    has_size = bool(descriptor.size)
    return {
        "position": descriptor.position,
        "width": None,
        "height": None,
        "scale": 1.0 if has_size else None,
        "display_mode": descriptor.default_display_mode,
        "idle_hide_seconds": None,
        "z_order": 0,
    }


def validate_plugin_layout(payload: Any) -> dict[str, Any]:
    """Validate a per-plugin layout payload against the fixed overlay schema.

    Returns the normalized layout with defaults filled for absent fields,
    enforcing the 9-anchor enum (``position``), the display-mode enum,
    positive-integer sizes (``width``/``height``), a positive ``scale`` (or
    ``None`` = no scaling), a non-negative ``idle_hide_seconds`` (or ``None`` =
    inherit) and an integer ``z_order``. Unknown keys are rejected.
    """
    if not isinstance(payload, dict):
        raise PluginLayoutError("Plugin layout must be an object")

    unknown = sorted(set(payload) - set(_LAYOUT_FIELDS))
    if unknown:
        raise PluginLayoutError(f"Plugin layout has unknown fields: {', '.join(unknown)}")

    result: dict[str, Any] = {
        "position": "top-right",
        "width": None,
        "height": None,
        "scale": None,
        "display_mode": "auto_hide",
        "idle_hide_seconds": None,
        "z_order": 0,
    }

    position = payload.get("position")
    if position is not None:
        if not isinstance(position, str) or position not in OVERLAY_ANCHORS:
            raise PluginLayoutError(
                f"Plugin layout 'position' must be one of {list(OVERLAY_ANCHORS)}"
            )
        result["position"] = position

    for dim in ("width", "height"):
        value = payload.get(dim)
        if value is None:
            continue
        # ``bool`` is a subclass of ``int``; reject it explicitly.
        if isinstance(value, bool) or not isinstance(value, int):
            raise PluginLayoutError(f"Plugin layout '{dim}' must be a positive integer or null")
        if value <= 0:
            raise PluginLayoutError(f"Plugin layout '{dim}' must be a positive integer or null")
        result[dim] = value

    scale = payload.get("scale")
    if scale is not None:
        if isinstance(scale, bool) or not isinstance(scale, (int, float)):
            raise PluginLayoutError("Plugin layout 'scale' must be a positive number or null")
        if scale <= 0:
            raise PluginLayoutError("Plugin layout 'scale' must be a positive number or null")
        result["scale"] = float(scale)

    display_mode = payload.get("display_mode")
    if display_mode is not None:
        if not isinstance(display_mode, str) or display_mode not in OVERLAY_DISPLAY_MODES:
            raise PluginLayoutError(
                f"Plugin layout 'display_mode' must be one of {list(OVERLAY_DISPLAY_MODES)}"
            )
        result["display_mode"] = display_mode

    idle_hide_seconds = payload.get("idle_hide_seconds")
    if idle_hide_seconds is not None:
        if isinstance(idle_hide_seconds, bool) or not isinstance(idle_hide_seconds, (int, float)):
            raise PluginLayoutError(
                "Plugin layout 'idle_hide_seconds' must be a non-negative number or null"
            )
        if idle_hide_seconds < 0:
            raise PluginLayoutError(
                "Plugin layout 'idle_hide_seconds' must be a non-negative number or null"
            )
        result["idle_hide_seconds"] = float(idle_hide_seconds)

    z_order = payload.get("z_order")
    if z_order is not None:
        if isinstance(z_order, bool) or not isinstance(z_order, int):
            raise PluginLayoutError("Plugin layout 'z_order' must be an integer")
        result["z_order"] = z_order

    return result


def effective_plugin_layout(descriptor: PluginDescriptor, db_layout: Any) -> dict[str, Any]:
    """Return the effective layout for a plugin: manifest defaults merged with
    persisted user overrides from ``overlay.plugin_layout.<id>.*``.

    ``db_layout`` is the per-plugin layout dict read from the config repository
    (already validated on write). ``None``/absent values in ``db_layout`` keep
    the manifest default.
    """
    merged = plugin_layout_defaults(descriptor)
    if isinstance(db_layout, dict):
        for field_name in _LAYOUT_FIELDS:
            if field_name in db_layout and db_layout[field_name] is not None:
                merged[field_name] = db_layout[field_name]
    return merged


def normalize_legacy_overlay(overlay: Any) -> dict[str, Any]:
    """Normalize an ``overlay`` config dict for the widget model (issue #752).

    Bridges the legacy single-visible-plugin model to the multi-widget model:

    * ``visible_plugin`` (str|null) -> ``visible_plugins`` (list[str]) when the
      new key is absent (a ``null``/missing ``visible_plugin`` -> ``[]``).
    * ``visible_plugin`` (legacy) is re-derived from ``visible_plugins[0]`` when
      absent, so the out-of-process worker / shell (Phase 0 / #739, which still
      consume the single-plugin shape) keep rendering unchanged until Phase B
      switches them to the list.
    * the legacy global ``display_mode`` is passed through unchanged for the
      same worker/shell compatibility; the Pydantic ``OverlayConfig`` model
      ignores it (``extra='ignore'``), so the API surface only exposes the new
      per-plugin ``plugin_layout``.

    This is a read-time bridge only; it never drops legacy keys (Phase B removes
    the worker/shell consumers and then the passthrough).
    """
    if not isinstance(overlay, dict):
        return {}
    result = dict(overlay)
    if "visible_plugins" not in result:
        legacy = result.get("visible_plugin")
        result["visible_plugins"] = [legacy] if isinstance(legacy, str) and legacy else []
    if "visible_plugin" not in result:
        vps = result.get("visible_plugins")
        result["visible_plugin"] = vps[0] if isinstance(vps, list) and vps else None
    return result
