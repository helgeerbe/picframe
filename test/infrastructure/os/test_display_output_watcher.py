"""Tests for DisplayOutputWatcher (#755)."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

from picframe.core.events.dto import DisplayPowerEvent
from picframe.infrastructure.os.display_output_watcher import DisplayOutputWatcher

_WLR_RANDR_ON = "DSI-1\n  enabled: no\n\nHDMI-A-1\n  enabled: yes\n  mode: 1920x1080\n"
_WLR_RANDR_OFF = "DSI-1\n  enabled: yes\n"  # HDMI-A-1 absent (HPD drop)
_WLR_RANDR_DISABLED = "HDMI-A-1\n  enabled: no\n"


def _completed(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["wlr-randr"], returncode=returncode, stdout=stdout, stderr=""
    )


def test_parse_output_state_enabled() -> None:
    w = DisplayOutputWatcher("HDMI-A-1", MagicMock())
    assert w._parse_output_state(_WLR_RANDR_ON) is True


def test_parse_output_state_absent_is_off() -> None:
    w = DisplayOutputWatcher("HDMI-A-1", MagicMock())
    # Output not listed at all -> real off (False), not a probe error.
    assert w._parse_output_state(_WLR_RANDR_OFF) is False


def test_parse_output_state_disabled_is_off() -> None:
    w = DisplayOutputWatcher("HDMI-A-1", MagicMock())
    assert w._parse_output_state(_WLR_RANDR_DISABLED) is False


def test_parse_output_state_listed_without_enabled_key_defaults_on() -> None:
    w = DisplayOutputWatcher("HDMI-A-1", MagicMock())
    # Older wlr-randr lists only enabled outputs with no `enabled:` key.
    assert w._parse_output_state("HDMI-A-1\n  mode: 1920x1080\n") is True


@patch("picframe.infrastructure.os.display_output_watcher.subprocess.run")
def test_default_probe_wlr_randr_missing_returns_none(mock_run: MagicMock) -> None:
    mock_run.side_effect = FileNotFoundError
    w = DisplayOutputWatcher("HDMI-A-1", MagicMock())
    assert w._default_probe() is None
    assert w._default_probe() is None  # second call: still None, logged once


@patch("picframe.infrastructure.os.display_output_watcher.subprocess.run")
def test_default_probe_nonzero_return_returns_none(mock_run: MagicMock) -> None:
    mock_run.return_value = _completed("x", returncode=1)
    w = DisplayOutputWatcher("HDMI-A-1", MagicMock())
    assert w._default_probe() is None


@patch("picframe.infrastructure.os.display_output_watcher.subprocess.run")
def test_default_probe_parses_enabled(mock_run: MagicMock) -> None:
    mock_run.return_value = _completed(_WLR_RANDR_ON)
    w = DisplayOutputWatcher("HDMI-A-1", MagicMock())
    assert w._default_probe() is True


@patch("picframe.infrastructure.os.display_output_watcher.subprocess.run")
def test_default_probe_timeout_returns_none(mock_run: MagicMock) -> None:
    mock_run.side_effect = subprocess.TimeoutExpired(cmd="wlr-randr", timeout=3)
    w = DisplayOutputWatcher("HDMI-A-1", MagicMock())
    assert w._default_probe() is None


def test_start_stop_publishes_on_off_to_on_transition() -> None:
    publisher = MagicMock()
    states: list = [True, False, True, True]  # baseline True, off, on, on
    w = DisplayOutputWatcher(
        "HDMI-A-1",
        publisher,
        probe_interval=0.01,
        probe=lambda: states.pop(0) if states else True,
    )
    w.start()
    import time

    time.sleep(0.2)
    w.stop()
    published = [c.args[0] for c in publisher.publish.call_args_list]
    assert published == [DisplayPowerEvent(power_on=False), DisplayPowerEvent(power_on=True)]


def test_start_does_not_publish_baseline() -> None:
    publisher = MagicMock()
    w = DisplayOutputWatcher("HDMI-A-1", publisher, probe_interval=0.01, probe=lambda: True)
    w.start()
    import time

    time.sleep(0.1)
    w.stop()
    publisher.publish.assert_not_called()


def test_none_probe_does_not_publish_or_update_baseline() -> None:
    publisher = MagicMock()
    states: list = [True, None, None, False, True]
    w = DisplayOutputWatcher(
        "HDMI-A-1",
        publisher,
        probe_interval=0.01,
        probe=lambda: states.pop(0) if states else True,
    )
    w.start()
    import time

    time.sleep(0.25)
    w.stop()
    published = [c.args[0] for c in publisher.publish.call_args_list]
    # Baseline True; None probes skipped (baseline stays True); False -> publish
    # power_on=False; True -> publish power_on=True.
    assert published == [DisplayPowerEvent(power_on=False), DisplayPowerEvent(power_on=True)]


def test_baseline_none_then_real_state_no_spurious_publish() -> None:
    publisher = MagicMock()
    states: list = [None, True, True, False]
    w = DisplayOutputWatcher(
        "HDMI-A-1",
        publisher,
        probe_interval=0.01,
        probe=lambda: states.pop(0) if states else False,
    )
    w.start()
    import time

    time.sleep(0.25)
    w.stop()
    published = [c.args[0] for c in publisher.publish.call_args_list]
    # Baseline None -> first True sets baseline (no publish); then True (no
    # change); then False -> publish power_on=False only.
    assert published == [DisplayPowerEvent(power_on=False)]


def test_start_stop_idempotent() -> None:
    publisher = MagicMock()
    w = DisplayOutputWatcher("HDMI-A-1", publisher, probe_interval=0.5, probe=lambda: True)
    w.start()
    w.start()  # no second thread
    assert w._thread is not None
    assert w._thread.is_alive()
    w.stop()
    assert w._thread is None
    w.stop()  # no error


@patch("picframe.infrastructure.os.display_output_watcher.subprocess.run")
def test_watcher_event_drives_renderer_respawn(mock_run: MagicMock, monkeypatch) -> None:
    """A watcher off->on transition publishes the DisplayPowerEvent the
    WebKitOverlayRenderer respawns on (#755 external power-cycle path)."""
    import tempfile
    from pathlib import Path

    from picframe.core.renderers import webkit_overlay_renderer as wor
    from picframe.core.renderers.webkit_overlay_renderer import WebKitOverlayRenderer
    from picframe.infrastructure.overlay.plugin_loader import PluginLoader

    tmp = Path(tempfile.mkdtemp())
    plugin_loader = PluginLoader(str(tmp))
    publisher = MagicMock()
    renderer = WebKitOverlayRenderer(
        event_publisher=MagicMock(),
        event_subscriber=MagicMock(),
        plugin_loader=plugin_loader,
        html_dir=str(tmp),
        plugin_dir=str(tmp),
        ws_port=9000,
        overlay_config={"enabled": True},
    )
    renderer._availability = True
    # Simulate the external power-cycle case (#755): the worker crashed when
    # the output was destroyed, so _running is False — but _stopped is False
    # (not an intentional shutdown), so the handler must still respawn.
    renderer._running = False
    renderer._stopped = False

    states: list = [_WLR_RANDR_ON, _WLR_RANDR_OFF, _WLR_RANDR_ON, _WLR_RANDR_ON]

    def fake_run(*a, **k):
        return _completed(states.pop(0) if states else _WLR_RANDR_ON)

    mock_run.side_effect = fake_run
    w = DisplayOutputWatcher("HDMI-A-1", publisher, probe_interval=0.01)
    w.start()
    import time

    time.sleep(0.25)
    w.stop()

    published = [c.args[0] for c in publisher.publish.call_args_list]
    assert DisplayPowerEvent(power_on=False) in published
    assert DisplayPowerEvent(power_on=True) in published

    class _SyncThread:
        def __init__(self, target=None, **kwargs) -> None:
            self._target = target

        def start(self) -> None:
            if self._target is not None:
                self._target()

        def join(self, timeout=None) -> None:
            return None

    monkeypatch.setattr(wor.threading, "Thread", _SyncThread)
    with (
        patch.object(renderer, "_unsubscribe_events") as mock_unsub,
        patch.object(renderer, "_cleanup") as mock_cleanup,
        patch.object(renderer, "start") as mock_start,
    ):
        renderer._on_display_power_event(DisplayPowerEvent(power_on=True))
        mock_unsub.assert_called_once()
        mock_cleanup.assert_called_once()
        mock_start.assert_called_once()
