"""Tests for the overlay domain model (PluginDescriptor + config helpers)."""

import pytest

from picframe.core.models.overlay import (
    PluginConfigError,
    PluginDescriptor,
    plugin_config_defaults,
    validate_plugin_config,
)


def test_plugin_descriptor_defaults() -> None:
    descriptor = PluginDescriptor(id="clock")
    assert descriptor.id == "clock"
    assert descriptor.name == ""
    assert descriptor.trigger == "icon"
    assert descriptor.position == "top-right"
    assert descriptor.size is None
    assert descriptor.requires == []
    assert descriptor.config_schema == {}
    assert descriptor.entry == "index.html"
    assert descriptor.directory == ""


def test_plugin_config_defaults_extracts_defaults() -> None:
    schema = {
        "api_key": {"type": "string", "required": True, "label": "API key"},
        "units": {"type": "string", "default": "metric", "enum": ["metric", "imperial"]},
        "refresh": {"type": "integer", "default": 600},
    }
    assert plugin_config_defaults(schema) == {"units": "metric", "refresh": 600}


def test_validate_plugin_config_merges_defaults_and_validates_types() -> None:
    schema = {
        "api_key": {"type": "string", "required": True},
        "units": {"type": "string", "default": "metric", "enum": ["metric", "imperial"]},
        "refresh": {"type": "integer", "default": 600},
        "enabled": {"type": "boolean", "default": False},
    }
    result = validate_plugin_config(schema, {"api_key": "secret", "units": "imperial"})
    assert result == {
        "api_key": "secret",
        "units": "imperial",
        "refresh": 600,
        "enabled": False,
    }


def test_validate_plugin_config_rejects_unknown_keys() -> None:
    schema = {"api_key": {"type": "string", "required": True}}
    with pytest.raises(PluginConfigError, match="unknown fields"):
        validate_plugin_config(schema, {"api_key": "x", "bogus": 1})


def test_validate_plugin_config_requires_required_fields() -> None:
    schema = {"api_key": {"type": "string", "required": True}}
    with pytest.raises(PluginConfigError, match="required"):
        validate_plugin_config(schema, {})


def test_validate_plugin_config_enforces_types() -> None:
    schema = {"refresh": {"type": "integer", "default": 60}}
    with pytest.raises(PluginConfigError, match="must be integer"):
        validate_plugin_config(schema, {"refresh": "sixty"})


def test_validate_plugin_config_rejects_bool_as_number() -> None:
    schema = {"refresh": {"type": "integer", "default": 60}}
    with pytest.raises(PluginConfigError, match="must be integer"):
        validate_plugin_config(schema, {"refresh": True})


def test_validate_plugin_config_enforces_enum() -> None:
    schema = {"units": {"type": "string", "default": "metric", "enum": ["metric", "imperial"]}}
    with pytest.raises(PluginConfigError, match="must be one of"):
        validate_plugin_config(schema, {"units": "kelvin"})


def test_validate_plugin_config_rejects_non_object_payload() -> None:
    schema = {"api_key": {"type": "string", "required": True}}
    with pytest.raises(PluginConfigError, match="must be an object"):
        validate_plugin_config(schema, "not-a-dict")  # type: ignore[arg-type]


def test_validate_plugin_config_rejects_unsupported_field_type() -> None:
    schema = {"data": {"type": "blob"}}
    with pytest.raises(PluginConfigError, match="unsupported type"):
        validate_plugin_config(schema, {"data": "x"})


def test_validate_plugin_config_accepts_number_for_integer_or_number() -> None:
    schema = {
        "lat": {"type": "number", "required": True},
        "count": {"type": "integer", "required": True},
    }
    result = validate_plugin_config(schema, {"lat": 52.5, "count": 3})
    assert result == {"lat": 52.5, "count": 3}


# ---------------------------------------------------------------------------
# Per-plugin layout (issue #752)
# ---------------------------------------------------------------------------


def test_plugin_layout_defaults_derived_from_manifest() -> None:
    from picframe.core.models.overlay import plugin_layout_defaults

    descriptor = PluginDescriptor(
        id="weather",
        position="bottom-left",
        size={"w": 320, "h": 180},
        default_display_mode="persistent",
    )
    assert plugin_layout_defaults(descriptor) == {
        "position": "bottom-left",
        "width": None,
        "height": None,
        "scale": 1.0,
        "display_mode": "persistent",
        "idle_hide_seconds": None,
        "z_order": 0,
    }


