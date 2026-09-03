"""Tests for the out-of-process overlay worker IPC plumbing (GTK-free)."""

import json
from unittest.mock import MagicMock

import pytest

from picframe.core.renderers.overlay_ipc import (
    INPUT_ACTION_HIDE,
    INPUT_ACTION_NEXT,
    INPUT_ACTION_PREV,
    INPUT_ACTION_TOGGLE,
    OverlayErrorEvent,
    ReadyEvent,
    ReloadCommand,
    SetConfigCommand,
    SetOpacityCommand,
    ShutdownCommand,
)
from picframe.infrastructure.overlay.overlay_worker import OverlayWorker, parse_args


def make_worker() -> OverlayWorker:
    return OverlayWorker(
        socket_path="/tmp/unused.sock", html_dir="/html", plugin_dir="/plugins", ws_port=9000
    )


def test_handle_set_opacity_clamps_and_stores() -> None:
    worker = make_worker()
    assert worker.handle_command(SetOpacityCommand(opacity=1.5)) is True
    assert worker._opacity == 1.0
    assert worker.handle_command(SetOpacityCommand(opacity=-0.2)) is True
    assert worker._opacity == 0.0


def test_handle_set_config_stores_config() -> None:
    worker = make_worker()
    worker.handle_command(SetConfigCommand(config={"enabled": True}))
    assert worker._config == {"enabled": True}


def test_handle_reload_returns_true() -> None:
    worker = make_worker()
    assert worker.handle_command(ReloadCommand()) is True


def test_handle_shutdown_returns_false() -> None:
    worker = make_worker()
    assert worker.handle_command(ShutdownCommand()) is False


def test_emit_input_sends_event_on_connection() -> None:
    worker = make_worker()
    conn = MagicMock()
    worker._conn = conn
    worker.emit_input(INPUT_ACTION_NEXT)
    conn.send.assert_called_once()
    sent = conn.send.call_args[0][0]
    assert '"type": "input"' in sent
    assert '"action": "next"' in sent


def test_emit_input_no_connection_does_not_raise() -> None:
    worker = make_worker()
    worker._conn = None
    worker.emit_input(INPUT_ACTION_NEXT)  # must not raise


def test_send_event_swallows_send_errors() -> None:
    worker = make_worker()
    conn = MagicMock()
    conn.send.side_effect = OSError("closed")
    worker._conn = conn
    worker._send_event(ReadyEvent())  # must not raise


def test_serve_emits_ready_then_handles_command() -> None:
    worker = make_worker()
    conn = MagicMock()
    # poll() returns True once (command), then False forever; recv returns JSON.
    conn.poll.side_effect = [True, False, False]
    conn.recv.return_value = ShutdownCommand().to_json()
    worker._serve(conn)
    # Ready is emitted first.
    first = conn.send.call_args_list[0][0][0]
    assert '"type": "ready"' in first
    # Worker stops after the shutdown command (no further recv).


def test_serve_skips_unparseable_lines() -> None:
    worker = make_worker()
    conn = MagicMock()
    conn.poll.side_effect = [True, True, False, False]
    conn.recv.side_effect = ["not json", ShutdownCommand().to_json()]
    worker._serve(conn)
    # Ready + nothing for the bad line; shutdown ends the loop without error.
    assert conn.send.call_count >= 1


def test_serve_reports_handler_exception_as_error() -> None:
    worker = make_worker()
    conn = MagicMock()
    conn.poll.side_effect = [True, False, False]
    conn.recv.return_value = SetConfigCommand(config={"x": 1}).to_json()
    worker.handle_command = MagicMock(side_effect=RuntimeError("kaboom"))  # type: ignore[method-assign]
    worker._serve(conn)
    error_sent = conn.send.call_args_list[-1][0][0]
    assert '"type": "error"' in error_sent
    assert "kaboom" in error_sent


def test_serve_stops_on_eof() -> None:
    worker = make_worker()
    conn = MagicMock()
    conn.poll.side_effect = [True]
    conn.recv.side_effect = [EOFError()]
    worker._serve(conn)  # must not raise
    assert conn.send.called  # Ready was emitted


def test_parse_args_required() -> None:
    args = parse_args(
        ["--socket", "/tmp/s.sock", "--html-dir", "/h", "--plugin-dir", "/p", "--ws-port", "1234"]
    )
    assert args.socket == "/tmp/s.sock"
    assert args.html_dir == "/h"
    assert args.plugin_dir == "/p"
    assert args.ws_port == 1234


