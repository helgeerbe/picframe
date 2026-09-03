"""Tests for the overlay plugin manifest loader."""

import json
from pathlib import Path

from picframe.infrastructure.overlay.plugin_loader import PluginLoader


def _write_plugin(base: Path, plugin_id: str, manifest: dict) -> Path:
    plugin_dir = base / plugin_id
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    return plugin_dir


def test_list_plugins_empty_when_dir_missing(tmp_path: Path) -> None:
    loader = PluginLoader(tmp_path / "does-not-exist")
    assert loader.list_plugins() == []


def test_list_plugins_empty_when_dir_empty(tmp_path: Path) -> None:
    loader = PluginLoader(tmp_path)
    assert loader.list_plugins() == []


def test_list_plugins_skips_files_and_dirs_without_manifest(tmp_path: Path) -> None:
    (tmp_path / "readme.txt").write_text("hi")
    (tmp_path / "no-manifest").mkdir()
    loader = PluginLoader(tmp_path)
    assert loader.list_plugins() == []


def test_list_plugins_loads_manifests_sorted(tmp_path: Path) -> None:
    _write_plugin(
        tmp_path,
        "weather",
        {
            "id": "weather",
            "name": "Weather",
            "description": "Forecast.",
            "icon": "\u2600\ufe0f",
            "trigger": "icon",
            "position": "top-right",
            "size": {"w": 480, "h": 360},
            "requires": ["weather"],
            "config_schema": {
                "api_key": {"type": "string", "required": True},
                "units": {"type": "string", "default": "metric", "enum": ["metric", "imperial"]},
            },
        },
    )
    _write_plugin(tmp_path, "clock", {"id": "clock", "name": "Clock"})

    loader = PluginLoader(tmp_path)
    descriptors = loader.list_plugins()
    assert [d.id for d in descriptors] == ["clock", "weather"]

    weather = descriptors[1]
    assert weather.name == "Weather"
    assert weather.icon == "\u2600\ufe0f"
    assert weather.size == {"w": 480, "h": 360}
    assert weather.requires == ["weather"]
    assert weather.config_schema["api_key"]["required"] is True
    assert weather.directory == str(tmp_path / "weather")


def test_list_plugins_defaults_id_to_directory_name(tmp_path: Path) -> None:
    _write_plugin(tmp_path, "meta", {"name": "Meta"})
    loader = PluginLoader(tmp_path)
    descriptor = loader.list_plugins()[0]
    assert descriptor.id == "meta"
    assert descriptor.name == "Meta"


def test_list_plugins_skips_malformed_manifest(tmp_path: Path) -> None:
    _write_plugin(tmp_path, "good", {"id": "good"})
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "plugin.json").write_text("{not valid json", encoding="utf-8")
    loader = PluginLoader(tmp_path)
    assert [d.id for d in loader.list_plugins()] == ["good"]


def test_list_plugins_skips_non_object_manifest(tmp_path: Path) -> None:
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "plugin.json").write_text("[]", encoding="utf-8")
    loader = PluginLoader(tmp_path)
    assert loader.list_plugins() == []


def test_list_plugins_expands_user_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    plugins = tmp_path / "overlay-plugins"
    _write_plugin(plugins, "clock", {"id": "clock"})
    loader = PluginLoader("~/overlay-plugins")
    assert [d.id for d in loader.list_plugins()] == ["clock"]
