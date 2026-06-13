"""Settings UI coverage guards for compatibility-only legacy fields."""

from pathlib import Path


def test_compatibility_only_settings_are_not_live_controls() -> None:
    settings_view = Path("frontend/src/views/SettingsView.vue").read_text()
    hidden_bindings = [
        "localConfig.viewer.display_power",
        "localConfig.viewer.menu_text_sz",
        "localConfig.viewer.menu_autohide_tm",
        "localConfig.model.update_interval",
        "localConfig.model.image_attr",
        "localConfig.http.auth",
        "localConfig.http.username",
        "localConfig.http.password",
        "localConfig.http.use_ssl",
        "localConfig.http.keyfile",
        "localConfig.http.certfile",
        "localConfig.peripherals",
    ]

    for binding in hidden_bindings:
        assert binding not in settings_view
