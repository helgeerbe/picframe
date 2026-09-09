"""
Evdev wake-input adapter (#762).

Reads raw input devices under ``/dev/input/event*`` via the ``evdev`` library
so the backend can wake the display while the configured Wayland output is
destroyed by ``wlr-randr --off`` (the overlay's JS listeners cannot fire in
that state because the layer-shell surface is gone).

The adapter listens *passively* (it does not ``grab()`` devices), so the
compositor keeps receiving events for normal UI while the display is on. It
filters to pointer + keyboard devices (touch devices are excluded by design)
and emits ``"mouse"`` on relative pointer motion and ``"keyboard"`` on key
events.

The ``evdev`` dependency is imported lazily so this module imports cleanly on
non-Linux / CI hosts. :meth:`is_available` probes whether input devices exist
and are readable; if not, the HAL factory falls back to the mock listener.
"""

import logging
import os
import threading
from collections.abc import Callable

from picframe.core.ports import IWakeInputListener

logger = logging.getLogger(__name__)

# evdev event/bit constants used for device classification. Defined here as
# module-level ints so the adapter can be unit-tested without importing evdev
# (the real values come from the kernel uapi headers and never change).
_EV_REL = 0x02
_EV_KEY = 0x01
_REL_X = 0x00
_REL_Y = 0x01
_BTN_LEFT = 0x110
_KEY_ESC = 0x01
_BTN_TOUCH = 0x14A

_INPUT_DEVICE_DIR = "/dev/input"


class EvdevWakeAdapter(IWakeInputListener):
    """
    Backend wake-input listener backed by the ``evdev`` library.

    Reads pointer and keyboard ``/dev/input/event*`` devices on daemon threads
    and invokes the registered callback with ``"mouse"`` or ``"keyboard"``
    when a wake-capable event occurs.
    """

    def __init__(self) -> None:
        self._callback: Callable[[str], None] | None = None
        self._threads: list[threading.Thread] = []
        self._devices: list[object] = []
        self._stop_event = threading.Event()
        self._started = False
        logger.info("EvdevWakeAdapter initialized.")

    @staticmethod
    def is_available() -> bool:
        """Probe whether ``evdev`` is importable and input devices are readable."""
        try:
            import evdev  # noqa: F401  pylint: disable=import-outside-toplevel
        except ImportError:
            return False
        if not os.path.isdir(_INPUT_DEVICE_DIR):
            return False
        try:
            names = os.listdir(_INPUT_DEVICE_DIR)
        except OSError:
            # Directory vanished or unreadable between the isdir check and
            # enumeration; treat as "no wake devices available" so the HAL
            # factory falls back to the mock listener (#762).
            return False
        for name in names:
            if not name.startswith("event"):
                continue
            path = os.path.join(_INPUT_DEVICE_DIR, name)
            if os.access(path, os.R_OK):
                return True
        return False

    def register_callback(self, callback: Callable[[str], None]) -> None:
        self._callback = callback
        logger.info("EvdevWakeAdapter: Callback registered.")

    def start(self) -> None:
        if self._started:
            return
        try:
            import evdev  # pylint: disable=import-outside-toplevel
        except ImportError:
            logger.warning("EvdevWakeAdapter: 'evdev' not available; wake-on-input disabled.")
            return

        self._stop_event.clear()
        try:
            names = os.listdir(_INPUT_DEVICE_DIR)
        except OSError as exc:
            logger.warning(
                "EvdevWakeAdapter: Cannot enumerate %s (%s); wake-on-input inactive.",
                _INPUT_DEVICE_DIR,
                exc,
            )
            self._started = True
            return
        for name in names:
            if not name.startswith("event"):
                continue
            path = os.path.join(_INPUT_DEVICE_DIR, name)
            try:
                device = evdev.InputDevice(path)
            except (OSError, PermissionError) as exc:
                logger.warning(
                    "EvdevWakeAdapter: Cannot open %s (%s); skipping. "
                    "Is the picframe user in the 'input' group?",
                    path,
                    exc,
                )
                continue
            if not self._is_wake_device(device):
                logger.debug("EvdevWakeAdapter: Skipping non-wake device %s.", path)
                continue
            self._devices.append(device)
            thread = threading.Thread(
                target=self._read_loop,
                args=(device,),
                name=f"evdev-wake-{name}",
                daemon=True,
            )
            self._threads.append(thread)
            thread.start()
            logger.info("EvdevWakeAdapter: Listening on %s (%s).", path, device.name)

        if not self._threads:
            logger.warning(
                "EvdevWakeAdapter: No readable pointer/keyboard input devices found; "
                "wake-on-input inactive."
            )
        self._started = True

    def stop(self) -> None:
        self._stop_event.set()
        for device in self._devices:
            try:
                device.close()  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001  pylint: disable=broad-except
                pass
        for thread in self._threads:
            thread.join(timeout=2.0)
        self._devices.clear()
        self._threads.clear()
        self._started = False
        logger.info("EvdevWakeAdapter: Stopped.")

    # -- internals ----------------------------------------------------------

    @staticmethod
    def _is_wake_device(device: object) -> bool:
        """Return True for pointer (mouse) or keyboard devices; exclude touch."""
        try:
            caps = device.capabilities(absinfo=False)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            return False
        ev_rel = _EV_REL in caps
        ev_key = _EV_KEY in caps
        if ev_rel and ev_key:
            # Relative-pointer device with mouse buttons — a mouse.
            return True
        if ev_key and not ev_rel:
            key_bits = caps.get(_EV_KEY, [])
            # Keyboard: has standard keys but no touch button.
            has_keys = any(_KEY_ESC <= b < _BTN_LEFT for b in key_bits)
            has_touch = _BTN_TOUCH in key_bits
            return has_keys and not has_touch
        return False

    def _read_loop(self, device: object) -> None:
        while not self._stop_event.is_set():
            try:
                for event in device.read_loop():  # type: ignore[attr-defined]
                    if self._stop_event.is_set():
                        break
                    input_class = self._classify(event)
                    if input_class and self._callback:
                        self._callback(input_class)
            except OSError as exc:
                if self._stop_event.is_set():
                    break
                logger.warning("EvdevWakeAdapter: read error on %s: %s", device, exc)
                break
            except Exception:  # noqa: BLE001  pylint: disable=broad-except
                if self._stop_event.is_set():
                    break
                logger.exception("EvdevWakeAdapter: Unexpected error in read loop.")
                break

    @staticmethod
    def _classify(event: object) -> str | None:
        """Map a raw input event to a wake input-class, or None if not wake-worthy."""
        etype = event.type  # type: ignore[attr-defined]
        if etype == _EV_REL and event.code in (_REL_X, _REL_Y):  # type: ignore[attr-defined]
            return "mouse"
        if etype == _EV_KEY:
            code = event.code  # type: ignore[attr-defined]
            value = event.value  # type: ignore[attr-defined]
            # value 1 = key press, 2 = key repeat; ignore releases (0).
            if _KEY_ESC <= code < _BTN_LEFT and value != 0:
                return "keyboard"
        return None
