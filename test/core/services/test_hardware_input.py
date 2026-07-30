"""
Tests for the HardwareInputService.
"""

from unittest.mock import MagicMock

from picframe.core.events.dto import Command, CommandEvent, State, StateEvent
from picframe.core.services.hardware_input import HardwareInputService
from picframe.infrastructure.os.mock_adapters import MockHardwareInput


class FakeTimer:
    instances: list["FakeTimer"] = []

    def __init__(self, delay: float, callback, args=()) -> None:
        self.delay = delay
        self.callback = callback
        self.args = args
        self.started = False
        self.cancelled = False
        FakeTimer.instances.append(self)

    def start(self) -> None:
        self.started = True

    def cancel(self) -> None:
        self.cancelled = True

    def fire(self) -> None:
        if not self.cancelled:
            self.callback(*self.args)


def test_hardware_input_service_translates_events() -> None:
    """Test that the service correctly translates hardware events to CommandEvents."""
    mock_event_bus = MagicMock()
    mock_adapter = MockHardwareInput()

    input_mapping = {
        "next_button": {"pressed": "NEXT"},
        "motion_sensor": {"motion_detected": "DISPLAY_ON", "no_motion": "DISPLAY_OFF"},
    }

    service = HardwareInputService(mock_event_bus, mock_adapter, input_mapping)
    service.start()

    # Simulate button press
    mock_adapter.simulate_event("next_button", "pressed")
    mock_event_bus.publish.assert_called_with(CommandEvent(command=Command.NEXT))

    # Simulate motion detected
    mock_adapter.simulate_event("motion_sensor", "motion_detected")
    mock_event_bus.publish.assert_called_with(CommandEvent(command=Command.DISPLAY_ON))

    # Simulate no motion
    mock_adapter.simulate_event("motion_sensor", "no_motion")
    mock_event_bus.publish.assert_called_with(CommandEvent(command=Command.DISPLAY_OFF))

    service.stop()


def test_hardware_input_service_ignores_unmapped_events() -> None:
    """Test that the service ignores events that are not in the mapping."""
    mock_event_bus = MagicMock()
    mock_adapter = MockHardwareInput()

    input_mapping = {
        "next_button": {"pressed": "NEXT"},
    }

    service = HardwareInputService(mock_event_bus, mock_adapter, input_mapping)
    service.start()

    # Simulate unmapped input ID
    mock_adapter.simulate_event("unknown_button", "pressed")
    mock_event_bus.publish.assert_not_called()

    # Simulate unmapped action for a known input ID
    mock_adapter.simulate_event("next_button", "released")
    mock_event_bus.publish.assert_not_called()

    service.stop()


def test_hardware_input_service_handles_invalid_commands() -> None:
    """Test that the service handles invalid command names in the mapping gracefully."""
    mock_event_bus = MagicMock()
    mock_adapter = MockHardwareInput()

    input_mapping = {
        "bad_button": {"pressed": "INVALID_COMMAND_NAME"},
    }

    service = HardwareInputService(mock_event_bus, mock_adapter, input_mapping)
    service.start()

    # Simulate event that maps to an invalid command
    mock_adapter.simulate_event("bad_button", "pressed")
    mock_event_bus.publish.assert_not_called()

    service.stop()


def test_hardware_input_service_loads_enabled_config_from_repository() -> None:
    mock_event_bus = MagicMock()
    mock_repo = MagicMock()
    mock_repo.get_all_app_config.return_value = {
        "hardware_inputs.enabled": True,
        "hardware_inputs.inputs.next_button.type": "button",
        "hardware_inputs.inputs.next_button.pin": 17,
        "hardware_inputs.inputs.next_button.actions.pressed": "NEXT",
    }
    mock_adapter = MockHardwareInput()

    service = HardwareInputService(
        event_bus=mock_event_bus,
        hardware_input_adapter=mock_adapter,
        config_repository=mock_repo,
    )
    service.start()

    assert mock_adapter.config == {"next_button": {"type": "button", "pin": 17, "bounce_time": 0.1}}
    mock_adapter.simulate_event("next_button", "pressed")
    mock_event_bus.publish.assert_called_with(CommandEvent(command=Command.NEXT))

    service.stop()


