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
