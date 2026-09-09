"""
Tests for the EvdevWakeAdapter.

The evdev library is Linux-only; these tests guard on it with importorskip and
exercise the pure device-classification logic and the lifecycle with mocked
evdev objects (#762).
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from picframe.infrastructure.os.evdev_wake_adapter import (
    _EV_KEY,
    _EV_REL,
    _REL_X,
    _REL_Y,
    EvdevWakeAdapter,
)


def _event(etype: int, code: int, value: int) -> SimpleNamespace:
    return SimpleNamespace(type=etype, code=code, value=value)


def test_classify_mouse_motion() -> None:
    assert EvdevWakeAdapter._classify(_event(_EV_REL, _REL_X, 1)) == "mouse"
    assert EvdevWakeAdapter._classify(_event(_EV_REL, _REL_Y, -1)) == "mouse"


def test_classify_keypress() -> None:
    # KEY_A = 0x1e; value 1 = press.
    assert EvdevWakeAdapter._classify(_event(_EV_KEY, 0x1E, 1)) == "keyboard"
    # Key repeat (value 2) also wakes.
    assert EvdevWakeAdapter._classify(_event(_EV_KEY, 0x1E, 2)) == "keyboard"


def test_classify_ignores_key_release() -> None:
    assert EvdevWakeAdapter._classify(_event(_EV_KEY, 0x1E, 0)) is None


def test_classify_ignores_mouse_button() -> None:
    # BTN_LEFT = 0x110 is outside the keyboard key range -> not a keyboard wake.
    assert EvdevWakeAdapter._classify(_event(_EV_KEY, 0x110, 1)) is None


def test_classify_ignores_other_event_types() -> None:
    # EV_SYN = 0x00
    assert EvdevWakeAdapter._classify(_event(0x00, 0x00, 0)) is None


def test_is_wake_device_mouse() -> None:
    device = MagicMock()
    device.capabilities.return_value = {_EV_REL: [_REL_X, _REL_Y], _EV_KEY: [0x110]}
    assert EvdevWakeAdapter._is_wake_device(device) is True


def test_is_wake_device_keyboard() -> None:
    device = MagicMock()
    # Keyboard: only EV_KEY with standard keys, no REL, no BTN_TOUCH.
    device.capabilities.return_value = {_EV_KEY: [0x01, 0x1E, 0x28]}
    assert EvdevWakeAdapter._is_wake_device(device) is True


def test_is_wake_device_excludes_touchscreen() -> None:
    device = MagicMock()
    # Touchscreen: EV_KEY with BTN_TOUCH and EV_ABS (no EV_REL).
    device.capabilities.return_value = {_EV_KEY: [0x14A, 0x14B], 0x03: [0x00]}
    assert EvdevWakeAdapter._is_wake_device(device) is False


def test_is_wake_device_excludes_pure_button_device() -> None:
    device = MagicMock()
    # EV_KEY only with BTN_LEFT, no standard keys -> not wake-worthy.
    device.capabilities.return_value = {_EV_KEY: [0x110]}
    assert EvdevWakeAdapter._is_wake_device(device) is False


def test_is_wake_device_handles_capability_error() -> None:
    device = MagicMock()
    device.capabilities.side_effect = OSError("boom")
    assert EvdevWakeAdapter._is_wake_device(device) is False


def test_register_callback_stores_callback() -> None:
    adapter = EvdevWakeAdapter()
    received: list[str] = []
    adapter.register_callback(received.append)
    # Invoke via the stored reference to confirm wiring.
    assert adapter._callback is not None
    adapter._callback("mouse")
    assert received == ["mouse"]


def test_is_available_false_when_no_input_dir() -> None:
    with (
        patch.dict("sys.modules", {"evdev": MagicMock()}),
        patch("os.path.isdir", return_value=False),
    ):
        assert EvdevWakeAdapter.is_available() is False


def test_is_available_true_when_readable_event_device() -> None:
    with (
        patch.dict("sys.modules", {"evdev": MagicMock()}),
        patch("os.path.isdir", return_value=True),
        patch("os.listdir", return_value=["event0", "mice"]),
        patch("os.access", return_value=True),
    ):
        assert EvdevWakeAdapter.is_available() is True


def test_is_available_false_when_no_event_devices() -> None:
    with (
        patch.dict("sys.modules", {"evdev": MagicMock()}),
        patch("os.path.isdir", return_value=True),
        patch("os.listdir", return_value=["mice", "by-path"]),
        patch("os.access", return_value=True),
    ):
        assert EvdevWakeAdapter.is_available() is False


def test_is_available_false_when_evdev_missing() -> None:
    # evdev not installed: the bare `import evdev` raises ImportError.
    with patch.dict("sys.modules", {"evdev": None}):
        assert EvdevWakeAdapter.is_available() is False


def test_is_available_false_when_listdir_raises() -> None:
    # /dev/input exists but enumeration fails (vanished / transient error):
    # must degrade to "not available" rather than raising (#762).
    err = OSError("boom")

    def _listdir(_path: str) -> list[str]:
        raise err

    with (
        patch.dict("sys.modules", {"evdev": MagicMock()}),
        patch("os.path.isdir", return_value=True),
        patch("os.listdir", side_effect=_listdir),
    ):
        assert EvdevWakeAdapter.is_available() is False


def test_start_open_and_listen_on_wake_device() -> None:
    adapter = EvdevWakeAdapter()
    fake_device = MagicMock()
    fake_device.name = "Test Mouse"
    fake_device.capabilities.return_value = {_EV_REL: [_REL_X, _REL_Y], _EV_KEY: [0x110]}

    fake_evdev = MagicMock()
    fake_evdev.InputDevice.return_value = fake_device
    fake_device.read_loop.side_effect = OSError("device closed by test")

    with (
        patch("os.listdir", return_value=["event0"]),
        patch("os.path.join", return_value="/dev/input/event0"),
        patch.dict("sys.modules", {"evdev": fake_evdev}),
    ):
        adapter.start()

    fake_evdev.InputDevice.assert_called_once_with("/dev/input/event0")
    assert len(adapter._threads) == 1
    assert adapter._started is True

    adapter.stop()
    fake_device.close.assert_called_once()
    assert adapter._started is False


def test_start_skips_non_wake_device() -> None:
    adapter = EvdevWakeAdapter()
    touch_device = MagicMock()
    touch_device.name = "Touch"
    touch_device.capabilities.return_value = {_EV_KEY: [0x14A]}

    fake_evdev = MagicMock()
    fake_evdev.InputDevice.return_value = touch_device

    with (
        patch("os.listdir", return_value=["event0"]),
        patch("os.path.join", return_value="/dev/input/event0"),
        patch.dict("sys.modules", {"evdev": fake_evdev}),
    ):
        adapter.start()

    assert adapter._threads == []
    assert adapter._started is True
    adapter.stop()


def test_start_logs_and_skips_unreadable_device() -> None:
    adapter = EvdevWakeAdapter()
    fake_evdev = MagicMock()
    fake_evdev.InputDevice.side_effect = PermissionError("denied")

    with (
        patch("os.listdir", return_value=["event0"]),
        patch("os.path.join", return_value="/dev/input/event0"),
        patch.dict("sys.modules", {"evdev": fake_evdev}),
    ):
        adapter.start()

    assert adapter._threads == []
    assert adapter._started is True
    adapter.stop()


def test_start_noop_without_evdev() -> None:
    adapter = EvdevWakeAdapter()
    # Force the lazy `import evdev` inside start() to fail.
    with patch.dict("sys.modules", {"evdev": None}):
        adapter.start()
    assert adapter._threads == []
    assert adapter._started is False


def test_start_inactive_when_listdir_raises() -> None:
    # /dev/input enumeration fails at start(): must log + go inactive
    # rather than propagating out of service startup (#762).
    adapter = EvdevWakeAdapter()
    err = OSError("boom")

    def _listdir(_path: str) -> list[str]:
        raise err

    with (
        patch.dict("sys.modules", {"evdev": MagicMock()}),
        patch("os.listdir", side_effect=_listdir),
    ):
        adapter.start()

    assert adapter._threads == []
    assert adapter._started is True
    adapter.stop()
