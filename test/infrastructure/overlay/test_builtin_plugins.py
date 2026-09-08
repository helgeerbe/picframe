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
    assert {"clock", "weather", "meta", "text"}.issubset(ids), ids


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
        "custom_format": "",
        "opacity": 1.0,
        "extra_source": "off",
        "extra_text": "",
    }
    # A user payload overriding only some fields merges with defaults.
    result = validate_plugin_config(clock.config_schema, {"style": "analog"})
    assert result["style"] == "analog"
    assert result["clock_format"] == "24h"
    assert result["show_seconds"] is False


def test_clock_plugin_schema_extra_source_enum_and_opacity() -> None:
    """#761: the clock plugin exposes the legacy-parity extra-text source enum,
    a custom strftime override, and a whole-clock opacity field. Guards the
    shipped ``plugin.json`` so a regression that drops them is caught."""
    loader = PluginLoader(_BUILTIN_PLUGINS_DIR)
    clock = next(d for d in loader.list_plugins() if d.id == "clock")
    assert clock.config_schema["extra_source"]["enum"] == ["off", "text", "file"]
    assert clock.config_schema["extra_source"]["default"] == "off"
    assert clock.config_schema["custom_format"]["type"] == "string"
    assert clock.config_schema["custom_format"]["default"] == ""
    assert clock.config_schema["opacity"]["type"] == "number"
    assert clock.config_schema["opacity"]["default"] == 1.0
    assert clock.config_schema["extra_text"]["type"] == "string"
    # Valid overrides round-trip through validation.
    result = validate_plugin_config(
        clock.config_schema,
        {
            "extra_source": "file",
            "custom_format": "%-I:%M %p",
            "opacity": 0.5,
            "extra_text": "21.0C",
        },
    )
    assert result["extra_source"] == "file"
    assert result["custom_format"] == "%-I:%M %p"
    assert result["opacity"] == 0.5
    assert result["extra_text"] == "21.0C"
    # An invalid enum value is rejected.
    import pytest

    with pytest.raises(Exception, match="one of"):
        validate_plugin_config(clock.config_schema, {"extra_source": "clock_txt"})


def test_clock_plugin_html_renders_extra_text_elements() -> None:
    """#761: the clock ``index.html`` ships an extra-text element for both the
    digital and analog styles, and the JS reads ``cfg.extra_source`` /
    ``cfg.extra_text`` plus a ``picframe:data`` push for the file source."""
    loader = PluginLoader(_BUILTIN_PLUGINS_DIR)
    clock = next(d for d in loader.list_plugins() if d.id == "clock")
    html = (Path(clock.directory) / clock.entry).read_text(encoding="utf-8")
    assert 'id="extra"' in html, "digital clock must include an extra-text element (#761)"
    assert 'id="analog-extra"' in html, "analog clock must include an extra-text element (#761)"
    assert "cfg.extra_source" in html, "clock must branch on cfg.extra_source (#761)"
    assert "cfg.extra_text" in html, "clock must read cfg.extra_text (#761)"
    # The file source is fed by a picframe:data postMessage with key extra_text.
    assert '"picframe:data"' in html, "clock must listen for picframe:data (#761)"
    assert 'data.key === "extra_text"' in html, "clock must filter picframe:data by key (#761)"


def test_clock_plugin_html_custom_format_overrides_digital() -> None:
    """#761: a non-empty ``custom_format`` (strftime) overrides the 12h/24h +
    seconds toggles for the digital time line. Guards the shipped JS."""
    loader = PluginLoader(_BUILTIN_PLUGINS_DIR)
    clock = next(d for d in loader.list_plugins() if d.id == "clock")
    html = (Path(clock.directory) / clock.entry).read_text(encoding="utf-8")
    assert "cfg.custom_format" in html, "clock must branch on cfg.custom_format (#761)"
    assert "function strftime(" in html, "clock must ship a strftime helper (#761)"
    # The glibc '-' non-padding modifier (legacy default '%-I:%M') must be honored.
    assert '"-"' in html, "strftime must support the '-' non-padding modifier (#761)"


def test_clock_plugin_html_opacity_css_var() -> None:
    """#761: clock opacity is applied via a ``--pf-opacity`` CSS variable on both
    styles. Guards the shipped CSS/JS against the regression of hardcoding full
    opacity."""
    loader = PluginLoader(_BUILTIN_PLUGINS_DIR)
    clock = next(d for d in loader.list_plugins() if d.id == "clock")
    html = (Path(clock.directory) / clock.entry).read_text(encoding="utf-8")
    assert "--pf-opacity" in html, "clock must use the --pf-opacity CSS var (#761)"
    assert "setOpacity" in html, "clock must expose an opacity setter (#761)"


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


def test_text_plugin_schema_and_trigger() -> None:
    """The text plugin (#757) reproduces the legacy pi3d text overlay fields and
    is dock-activatable + media-change-triggered with auto_hide as the default."""
    loader = PluginLoader(_BUILTIN_PLUGINS_DIR)
    text = next(d for d in loader.list_plugins() if d.id == "text")
    assert text.trigger == ["icon", "media_change"]
    assert text.default_display_mode == "auto_hide"
    assert text.size == {"w": 1280, "h": 220}
    assert text.config_schema["justify"]["enum"] == ["L", "C", "R"]
    defaults = plugin_config_defaults(text.config_schema)
    assert defaults == {
        "format": "title caption name date folder location",
        "date_format": "%b %d, %Y",
        "font_size": 40,
        "justify": "L",
        "opacity": 1.0,
        "background_height": 0.25,
    }
    result = validate_plugin_config(
        text.config_schema, {"justify": "R", "font_size": 56, "format": "title date"}
    )
    assert result["justify"] == "R"
    assert result["font_size"] == 56
    assert result["format"] == "title date"
    assert result["date_format"] == "%b %d, %Y"


