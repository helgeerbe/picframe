import pytest

from picframe.core.models.hardware_input import (
    HardwareInputConfigError,
    derive_hardware_input_runtime_config,
    normalize_hardware_inputs_config,
)


def test_normalize_valid_button_and_pir_config() -> None:
    config = normalize_hardware_inputs_config(
        {
            "enabled": True,
            "inputs": {
                "next_button": {
                    "label": "Next",
                    "type": "button",
                    "pin": "17",
                    "bounce_time": "0.2",
                    "actions": {"pressed": "next"},
                },
                "motion": {
                    "type": "pir",
                    "pin": 27,
                    "no_motion_delay_seconds": "900",
                    "actions": {
                        "motion_detected": "DISPLAY_ON",
                        "no_motion": "DISPLAY_OFF",
                    },
                },
            },
        }
    )

    assert config["enabled"] is True
    assert config["inputs"]["next_button"]["pin"] == 17
    assert config["inputs"]["next_button"]["bounce_time"] == 0.2
    assert config["inputs"]["next_button"]["actions"] == {"pressed": "NEXT"}
    assert config["inputs"]["motion"]["label"] == "motion"
    assert config["inputs"]["motion"]["no_motion_delay_seconds"] == 900.0


def test_duplicate_pins_are_rejected() -> None:
    with pytest.raises(HardwareInputConfigError, match="duplicate pin"):
        normalize_hardware_inputs_config(
            {
                "inputs": {
                    "a": {"type": "button", "pin": 17, "actions": {"pressed": "NEXT"}},
                    "b": {"type": "pir", "pin": 17, "actions": {"motion_detected": "DISPLAY_ON"}},
                },
            }
        )


@pytest.mark.parametrize(
    ("settings", "match"),
    [
        ({"type": "switch", "pin": 17, "actions": {"pressed": "NEXT"}}, "unsupported type"),
        ({"type": "button", "pin": 17, "actions": {"motion_detected": "NEXT"}}, "invalid"),
        ({"type": "button", "pin": 17, "actions": {"pressed": "SET_BRIGHTNESS"}}, "unsupported"),
        ({"type": "button", "pin": 17, "actions": {"pressed": "SLEEP"}}, "unsupported"),
        ({"type": "pir", "pin": 17, "actions": {"motion_detected": "WAKE"}}, "unsupported"),
        ({"type": "button", "pin": 40, "actions": {"pressed": "NEXT"}}, "BCM"),
        ({"type": "button", "pin": 17}, "at least one action"),
        (
            {
                "type": "button",
                "pin": 17,
                "no_motion_delay_seconds": 30,
                "actions": {"pressed": "NEXT"},
            },
            "only valid for PIR",
        ),
        (
            {
                "type": "pir",
                "pin": 17,
                "no_motion_delay_seconds": -1,
                "actions": {"motion_detected": "DISPLAY_ON"},
            },
            "must not be negative",
        ),
        (
            {
                "type": "pir",
                "pin": 17,
                "no_motion_delay_seconds": "later",
                "actions": {"motion_detected": "DISPLAY_ON"},
            },
            "must be numeric",
        ),
    ],
)
def test_invalid_input_settings_are_rejected(settings: dict[str, object], match: str) -> None:
    with pytest.raises(HardwareInputConfigError, match=match):
        normalize_hardware_inputs_config({"inputs": {"bad": settings}})


def test_derive_runtime_config_splits_adapter_and_command_mapping() -> None:
    enabled, adapter_config, command_mapping, no_motion_delays = (
        derive_hardware_input_runtime_config(
            {
                "enabled": True,
                "inputs": {
                    "next_button": {
                        "type": "button",
                        "pin": 17,
                        "bounce_time": 0.2,
                        "actions": {"pressed": "NEXT"},
                    }
                },
            }
        )
    )

    assert enabled is True
    assert adapter_config == {"next_button": {"type": "button", "pin": 17, "bounce_time": 0.2}}
    assert command_mapping == {"next_button": {"pressed": "NEXT"}}
    assert no_motion_delays == {}


def test_derive_runtime_config_returns_pir_no_motion_delay() -> None:
    enabled, adapter_config, command_mapping, no_motion_delays = (
        derive_hardware_input_runtime_config(
            {
                "enabled": True,
                "inputs": {
                    "motion": {
                        "type": "pir",
                        "pin": 27,
                        "no_motion_delay_seconds": 900,
                        "actions": {
                            "motion_detected": "DISPLAY_ON",
                            "no_motion": "DISPLAY_OFF",
                        },
                    }
                },
            }
        )
    )

    assert enabled is True
    assert adapter_config == {"motion": {"type": "pir", "pin": 27}}
    assert command_mapping == {
        "motion": {"motion_detected": "DISPLAY_ON", "no_motion": "DISPLAY_OFF"}
    }
    assert no_motion_delays == {"motion": 900.0}
