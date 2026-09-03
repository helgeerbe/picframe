"""Tests for the built-in overlay plugins shipped with picframe (#739, Phase 3).

Validates that the shipped plugin manifests load through the ``PluginLoader``,
declare the expected ``config_schema`` fields, and that their default values
and user payloads round-trip through ``validate_plugin_config``.
"""

from pathlib import Path

import picframe
from picframe.core.models.overlay import plugin_config_defaults, validate_plugin_config
from picframe.infrastructure.overlay.plugin_loader import PluginLoader

# Path to the built-in plugins shipped as package data.
_BUILTIN_PLUGINS_DIR = Path(picframe.__file__).parent / "overlay_plugins"


def test_builtin_plugins_directory_exists() -> None:
    assert _BUILTIN_PLUGINS_DIR.is_dir(), "Built-in overlay_plugins package dir must exist"


def test_builtin_plugins_load_through_loader() -> None:
    loader = PluginLoader(_BUILTIN_PLUGINS_DIR)
    descriptors = loader.list_plugins()
    ids = {d.id for d in descriptors}
    assert {"clock", "weather", "meta"}.issubset(ids), ids


def test_each_builtin_plugin_has_html_entry() -> None:
    loader = PluginLoader(_BUILTIN_PLUGINS_DIR)
    for descriptor in loader.list_plugins():
        entry = Path(descriptor.directory) / descriptor.entry
        assert entry.is_file(), f"{descriptor.id} entry {entry} missing"


def test_clock_plugin_schema() -> None:
    loader = PluginLoader(_BUILTIN_PLUGINS_DIR)
    clock = next(d for d in loader.list_plugins() if d.id == "clock")
    assert clock.icon
    assert clock.config_schema["style"]["enum"] == ["digital", "analog"]
    assert clock.config_schema["clock_format"]["enum"] == ["12h", "24h"]
    defaults = plugin_config_defaults(clock.config_schema)
    assert defaults == {
        "style": "digital",
        "clock_format": "24h",
        "show_seconds": False,
        "show_date": True,
    }
    # A user payload overriding only some fields merges with defaults.
    result = validate_plugin_config(clock.config_schema, {"style": "analog"})
    assert result["style"] == "analog"
    assert result["clock_format"] == "24h"
    assert result["show_seconds"] is False


def test_weather_plugin_schema_requires_api_key_and_coords() -> None:
    loader = PluginLoader(_BUILTIN_PLUGINS_DIR)
    weather = next(d for d in loader.list_plugins() if d.id == "weather")
    assert weather.config_schema["api_key"]["required"] is True
    assert weather.config_schema["lat"]["required"] is True
    assert weather.config_schema["lon"]["required"] is True
    assert weather.config_schema["units"]["enum"] == ["metric", "imperial"]
    defaults = plugin_config_defaults(weather.config_schema)
    assert defaults == {"units": "metric", "language": "en", "refresh_seconds": 600}
    # Valid full payload validates.
    result = validate_plugin_config(
        weather.config_schema,
        {"api_key": "secret", "lat": 52.5, "lon": 13.4, "units": "imperial"},
    )
    assert result["units"] == "imperial"
    assert result["api_key"] == "secret"
    assert result["language"] == "en"
    # Missing required field is rejected.
    import pytest

    with pytest.raises(Exception, match="required"):
        validate_plugin_config(weather.config_schema, {"api_key": "x"})


def test_meta_plugin_schema() -> None:
    loader = PluginLoader(_BUILTIN_PLUGINS_DIR)
    meta = next(d for d in loader.list_plugins() if d.id == "meta")
    defaults = plugin_config_defaults(meta.config_schema)
    assert defaults == {
        "show_map": True,
        "map_zoom": 13,
        "show_exif": True,
        "date_format": "YYYY-MM-DD HH:mm",
    }
    result = validate_plugin_config(meta.config_schema, {"map_zoom": 16, "show_map": False})
    assert result["map_zoom"] == 16
    assert result["show_map"] is False
    assert result["show_exif"] is True