def test_each_builtin_plugin_ships_icon_svg() -> None:
    """Built-in plugins ship a single-color icon.svg so dock icons render
    without an emoji font (font-independent, theme-aware via currentColor)."""
    loader = PluginLoader(_BUILTIN_PLUGINS_DIR)
    for descriptor in loader.list_plugins():
        svg_path = Path(descriptor.directory) / "icon.svg"
        assert svg_path.is_file(), f"{descriptor.id} missing icon.svg"
        markup = descriptor.icon_svg
        assert markup.startswith("<svg"), f"{descriptor.id} icon_svg not an <svg> root"
        assert "currentColor" in markup, (
            f"{descriptor.id} icon.svg must use currentColor to inherit dock color"
        )


def test_text_plugin_background_grows_with_wrapped_text() -> None:
    """Regression test for #757: the text overlay background must grow to cover
    the full rendered caption height (multi-line wrap), not stay fixed at one
    line. The plugin has no browser/jsdom harness, so this is a string-presence
    check on the shipped ``index.html`` that guards against accidental removal
    of the dynamic ``offsetHeight``-driven sizing."""
    loader = PluginLoader(_BUILTIN_PLUGINS_DIR)
    text = next(d for d in loader.list_plugins() if d.id == "text")
    html = (Path(text.directory) / text.entry).read_text(encoding="utf-8")

    # The dynamic band must be sized from the measured caption height...
    assert "el.offsetHeight" in html, "text plugin must measure caption offsetHeight (#757)"
    # ...combined with the minimum (background_height * panel height)...
    assert "bh * panelH" in html, (
        "text plugin must compute a minimum band from background_height * panel height (#757)"
    )
    # ...taking the max so multi-line captions keep their background.
    assert "Math.max(minBand" in html, (
        "text plugin must max(min band, caption height) so the band never"
        " clips wrapped lines (#757)"
    )
    # And the band must be applied as an absolute px size, not a fixed
    # percentage of the panel (the pre-#757 one-line bug).
    assert 'backgroundSize = "100% " + bandPx + "px"' in html, (
        "text plugin must set backgroundSize in px from bandPx (#757)"
    )
    assert '* 100).toFixed(1) + "%"' not in html, (
        "text plugin must not keep the old fixed-percentage backgroundSize (#757)"
    )


def test_clock_plugin_analog_has_date_element() -> None:
    """Regression test for #760: the analog clock must render the date when
    ``show_date`` is true. The pre-fix analog mode only updated the clock hands
    and the date element lived inside the (hidden) digital div, so the date
    was silently dropped. This guards against the analog-date element going
    missing from the shipped ``index.html``."""
    loader = PluginLoader(_BUILTIN_PLUGINS_DIR)
    clock = next(d for d in loader.list_plugins() if d.id == "clock")
    html = (Path(clock.directory) / clock.entry).read_text(encoding="utf-8")
    assert 'id="analog-date"' in html, "clock analog mode must include a date element (#760)"


def test_clock_plugin_analog_draw_updates_date() -> None:
    """Regression test for #760: ``drawAnalog`` must honor ``cfg.show_date`` by
    showing/hiding the analog date element. String-presence check on the
    shipped ``index.html`` guards against the date logic being dropped."""
    loader = PluginLoader(_BUILTIN_PLUGINS_DIR)
    clock = next(d for d in loader.list_plugins() if d.id == "clock")
    html = (Path(clock.directory) / clock.entry).read_text(encoding="utf-8")
    assert '"analog-date"' in html, "drawAnalog must reference the analog date element (#760)"
    assert "cfg.show_date" in html, "drawAnalog must check cfg.show_date (#760)"
    draw_analog_idx = html.find("function drawAnalog(now)")
    assert draw_analog_idx != -1, "clock plugin must define drawAnalog (#760)"
    analog_date_idx = html.find('"analog-date"', draw_analog_idx)
    assert analog_date_idx != -1, "drawAnalog must update the analog date (#760)"


def test_clock_plugin_analog_uses_flex_wrapper_not_fixed_size() -> None:
    """Regression test for #760: the analog clock face must not be sized with a
    fixed fraction of the full panel dimensions (``min(calc(var(--w)*0.9),
    calc(var(--h)*0.9))``), which ignored the per-edge content_offset and could
    clip the bottom of the face. The fix wraps the SVG in a column flex layout
    that fills the content area and lets the SVG's ``preserveAspectRatio``
    letterbox the face. String-presence/absence checks guard the shipped
    ``index.html``."""
    loader = PluginLoader(_BUILTIN_PLUGINS_DIR)
    clock = next(d for d in loader.list_plugins() if d.id == "clock")
    html = (Path(clock.directory) / clock.entry).read_text(encoding="utf-8")
    assert "pf-analog-wrap" in html, "analog must use a flex wrapper (#760)"
    assert "pf-analog-svg-wrap" in html, "analog SVG must live in a flex wrapper (#760)"
    assert "svg.pf-analog { width: 100%; height: 100%; }" in html, (
        "analog SVG must fill its wrapper rather than use a fixed size (#760)"
    )
    assert "min(calc(var(--w) * 0.9), calc(var(--h) * 0.9))" not in html, (
        "analog must not keep the old fixed-size SVG sizing that clipped the face (#760)"
    )
