"""Source guards for Settings clock hour-mode controls."""

from pathlib import Path


def test_settings_clock_hour_mode_presets_and_custom_path() -> None:
    settings_view = Path("frontend/src/views/SettingsView.vue").read_text()

    assert "const CLOCK_FORMAT_24 = '%H:%M'" in settings_view
    assert "const CLOCK_FORMAT_12 = '%-I:%M %p'" in settings_view
    assert "type ClockFormatMode = '24' | '12' | 'custom'" in settings_view
    assert "localConfig.value.viewer.clock_format = CLOCK_FORMAT_24" in settings_view
    assert "localConfig.value.viewer.clock_format = CLOCK_FORMAT_12" in settings_view
    assert "clockFormatModeOverride.value = 'custom'" in settings_view
    assert 'v-if="clockFormatMode === \'custom\'"' in settings_view
    assert "v-model=\"localConfig.viewer.clock_format\"" in settings_view


def test_settings_clock_hour_mode_is_not_locale_driven() -> None:
    settings_view = Path("frontend/src/views/SettingsView.vue").read_text()
    clock_section = settings_view[
        settings_view.index("const CLOCK_FORMAT_24"):
        settings_view.index("function normalizeAuthScope")
    ]

    assert "model.locale" not in clock_section
