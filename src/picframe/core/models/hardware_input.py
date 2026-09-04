"""Validation and runtime mapping helpers for hardware input configuration."""

from __future__ import annotations

import re
from typing import Any


class HardwareInputConfigError(ValueError):
    """Raised when hardware input configuration is invalid."""


HARDWARE_INPUT_ALLOWED_COMMANDS = {
    "NEXT",
    "PREV",
    "PAUSE",
    "PLAY",
    "DISPLAY_ON",
    "DISPLAY_OFF",
    "DISPLAY_TOGGLE",
    "TOGGLE_TEXT",
    "REFRESH_TEXT",
    "REBOOT_HOST",
    "SHUTDOWN_HOST",
    "STOP",
}

HARDWARE_INPUT_ACTIONS_BY_TYPE = {
    "button": {"pressed", "released"},
    "pir": {"motion_detected", "no_motion"},
}

DEFAULT_HARDWARE_INPUTS_CONFIG: dict[str, Any] = {
    "enabled": False,
    "inputs": {},
}

_INPUT_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _parse_enabled(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "on"}
    return bool(value)


def _validate_input_id(input_id: str) -> None:
    if not input_id:
        raise HardwareInputConfigError("Hardware input id must not be empty")
    if not _INPUT_ID_RE.match(input_id):
        raise HardwareInputConfigError(
            f"Hardware input id '{input_id}' may only contain letters, numbers, '_' and '-'"
        )


def _parse_non_negative_float(value: Any, label: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise HardwareInputConfigError(f"{label} must be numeric") from exc
    if parsed < 0:
        raise HardwareInputConfigError(f"{label} must not be negative")
    return parsed


def normalize_hardware_inputs_config(config: Any | None) -> dict[str, Any]:
    """Return a normalized hardware input config or raise on invalid values."""
    if config is None:
        return dict(DEFAULT_HARDWARE_INPUTS_CONFIG)
    if not isinstance(config, dict):
        raise HardwareInputConfigError("hardware_inputs must be an object")

    enabled = _parse_enabled(config.get("enabled", False))
    raw_inputs = config.get("inputs", {})
    if raw_inputs is None:
        raw_inputs = {}
    if not isinstance(raw_inputs, dict):
        raise HardwareInputConfigError("hardware_inputs.inputs must be an object")

    normalized_inputs: dict[str, dict[str, Any]] = {}
    used_pins: dict[int, str] = {}

    for input_id, raw_settings in raw_inputs.items():
        input_id = str(input_id).strip()
        _validate_input_id(input_id)
        if not isinstance(raw_settings, dict):
            raise HardwareInputConfigError(f"Hardware input '{input_id}' must be an object")

        device_type = str(raw_settings.get("type", "")).strip().lower()
        if device_type not in HARDWARE_INPUT_ACTIONS_BY_TYPE:
            raise HardwareInputConfigError(
                f"Hardware input '{input_id}' has unsupported type '{device_type}'"
            )

        raw_pin = raw_settings.get("pin")
        if isinstance(raw_pin, bool) or raw_pin is None:
            raise HardwareInputConfigError(f"Hardware input '{input_id}' needs a BCM pin")
        try:
            pin = int(raw_pin)
        except (TypeError, ValueError) as exc:
            raise HardwareInputConfigError(
                f"Hardware input '{input_id}' pin must be an integer"
            ) from exc
        if pin < 0 or pin > 27:
            raise HardwareInputConfigError(
                f"Hardware input '{input_id}' pin must be a BCM GPIO number from 0 to 27"
            )
        if pin in used_pins:
            raise HardwareInputConfigError(
                f"Hardware input '{input_id}' uses duplicate pin {pin} "
                f"already assigned to '{used_pins[pin]}'"
            )
        used_pins[pin] = input_id

        raw_actions = raw_settings.get("actions")
        if not isinstance(raw_actions, dict) or not raw_actions:
            raise HardwareInputConfigError(
                f"Hardware input '{input_id}' needs at least one action mapping"
            )

        allowed_actions = HARDWARE_INPUT_ACTIONS_BY_TYPE[device_type]
        normalized_actions: dict[str, str] = {}
        for action, raw_command in raw_actions.items():
            action = str(action).strip()
            if action not in allowed_actions:
                raise HardwareInputConfigError(
                    f"Hardware input '{input_id}' action '{action}' is invalid for {device_type}"
                )

            command_name = str(raw_command).strip().upper()
            if command_name not in HARDWARE_INPUT_ALLOWED_COMMANDS:
                raise HardwareInputConfigError(
                    f"Hardware input '{input_id}' action '{action}' uses unsupported "
                    f"command '{raw_command}'"
                )
            normalized_actions[action] = command_name

        label = str(raw_settings.get("label", input_id)).strip() or input_id
        normalized: dict[str, Any] = {
            "label": label,
            "type": device_type,
            "pin": pin,
            "actions": normalized_actions,
        }
        if device_type == "button":
            if "no_motion_delay_seconds" in raw_settings:
                raise HardwareInputConfigError(
                    f"Hardware input '{input_id}' no_motion_delay_seconds is only valid for PIR"
                )
            bounce_time = _parse_non_negative_float(
                raw_settings.get("bounce_time", 0.1),
                f"Hardware input '{input_id}' bounce_time",
            )
            normalized["bounce_time"] = bounce_time
        else:
            normalized["no_motion_delay_seconds"] = _parse_non_negative_float(
                raw_settings.get("no_motion_delay_seconds", 0.0),
                f"Hardware input '{input_id}' no_motion_delay_seconds",
            )

        normalized_inputs[input_id] = normalized

    return {
        "enabled": enabled,
        "inputs": normalized_inputs,
    }


def hardware_inputs_from_flat_config(flat_config: dict[str, Any]) -> dict[str, Any]:
    """Extract a nested hardware_inputs section from flat config repository keys."""
    section: dict[str, Any] = {}

    direct_value = flat_config.get("hardware_inputs")
    if isinstance(direct_value, dict):
        section.update(direct_value)

    for flat_key, value in flat_config.items():
        if not flat_key.startswith("hardware_inputs."):
            continue
        parts = flat_key.split(".")[1:]
        current = section
        for part in parts[:-1]:
            existing = current.get(part)
            if not isinstance(existing, dict):
                existing = {}
                current[part] = existing
            current = existing
        current[parts[-1]] = value

    return normalize_hardware_inputs_config(section or None)


def derive_hardware_input_runtime_config(
    config: Any | None,
) -> tuple[
    bool,
    dict[str, dict[str, Any]],
    dict[str, dict[str, str]],
    dict[str, float],
]:
    """Convert persisted config into adapter config and command mappings."""
    normalized = normalize_hardware_inputs_config(config)
    adapter_config: dict[str, dict[str, Any]] = {}
    command_mapping: dict[str, dict[str, str]] = {}
    no_motion_delays: dict[str, float] = {}

    for input_id, settings in normalized["inputs"].items():
        adapter_settings = {
            "type": settings["type"],
            "pin": settings["pin"],
        }
        if settings["type"] == "button":
            adapter_settings["bounce_time"] = settings.get("bounce_time", 0.1)
        elif settings.get("no_motion_delay_seconds", 0.0) > 0:
            no_motion_delays[input_id] = settings["no_motion_delay_seconds"]
        adapter_config[input_id] = adapter_settings
        command_mapping[input_id] = dict(settings["actions"])

    return bool(normalized["enabled"]), adapter_config, command_mapping, no_motion_delays
