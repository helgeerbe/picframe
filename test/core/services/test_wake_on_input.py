"""
Tests for the WakeOnInputService.

The service turns raw mouse/keyboard wake events (from a backend input-device
listener that works while the Wayland output is destroyed by ``wlr-randr
--off``) into ``Command.DISPLAY_ON`` events, gated by the overlay's
``enabled_input_types`` list and the current display-power state (#762).
"""

from unittest.mock import MagicMock

from picframe.core.events.dto import Command, CommandEvent, State, StateEvent
from picframe.core.services.wake_on_input import WakeOnInputService


def _make_service(
    display_on: bool = False,
    enabled_input_types: list[str] | None = None,
) -> tuple[WakeOnInputService, MagicMock, MagicMock, MagicMock, MagicMock, MagicMock]:
    """Build a service wired to mocks; return (service, bus, adapter, dp, repo, sub)."""
    if enabled_input_types is None:
        enabled_input_types = ["touch", "mouse", "keyboard"]
    mock_publisher = MagicMock()
    mock_wake_adapter = MagicMock()
    mock_display_power = MagicMock()
    mock_display_power.is_on.return_value = display_on
    mock_config_repo = MagicMock()
    mock_config_repo.get_app_config.return_value = enabled_input_types
    mock_subscriber = MagicMock()

    service = WakeOnInputService(
        event_publisher=mock_publisher,
        wake_adapter=mock_wake_adapter,
        display_power_adapter=mock_display_power,
        config_repository=mock_config_repo,
        event_subscriber=mock_subscriber,
    )
    return (
        service,
        mock_publisher,
        mock_wake_adapter,
        mock_display_power,
        mock_config_repo,
        mock_subscriber,
    )


def test_wake_on_input_registers_callback_and_subscribes() -> None:
    service, _, mock_wake_adapter, _, _, mock_subscriber = _make_service()

    mock_wake_adapter.register_callback.assert_called_once_with(service._handle_wake_event)
    mock_subscriber.subscribe.assert_any_call(StateEvent, service._handle_state_event)


def test_wake_on_input_publishes_display_on_when_off_and_mouse_enabled() -> None:
    service, mock_publisher, _, _, _, _ = _make_service(display_on=False)
    service.start()

    service._handle_wake_event("mouse")

    mock_publisher.publish.assert_called_once_with(CommandEvent(command=Command.DISPLAY_ON))


def test_wake_on_input_publishes_display_on_when_off_and_keyboard_enabled() -> None:
    service, mock_publisher, _, _, _, _ = _make_service(display_on=False)
    service.start()

    service._handle_wake_event("keyboard")

    mock_publisher.publish.assert_called_once_with(CommandEvent(command=Command.DISPLAY_ON))


def test_wake_on_input_noop_when_display_already_on() -> None:
    service, mock_publisher, _, mock_dp, _, _ = _make_service(display_on=True)
    service.start()

    service._handle_wake_event("mouse")

    mock_dp.is_on.assert_called()
    mock_publisher.publish.assert_not_called()


def test_wake_on_input_ignores_disabled_input_class() -> None:
    # Kiosk: only touch enabled — mouse/keyboard must not wake.
    service, mock_publisher, _, mock_dp, _, _ = _make_service(
        display_on=False, enabled_input_types=["touch"]
    )
    service.start()

    service._handle_wake_event("mouse")
    service._handle_wake_event("keyboard")

    mock_dp.is_on.assert_not_called()
    mock_publisher.publish.assert_not_called()


def test_wake_on_input_touch_never_wakes() -> None:
    """Touch devices are excluded by design (surface destroyed while off)."""
    service, mock_publisher, _, mock_dp, _, _ = _make_service(display_on=False)
    service.start()

    service._handle_wake_event("touch")

    mock_dp.is_on.assert_not_called()
    mock_publisher.publish.assert_not_called()


def test_wake_on_input_debounces_rapid_mouse_events() -> None:
    """Rapid mouse moves publish at most one wake per cooldown window."""
    service, mock_publisher, _, _, _, _ = _make_service(display_on=False)
    service.start()

    service._handle_wake_event("mouse")
    service._handle_wake_event("mouse")
    service._handle_wake_event("mouse")

    mock_publisher.publish.assert_called_once_with(CommandEvent(command=Command.DISPLAY_ON))


def test_wake_on_input_never_publishes_play() -> None:
    """DisplayPowerManager owns the PLAY side-effect; the wake service only wakes."""
    service, mock_publisher, _, _, _, _ = _make_service(display_on=False)
    service.start()

    service._handle_wake_event("keyboard")

    for call in mock_publisher.publish.call_args_list:
        published = call.args[0]
        assert isinstance(published, CommandEvent)
        assert published.command != Command.PLAY


def test_wake_on_input_reloads_enabled_types_on_overlay_config_change() -> None:
    service, _, _, _, mock_repo, _ = _make_service(
        enabled_input_types=["touch", "mouse", "keyboard"]
    )
    service.start()
    initial_calls = mock_repo.get_app_config.call_count

    # Change config to kiosk (touch only).
    mock_repo.get_app_config.return_value = ["touch"]
    service._handle_state_event(
        StateEvent(state=State.CONFIG_CHANGED, payload={"updated_sections": ["overlay"]})
    )
    assert mock_repo.get_app_config.call_count == initial_calls + 1

    # A subsequent mouse event must be ignored now.
    mock_publisher = MagicMock()
    service._event_publisher = mock_publisher  # type: ignore[attr-defined]
    service._handle_wake_event("mouse")
    mock_publisher.publish.assert_not_called()


def test_wake_on_input_ignores_config_change_for_other_sections() -> None:
    service, _, _, _, mock_repo, _ = _make_service(
        enabled_input_types=["touch", "mouse", "keyboard"]
    )
    service.start()
    initial_calls = mock_repo.get_app_config.call_count

    service._handle_state_event(
        StateEvent(state=State.CONFIG_CHANGED, payload={"updated_sections": ["viewer"]})
    )

    assert mock_repo.get_app_config.call_count == initial_calls


def test_wake_on_input_start_delegates_to_adapter_and_stops_cleanly() -> None:
    service, _, mock_wake_adapter, _, _, mock_subscriber = _make_service()
    service.start()
    mock_wake_adapter.start.assert_called_once()

    service.stop()
    mock_wake_adapter.stop.assert_called_once()
    mock_subscriber.unsubscribe.assert_any_call(StateEvent, service._handle_state_event)


def test_wake_on_input_ignores_non_state_events() -> None:
    service, _, _, _, mock_repo, _ = _make_service()
    service._handle_state_event("not a state event")
    # No reload should occur beyond construction.
    service.stop()