def test_parse_args_defaults_ws_port() -> None:
    args = parse_args(["--socket", "/tmp/s.sock", "--html-dir", "/h", "--plugin-dir", "/p"])
    assert args.ws_port == 9000


def test_parse_args_missing_required_exits() -> None:
    with pytest.raises(SystemExit):
        parse_args(["--socket", "/tmp/s.sock"])


def test_handle_command_unknown_message_returns_true() -> None:
    """An unrecognised (but valid) message type is a no-op, not a shutdown."""
    worker = make_worker()
    unknown = OverlayErrorEvent(details="x")  # an event, not a command
    assert worker.handle_command(unknown) is True


def test_handle_bridge_message_emits_input_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each navigation action is forwarded to ``emit_input``."""
    worker = make_worker()
    emitted: list[str] = []
    monkeypatch.setattr(worker, "emit_input", lambda action: emitted.append(action))
    for action in (INPUT_ACTION_PREV, INPUT_ACTION_NEXT, INPUT_ACTION_TOGGLE, INPUT_ACTION_HIDE):
        worker._handle_bridge_message({"action": action})
    assert emitted == [INPUT_ACTION_PREV, INPUT_ACTION_NEXT, INPUT_ACTION_TOGGLE, INPUT_ACTION_HIDE]


def test_handle_bridge_message_request_config_pushes_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shell boot handshake asks for the initial config via the bridge."""
    worker = make_worker()
    calls: list[bool] = []
    monkeypatch.setattr(worker, "_push_config_to_shell", lambda: calls.append(True))
    worker._handle_bridge_message({"action": "__request_config"})
    assert calls == [True]


def test_handle_bridge_message_ignores_unknown_action() -> None:
    worker = make_worker()
    worker._conn = None  # ensure no accidental emit
    worker._handle_bridge_message({"action": "???"})  # must not raise


def test_push_config_to_shell_noop_without_surface() -> None:
    """Headless (no WebView) config push is a no-op, never raises."""
    worker = make_worker()
    worker._web_view = None
    worker._push_config_to_shell()  # must not raise


def test_build_shell_config_merges_plugins_and_env(tmp_path) -> None:
    """The shell config carries overlay keys plus the plugin list + env."""
    plugin_dir = tmp_path / "plugins"
    clock = plugin_dir / "clock"
    clock.mkdir(parents=True)
    (clock / "plugin.json").write_text(
        json.dumps({"id": "clock", "name": "Clock", "icon": "🕐", "entry": "index.html"})
    )
    (clock / "index.html").write_text("<html></html>")
    worker = OverlayWorker(
        socket_path="/tmp/x.sock",
        html_dir=str(tmp_path / "html"),
        plugin_dir=str(plugin_dir),
        ws_port=1234,
    )
    worker._config = {"enabled_plugins": ["clock"], "visible_plugin": "clock"}
    cfg = worker._build_shell_config()
    assert cfg["enabled_plugins"] == ["clock"]
    assert cfg["_ws_port"] == 1234
    assert cfg["_plugin_uri"].startswith("file://")
    assert len(cfg["_plugins"]) == 1
    plugin = cfg["_plugins"][0]
    assert plugin["id"] == "clock"
    assert plugin["name"] == "Clock"
    assert plugin["icon"] == "🕐"
    assert plugin["entry_uri"].startswith("file://")
    assert plugin["entry_uri"].endswith("clock/index.html")


def test_build_shell_config_empty_plugin_dir(tmp_path) -> None:
    """A missing/empty plugin dir yields an empty plugin list, not an error."""
    worker = OverlayWorker(
        socket_path="/tmp/x.sock",
        html_dir=str(tmp_path / "html"),
        plugin_dir=str(tmp_path / "missing-plugins"),
        ws_port=9000,
    )
    worker._config = {}
    cfg = worker._build_shell_config()
    assert cfg["_plugins"] == []
    assert cfg["_ws_port"] == 9000


def test_shell_uri_includes_query_params(tmp_path) -> None:
    """The worker hands the shell the WS port + plugin dir via the load URI."""
    overlay_dir = tmp_path / "html" / "overlay"
    overlay_dir.mkdir(parents=True)
    (overlay_dir / "index.html").write_text("<html></html>")
    worker = OverlayWorker(
        socket_path="/tmp/x.sock",
        html_dir=str(tmp_path / "html"),
        plugin_dir=str(tmp_path / "plugins"),
        ws_port=9000,
    )
    uri = worker._shell_uri()
    assert uri.startswith("file://")
    assert "ws=9000" in uri
    assert "plugins=file" in uri