def test_hardware_input_service_delays_pir_no_motion_command(monkeypatch) -> None:
    FakeTimer.instances.clear()
    monkeypatch.setattr("picframe.core.services.hardware_input.threading.Timer", FakeTimer)
    mock_event_bus = MagicMock()
    mock_repo = MagicMock()
    mock_repo.get_all_app_config.return_value = {
        "hardware_inputs.enabled": True,
        "hardware_inputs.inputs.motion.type": "pir",
        "hardware_inputs.inputs.motion.pin": 27,
        "hardware_inputs.inputs.motion.no_motion_delay_seconds": 900,
        "hardware_inputs.inputs.motion.actions.motion_detected": "DISPLAY_ON",
        "hardware_inputs.inputs.motion.actions.no_motion": "DISPLAY_OFF",
    }
    mock_adapter = MockHardwareInput()

    service = HardwareInputService(
        event_bus=mock_event_bus,
        hardware_input_adapter=mock_adapter,
        config_repository=mock_repo,
    )
    service.start()

    startup_timer = FakeTimer.instances[0]
    mock_adapter.simulate_event("motion", "no_motion")

    mock_event_bus.publish.assert_not_called()
    assert len(FakeTimer.instances) == 2
    assert startup_timer.cancelled is True
    no_motion_timer = FakeTimer.instances[1]
    assert no_motion_timer.delay == 900
    assert no_motion_timer.started is True

    no_motion_timer.fire()
    mock_event_bus.publish.assert_called_once_with(CommandEvent(command=Command.DISPLAY_OFF))

    service.stop()


def test_hardware_input_service_schedules_initial_pir_no_motion_timer(monkeypatch) -> None:
    FakeTimer.instances.clear()
    monkeypatch.setattr("picframe.core.services.hardware_input.threading.Timer", FakeTimer)
    mock_event_bus = MagicMock()
    mock_repo = MagicMock()
    mock_repo.get_all_app_config.return_value = {
        "hardware_inputs.enabled": True,
        "hardware_inputs.inputs.motion.type": "pir",
        "hardware_inputs.inputs.motion.pin": 27,
        "hardware_inputs.inputs.motion.no_motion_delay_seconds": 60,
        "hardware_inputs.inputs.motion.actions.motion_detected": "DISPLAY_ON",
        "hardware_inputs.inputs.motion.actions.no_motion": "DISPLAY_OFF",
    }
    mock_adapter = MockHardwareInput()

    service = HardwareInputService(
        event_bus=mock_event_bus,
        hardware_input_adapter=mock_adapter,
        config_repository=mock_repo,
    )
    service.start()

    mock_event_bus.publish.assert_not_called()
    assert len(FakeTimer.instances) == 1
    assert FakeTimer.instances[0].delay == 60
    assert FakeTimer.instances[0].started is True

    FakeTimer.instances[0].fire()
    mock_event_bus.publish.assert_called_once_with(CommandEvent(command=Command.DISPLAY_OFF))

    service.stop()


def test_hardware_input_service_motion_cancels_pending_no_motion(monkeypatch) -> None:
    FakeTimer.instances.clear()
    monkeypatch.setattr("picframe.core.services.hardware_input.threading.Timer", FakeTimer)
    mock_event_bus = MagicMock()
    mock_repo = MagicMock()
    mock_repo.get_all_app_config.return_value = {
        "hardware_inputs.enabled": True,
        "hardware_inputs.inputs.motion.type": "pir",
        "hardware_inputs.inputs.motion.pin": 27,
        "hardware_inputs.inputs.motion.no_motion_delay_seconds": 30,
        "hardware_inputs.inputs.motion.actions.motion_detected": "DISPLAY_ON",
        "hardware_inputs.inputs.motion.actions.no_motion": "DISPLAY_OFF",
    }
    mock_adapter = MockHardwareInput()

    service = HardwareInputService(
        event_bus=mock_event_bus,
        hardware_input_adapter=mock_adapter,
        config_repository=mock_repo,
    )
    service.start()

    mock_adapter.simulate_event("motion", "no_motion")
    mock_adapter.simulate_event("motion", "motion_detected")

    assert FakeTimer.instances[0].cancelled is True
    mock_event_bus.publish.assert_called_once_with(CommandEvent(command=Command.DISPLAY_ON))
    FakeTimer.instances[0].fire()
    mock_event_bus.publish.assert_called_once_with(CommandEvent(command=Command.DISPLAY_ON))

    service.stop()