def test_plugin_layout_defaults_when_size_absent() -> None:
    from picframe.core.models.overlay import plugin_layout_defaults

    descriptor = PluginDescriptor(id="clock", position="top-right")
    defaults = plugin_layout_defaults(descriptor)
    assert defaults["width"] is None
    assert defaults["height"] is None
    assert defaults["scale"] is None
    assert defaults["display_mode"] == "auto_hide"


def test_validate_plugin_layout_fills_defaults_for_absent_fields() -> None:
    from picframe.core.models.overlay import validate_plugin_layout

    result = validate_plugin_layout({})
    assert result == {
        "position": "top-right",
        "width": None,
        "height": None,
        "scale": None,
        "display_mode": "auto_hide",
        "idle_hide_seconds": None,
        "z_order": 0,
    }


def test_validate_plugin_layout_accepts_full_payload() -> None:
    from picframe.core.models.overlay import validate_plugin_layout

    payload = {
        "position": "middle-center",
        "width": 400,
        "height": 200,
        "scale": 1.5,
        "display_mode": "persistent",
        "idle_hide_seconds": 10.0,
        "z_order": 5,
    }
    assert validate_plugin_layout(payload) == payload


def test_validate_plugin_layout_rejects_non_object() -> None:
    from picframe.core.models.overlay import PluginLayoutError, validate_plugin_layout

    with pytest.raises(PluginLayoutError, match="must be an object"):
        validate_plugin_layout("nope")  # type: ignore[arg-type]


def test_validate_plugin_layout_rejects_unknown_fields() -> None:
    from picframe.core.models.overlay import PluginLayoutError, validate_plugin_layout

    with pytest.raises(PluginLayoutError, match="unknown fields"):
        validate_plugin_layout({"bogus": 1})


def test_validate_plugin_layout_rejects_bad_anchor() -> None:
    from picframe.core.models.overlay import PluginLayoutError, validate_plugin_layout

    with pytest.raises(PluginLayoutError, match="position"):
        validate_plugin_layout({"position": "nowhere"})


def test_validate_plugin_layout_rejects_bad_scale() -> None:
    from picframe.core.models.overlay import PluginLayoutError, validate_plugin_layout

    with pytest.raises(PluginLayoutError, match="scale"):
        validate_plugin_layout({"scale": 0})
    with pytest.raises(PluginLayoutError, match="scale"):
        validate_plugin_layout({"scale": -1.0})


def test_validate_plugin_layout_rejects_non_number_scale() -> None:
    from picframe.core.models.overlay import PluginLayoutError, validate_plugin_layout

    with pytest.raises(PluginLayoutError, match="scale"):
        validate_plugin_layout({"scale": "big"})


def test_validate_plugin_layout_rejects_bool_scale() -> None:
    from picframe.core.models.overlay import PluginLayoutError, validate_plugin_layout

    with pytest.raises(PluginLayoutError, match="scale"):
        validate_plugin_layout({"scale": True})


def test_validate_plugin_layout_rejects_bad_display_mode() -> None:
    from picframe.core.models.overlay import PluginLayoutError, validate_plugin_layout

    with pytest.raises(PluginLayoutError, match="display_mode"):
        validate_plugin_layout({"display_mode": "always"})


def test_validate_plugin_layout_rejects_non_positive_size() -> None:
    from picframe.core.models.overlay import PluginLayoutError, validate_plugin_layout

    with pytest.raises(PluginLayoutError, match="width"):
        validate_plugin_layout({"width": 0})
    with pytest.raises(PluginLayoutError, match="height"):
        validate_plugin_layout({"height": -5})


def test_validate_plugin_layout_rejects_non_integer_size() -> None:
    from picframe.core.models.overlay import PluginLayoutError, validate_plugin_layout

    with pytest.raises(PluginLayoutError, match="width"):
        validate_plugin_layout({"width": 12.5})


def test_validate_plugin_layout_rejects_negative_idle_hide_seconds() -> None:
    from picframe.core.models.overlay import PluginLayoutError, validate_plugin_layout

    with pytest.raises(PluginLayoutError, match="idle_hide_seconds"):
        validate_plugin_layout({"idle_hide_seconds": -1.0})


def test_validate_plugin_layout_accepts_none_idle_hide_seconds() -> None:
    from picframe.core.models.overlay import validate_plugin_layout

    result = validate_plugin_layout({"idle_hide_seconds": None})
    assert result["idle_hide_seconds"] is None


def test_validate_plugin_layout_rejects_non_integer_z_order() -> None:
    from picframe.core.models.overlay import PluginLayoutError, validate_plugin_layout

    with pytest.raises(PluginLayoutError, match="z_order"):
        validate_plugin_layout({"z_order": 1.5})


