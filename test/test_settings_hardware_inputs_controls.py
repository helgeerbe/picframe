from pathlib import Path


def test_hardware_input_command_options_exclude_unsupported_wake_sleep() -> None:
    editor = Path("frontend/src/components/HardwareInputsEditor.vue").read_text()

    assert "'DISPLAY_ON'" in editor
    assert "'DISPLAY_OFF'" in editor
    assert "'SLEEP'" not in editor
    assert "'WAKE'" not in editor