def test_hardware_input_service_stop_cancels_pending_no_motion(monkeypatch) -> None:
    FakeTimer.instances.clear()
    monkeypatch.setattr("picframe.core.services.hardware_input.threading.Timer", FakeTimer)
    mock_event_bus = MagicMock()
    mock_repo = MagicMock()
    mock_repo.get_all_app_config.return_value = {
        "hardware_inputs.enabled": True,
        "hardware_inputs.inputs.motion.type": "pir",
        "hardware_inputs.inputs.motion.pin": 27,
        "hardware_inputs.inputs.motion.no_motion_delay_seconds": 30,
        "hardware_inputs.inputs.motion.actions.no_motion": "DISPLAY_OFF",
    }
    mock_adapter = MockHardwareInput()

    service = HardwareInputService(
        event_bus=mock_event_bus,
        hardware_input_adapter=mock_adapter,
        config_repository=mock_repo,
    )
    service.start()

    mock_adapter.simulate_event("motion", "no_motion")
    service.stop()

    assert FakeTimer.instances[0].cancelled is True


def test_hardware_input_service_keeps_disabled_config_stopped() -> None:
    mock_event_bus = MagicMock()
    mock_repo = MagicMock()
    mock_repo.get_all_app_config.return_value = {
        "hardware_inputs.enabled": False,
        "hardware_inputs.inputs.next_button.type": "button",
        "hardware_inputs.inputs.next_button.pin": 17,
        "hardware_inputs.inputs.next_button.actions.pressed": "NEXT",
    }
    mock_adapter = MockHardwareInput()

    service = HardwareInputService(
        event_bus=mock_event_bus,
        hardware_input_adapter=mock_adapter,
        config_repository=mock_repo,
    )
    service.start()

    mock_adapter.simulate_event("next_button", "pressed")
    mock_event_bus.publish.assert_not_called()

    service.stop()


def test_hardware_input_service_reconfigures_on_config_change() -> None:
    mock_event_bus = MagicMock()
    mock_repo = MagicMock()
    mock_repo.get_all_app_config.side_effect = [
        {
            "hardware_inputs.enabled": True,
            "hardware_inputs.inputs.next_button.type": "button",
            "hardware_inputs.inputs.next_button.pin": 17,
            "hardware_inputs.inputs.next_button.actions.pressed": "NEXT",
        },
        {
            "hardware_inputs.enabled": True,
            "hardware_inputs.inputs.pause_button.type": "button",
            "hardware_inputs.inputs.pause_button.pin": 22,
            "hardware_inputs.inputs.pause_button.actions.pressed": "PAUSE",
        },
    ]
    mock_adapter = MockHardwareInput()

    service = HardwareInputService(
        event_bus=mock_event_bus,
        hardware_input_adapter=mock_adapter,
        config_repository=mock_repo,
    )
    service.start()

    service._handle_state_event(
        StateEvent(state=State.CONFIG_CHANGED, payload={"updated_sections": ["hardware_inputs"]})
    )
    mock_adapter.simulate_event("pause_button", "pressed")

    mock_event_bus.publish.assert_called_with(CommandEvent(command=Command.PAUSE))
    assert mock_adapter.config == {
        "pause_button": {"type": "button", "pin": 22, "bounce_time": 0.1}
    }

    service.stop()


def test_hardware_input_service_reconfigure_cancels_pending_no_motion(monkeypatch) -> None:
    FakeTimer.instances.clear()
    monkeypatch.setattr("picframe.core.services.hardware_input.threading.Timer", FakeTimer)
    mock_event_bus = MagicMock()
    mock_repo = MagicMock()
    mock_repo.get_all_app_config.side_effect = [
        {
            "hardware_inputs.enabled": True,
            "hardware_inputs.inputs.motion.type": "pir",
            "hardware_inputs.inputs.motion.pin": 27,
            "hardware_inputs.inputs.motion.no_motion_delay_seconds": 30,
            "hardware_inputs.inputs.motion.actions.no_motion": "DISPLAY_OFF",
        },
        {
            "hardware_inputs.enabled": True,
            "hardware_inputs.inputs.next_button.type": "button",
            "hardware_inputs.inputs.next_button.pin": 17,
            "hardware_inputs.inputs.next_button.actions.pressed": "NEXT",
        },
    ]
    mock_adapter = MockHardwareInput()

    service = HardwareInputService(
        event_bus=mock_event_bus,
        hardware_input_adapter=mock_adapter,
        config_repository=mock_repo,
    )
    service.start()
    mock_adapter.simulate_event("motion", "no_motion")

    service._handle_state_event(
        StateEvent(state=State.CONFIG_CHANGED, payload={"updated_sections": ["hardware_inputs"]})
    )

    assert FakeTimer.instances[0].cancelled is True

    service.stop()
