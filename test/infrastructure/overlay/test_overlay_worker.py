"""Tests for the out-of-process overlay worker IPC plumbing (GTK-free)."""

from unittest.mock import MagicMock

import pytest

from picframe.core.renderers.overlay_ipc import (
    INPUT_ACTION_NEXT,
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