def test_validate_plugin_layout_rejects_bool_z_order() -> None:
    from picframe.core.models.overlay import PluginLayoutError, validate_plugin_layout

    with pytest.raises(PluginLayoutError, match="z_order"):
        validate_plugin_layout({"z_order": True})


def test_effective_plugin_layout_merges_defaults_with_overrides() -> None:
    from picframe.core.models.overlay import effective_plugin_layout

    descriptor = PluginDescriptor(
        id="weather",
        position="bottom-left",
        size={"w": 320, "h": 180},
        default_display_mode="persistent",
    )
    db_layout = {"position": "top-right", "idle_hide_seconds": 8.0}
    effective = effective_plugin_layout(descriptor, db_layout)
    assert effective == {
        "position": "top-right",
        "width": None,
        "height": None,
        "scale": 1.0,
        "display_mode": "persistent",
        "idle_hide_seconds": 8.0,
        "z_order": 0,
    }


def test_effective_plugin_layout_ignores_non_dict_db_layout() -> None:
    from picframe.core.models.overlay import effective_plugin_layout

    descriptor = PluginDescriptor(id="clock")
    assert effective_plugin_layout(descriptor, None)["position"] == "top-right"
    assert effective_plugin_layout(descriptor, "nope")["position"] == "top-right"  # type: ignore[arg-type]


def test_effective_plugin_layout_fill_mode_applies_width_height() -> None:
    """A plugin without a manifest `size` (fill mode, e.g. meta) starts with
    `scale=None` and `width`/`height=None`; a db override on `width`/`height`
    enlarges the panel (#752)."""
    from picframe.core.models.overlay import effective_plugin_layout

    descriptor = PluginDescriptor(id="meta", position="bottom-right")
    assert effective_plugin_layout(descriptor, None) == {
        "position": "bottom-right",
        "width": None,
        "height": None,
        "scale": None,
        "display_mode": "auto_hide",
        "idle_hide_seconds": None,
        "z_order": 0,
    }
    effective = effective_plugin_layout(
        descriptor, {"width": 600, "height": 400, "display_mode": "persistent"}
    )
    assert effective["width"] == 600
    assert effective["height"] == 400
    assert effective["scale"] is None
    assert effective["display_mode"] == "persistent"


# ---------------------------------------------------------------------------
# Legacy overlay normalization (issue #752 compatibility shim)
# ---------------------------------------------------------------------------


def test_normalize_legacy_overlay_derives_visible_plugins_from_visible_plugin() -> None:
    from picframe.core.models.overlay import normalize_legacy_overlay

    result = normalize_legacy_overlay({"visible_plugin": "clock", "display_mode": "auto_hide"})
    assert result["visible_plugins"] == ["clock"]
    assert result["visible_plugin"] == "clock"
    assert result["display_mode"] == "auto_hide"


def test_normalize_legacy_overlay_null_visible_plugin_yields_empty_list() -> None:
    from picframe.core.models.overlay import normalize_legacy_overlay

    result = normalize_legacy_overlay({"visible_plugin": None})
    assert result["visible_plugins"] == []
    assert result["visible_plugin"] is None


def test_normalize_legacy_overlay_rederives_visible_plugin_from_list() -> None:
    from picframe.core.models.overlay import normalize_legacy_overlay

    result = normalize_legacy_overlay({"visible_plugins": ["clock", "weather"]})
    assert result["visible_plugin"] == "clock"
    assert result["visible_plugins"] == ["clock", "weather"]


def test_normalize_legacy_overlay_keeps_existing_visible_plugins() -> None:
    from picframe.core.models.overlay import normalize_legacy_overlay

    result = normalize_legacy_overlay({"visible_plugins": ["weather"], "visible_plugin": "clock"})
    assert result["visible_plugins"] == ["weather"]
    assert result["visible_plugin"] == "clock"


def test_normalize_legacy_overlay_non_dict_returns_empty() -> None:
    from picframe.core.models.overlay import normalize_legacy_overlay

    assert normalize_legacy_overlay(None) == {}  # type: ignore[arg-type]
    assert normalize_legacy_overlay("nope") == {}  # type: ignore[arg-type]


def test_normalize_legacy_overlay_empty_visible_plugins_rederives_null_plugin() -> None:
    from picframe.core.models.overlay import normalize_legacy_overlay

    result = normalize_legacy_overlay({"visible_plugins": []})
    assert result["visible_plugin"] is None
    assert result["visible_plugins"] == []
