"""Tests for the out-of-process overlay worker IPC plumbing (GTK-free)."""

import json
import logging
from pathlib import Path
from typing import Any
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


def test_handle_bridge_message_console_forwarding_routes_levels(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Forwarded JS console lines are logged by level so a blocked/failing
    overlay shell becomes visible in the journal (#739)."""
    worker = make_worker()
    caplog.set_level(logging.DEBUG, logger="overlay_worker")
    worker._handle_bridge_message({"action": "__console", "level": "error", "text": "boom"})
    worker._handle_bridge_message({"action": "__console", "level": "warn", "text": "careful"})
    worker._handle_bridge_message({"action": "__console", "level": "info", "text": "hi"})
    msgs = [r.message for r in caplog.records if r.name == "overlay_worker"]
    assert "[overlay-js] boom" in msgs
    assert "[overlay-js] careful" in msgs
    assert "[overlay-js] hi" in msgs
    # Levels routed to the right log methods.
    assert any(
        r.levelno == logging.ERROR and r.message == "[overlay-js] boom" for r in caplog.records
    )
    assert any(
        r.levelno == logging.WARNING and r.message == "[overlay-js] careful" for r in caplog.records
    )


def test_build_surface_connects_load_diagnostics(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_build_surface`` wires ``load-changed`` / ``load-failed`` so a blocked or
    failed shell load is logged instead of silently swallowed (#739)."""
    import picframe.infrastructure.overlay.overlay_worker as mod

    fake_gtk = MagicMock()
    fake_webkit = MagicMock()
    monkeypatch.setattr(mod, "LAYER_SHELL_AVAILABLE", False)
    monkeypatch.setattr(mod, "Gtk", fake_gtk)
    monkeypatch.setattr(mod, "WebKit", fake_webkit)
    worker = make_worker()
    monkeypatch.setattr(worker, "_setup_layer_shell", lambda w: None)
    worker._build_surface()

    web_view = fake_webkit.WebView.return_value
    web_view.connect.assert_any_call("load-changed", worker._on_load_changed)
    web_view.connect.assert_any_call("load-failed", worker._on_load_failed)


def test_inject_console_forwarding_pushes_forwarder_script(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The injected diagnostic script forwards console + uncaught errors to the
    native bridge via the registered ``picframe`` message handler (#739)."""
    import picframe.infrastructure.overlay.overlay_worker as mod

    worker = make_worker()
    worker._web_view = MagicMock()
    monkeypatch.setattr(mod, "WEBKIT_AVAILABLE", True)
    pushed: list[str] = []
    monkeypatch.setattr(worker, "_push_to_shell", lambda js: pushed.append(js))
    worker._inject_console_forwarding()
    assert len(pushed) == 1
    js = pushed[0]
    assert "__pfConsoleFwd" in js
    assert "webkit.messageHandlers.picframe.postMessage" in js
    assert "unhandledrejection" in js
    assert "window.addEventListener('error'" in js


def test_on_load_changed_injects_forwarder_on_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    """At COMMITTED the console forwarder is installed; other states only log."""
    import picframe.infrastructure.overlay.overlay_worker as mod

    monkeypatch.setattr(mod, "_load_event_name", lambda le: le)  # passthrough name
    worker = make_worker()
    injected: list[bool] = []
    monkeypatch.setattr(worker, "_inject_console_forwarding", lambda: injected.append(True))
    worker._on_load_changed(None, "STARTED")
    worker._on_load_changed(None, "COMMITTED")
    worker._on_load_changed(None, "FINISHED")
    assert injected == [True]  # only on COMMITTED


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


def test_shell_uri_prefers_vite_build_layout(tmp_path) -> None:
    """The Vite overlay build emits ``overlay/overlay.html`` (not ``index.html``);
    the worker must resolve that file when present (#739)."""
    overlay_dir = tmp_path / "html" / "overlay"
    overlay_dir.mkdir(parents=True)
    (overlay_dir / "overlay.html").write_text("<html></html>")
    worker = OverlayWorker(
        socket_path="/tmp/x.sock",
        html_dir=str(tmp_path / "html"),
        plugin_dir=str(tmp_path / "plugins"),
        ws_port=9000,
    )
    uri = worker._shell_uri()
    assert uri.startswith("file://")
    assert "overlay/overlay.html" in uri


def test_setup_layer_shell_configures_fullscreen_overlay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """wlr-layer-shell wiring: overlay layer, anchored to all edges, no exclusive
    zone, on-demand keyboard (#739 task 8). GTK-free except the typelib calls."""
    import picframe.infrastructure.overlay.overlay_worker as mod

    fake = MagicMock()
    monkeypatch.setattr(mod, "Gtk4LayerShell", fake)
    worker = make_worker()
    window = MagicMock()
    worker._setup_layer_shell(window)

    fake.init_for_window.assert_called_once_with(window)
    fake.set_layer.assert_called_once_with(window, fake.Layer.OVERLAY)
    # Anchored to all four edges with True.
    assert fake.set_anchor.call_count == 4
    for call in fake.set_anchor.call_args_list:
        window_arg, _edge_arg, anchor_arg = call[0]
        assert window_arg is window
        assert anchor_arg is True
    # -1 = float on top without reserving space.
    fake.set_exclusive_zone.assert_called_once_with(window, -1)
    fake.set_keyboard_mode.assert_called_once_with(window, fake.KeyboardMode.ON_DEMAND)


def test_setup_layer_shell_degrades_when_shared_library_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Typelib present but backing ``.so`` absent: first runtime call raises
    ``GLib.GError`` (GObject-introspection loads the shared library lazily). The
    worker must fall back to a plain borderless window instead of crashing —
    matching the documented graceful degrade (#739 task 8)."""
    import picframe.infrastructure.overlay.overlay_worker as mod

    fake = MagicMock()
    # The typelib imported fine, but the first call fails to load the .so.
    fake.init_for_window.side_effect = Exception("could not locate gtk_layer_init_for_window")
    monkeypatch.setattr(mod, "Gtk4LayerShell", fake)
    monkeypatch.setattr(mod, "LAYER_SHELL_AVAILABLE", True)
    worker = make_worker()
    window = MagicMock()

    # Must not raise.
    worker._setup_layer_shell(window)

    # The runtime failure flips the availability flag so later checks degrade.
    assert mod.LAYER_SHELL_AVAILABLE is False
    # init_for_window was attempted, but the later calls were never reached.
    fake.init_for_window.assert_called_once_with(window)
    fake.set_layer.assert_not_called()


def test_build_surface_uses_layer_shell_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the typelib is present the surface is initialized as a layer shell."""
    import picframe.infrastructure.overlay.overlay_worker as mod

    fake_gtk = MagicMock()
    fake_webkit = MagicMock()
    monkeypatch.setattr(mod, "LAYER_SHELL_AVAILABLE", True)
    monkeypatch.setattr(mod, "Gtk", fake_gtk)
    monkeypatch.setattr(mod, "WebKit", fake_webkit)
    setup_calls: list[Any] = []
    worker = make_worker()
    monkeypatch.setattr(worker, "_setup_layer_shell", lambda w: setup_calls.append(w))
    worker._build_surface()

    assert len(setup_calls) == 1
    assert setup_calls[0] is fake_gtk.Window.return_value
    fake_webkit.WebView.return_value.load_uri.assert_called_once()


def test_build_surface_skips_layer_shell_when_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without the typelib the worker falls back to a plain borderless window."""
    import picframe.infrastructure.overlay.overlay_worker as mod

    fake_gtk = MagicMock()
    fake_webkit = MagicMock()
    monkeypatch.setattr(mod, "LAYER_SHELL_AVAILABLE", False)
    monkeypatch.setattr(mod, "Gtk", fake_gtk)
    monkeypatch.setattr(mod, "WebKit", fake_webkit)
    setup_calls: list[Any] = []
    worker = make_worker()
    monkeypatch.setattr(worker, "_setup_layer_shell", lambda w: setup_calls.append(w))
    worker._build_surface()

    assert setup_calls == []
    assert worker._web_view is fake_webkit.WebView.return_value
    # Still a borderless window so the rest of the surface setup is unchanged.
    fake_gtk.Window.return_value.set_decorated.assert_called_once_with(False)


def test_build_surface_lifts_file_access_for_file_origin_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The overlay shell loads from ``file://``; WebKitGTK blocks ES module
    scripts (``<script type="module">``) and the cross-origin ``ws://localhost``
    state WebSocket under ``file://`` unless file-access is lifted. Without
    this the worker reports ``ready`` but the JS never executes -> no clock
    (#739). Both settings must be enabled on the WebView before ``load_uri``.
    """
    import picframe.infrastructure.overlay.overlay_worker as mod

    fake_gtk = MagicMock()
    fake_webkit = MagicMock()
    monkeypatch.setattr(mod, "LAYER_SHELL_AVAILABLE", False)
    monkeypatch.setattr(mod, "Gtk", fake_gtk)
    monkeypatch.setattr(mod, "WebKit", fake_webkit)

    # Capture call order robustly via side effects.
    order: list[str] = []
    settings = MagicMock()
    settings.set_allow_file_access_from_file_urls.side_effect = lambda v: order.append(
        "file_access"
    )
    settings.set_allow_universal_access_from_file_urls.side_effect = lambda v: order.append(
        "universal"
    )
    fake_webkit.WebView.return_value.get_settings.return_value = settings
    fake_webkit.WebView.return_value.load_uri.side_effect = lambda *_: order.append("load_uri")

    worker = make_worker()
    monkeypatch.setattr(worker, "_setup_layer_shell", lambda w: None)
    worker._build_surface()

    settings.set_allow_file_access_from_file_urls.assert_called_once_with(True)
    settings.set_allow_universal_access_from_file_urls.assert_called_once_with(True)
    # Both file-access flags are set before the shell URI loads so they are
    # in effect when the ES module script is first evaluated.
    assert order == ["file_access", "universal", "load_uri"]


def test_display_env_log_precedes_gtk_init_block() -> None:
    """The display-environment log line must run *before* the GTK import/init
    block (mirrors gst_worker.py). If the worker segfaults during
    ``Gtk.init_check()``, this log line is often the only output visible, so it
    must be emitted first. This structural test guards against regressions that
    move it back below the init block.
    """
    import picframe.infrastructure.overlay.overlay_worker as mod

    source = Path(mod.__file__).read_text()
    log_idx = source.find("Overlay worker display environment:")
    gtk_idx = source.find('gi.require_version("Gtk", "4.0")')
    assert log_idx != -1, "display-environment log line not found in worker source"
    assert gtk_idx != -1, "GTK require_version line not found in worker source"
    assert log_idx < gtk_idx, "display-environment log must precede the GTK init block"


def test_apply_transparency_makes_surface_transparent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With ``transparent`` true the window, surface and WebView go transparent."""
    import picframe.infrastructure.overlay.overlay_worker as mod

    fake_gtk = MagicMock()
    fake_gdk = MagicMock()
    monkeypatch.setattr(mod, "WEBKIT_AVAILABLE", True)
    monkeypatch.setattr(mod, "Gtk", fake_gtk)
    monkeypatch.setattr(mod, "Gdk", fake_gdk)
    worker = make_worker()
    worker._config = {"transparent": True}
    window = MagicMock()
    web_view = MagicMock()
    worker._window = window
    worker._web_view = web_view

    worker._apply_transparency()

    fake_gtk.CssProvider.return_value.load_from_data.assert_called_once()
    # GTK4 non-deprecated path: add_provider_for_display (not get_style_context).
    fake_gtk.StyleContext.add_provider_for_display.assert_called_once()
    window.connect.assert_any_call("realize", worker._on_realize_transparent)
    # Gdk.RGBA constructed without deprecated positional args; channels set.
    web_view.set_background_color.assert_called_once()
    assert web_view.set_background_color.call_args[0][0] is fake_gdk.RGBA.return_value


def test_apply_transparency_skipped_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``transparent: false`` leaves the (opaque) surface untouched."""
    import picframe.infrastructure.overlay.overlay_worker as mod

    fake_gtk = MagicMock()
    fake_gdk = MagicMock()
    monkeypatch.setattr(mod, "WEBKIT_AVAILABLE", True)
    monkeypatch.setattr(mod, "Gtk", fake_gtk)
    monkeypatch.setattr(mod, "Gdk", fake_gdk)
    worker = make_worker()
    worker._config = {"transparent": False}
    window = MagicMock()
    web_view = MagicMock()
    worker._window = window
    worker._web_view = web_view

    worker._apply_transparency()

    fake_gtk.CssProvider.assert_not_called()
    web_view.set_background_color.assert_not_called()
    window.connect.assert_not_called()


def test_apply_transparency_noop_in_headless_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No surface / WebKitGTK absent -> nothing applied (keeps IPC testable)."""
    import picframe.infrastructure.overlay.overlay_worker as mod

    monkeypatch.setattr(mod, "WEBKIT_AVAILABLE", False)
    worker = make_worker()
    worker._config = {"transparent": True}
    worker._window = MagicMock()
    worker._web_view = MagicMock()

    # Must not raise and must not touch GTK.
    worker._apply_transparency()


def test_on_realize_transparent_marks_surface_non_opaque() -> None:
    """The realize callback flips the compositor opacity hint when supported."""
    worker = make_worker()
    surface = MagicMock()
    window = MagicMock()
    window.get_surface.return_value = surface

    worker._on_realize_transparent(window)

    surface.set_opaque.assert_called_once_with(False)


def test_on_realize_transparent_skips_surface_without_set_opaque() -> None:
    """A surface lacking ``set_opaque`` (mocked/older API) is handled gracefully."""
    worker = make_worker()
    surface = MagicMock(spec=[])  # no set_opaque attribute
    window = MagicMock()
    window.get_surface.return_value = surface

    # Must not raise.
    worker._on_realize_transparent(window)


def test_build_surface_applies_transparency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_build_surface`` wires transparency into the freshly built surface."""
    import picframe.infrastructure.overlay.overlay_worker as mod

    fake_gtk = MagicMock()
    fake_webkit = MagicMock()
    fake_gdk = MagicMock()
    monkeypatch.setattr(mod, "LAYER_SHELL_AVAILABLE", True)
    monkeypatch.setattr(mod, "WEBKIT_AVAILABLE", True)
    monkeypatch.setattr(mod, "Gtk", fake_gtk)
    monkeypatch.setattr(mod, "WebKit", fake_webkit)
    monkeypatch.setattr(mod, "Gdk", fake_gdk)
    transparency_calls: list[bool] = []
    worker = make_worker()
    monkeypatch.setattr(worker, "_setup_layer_shell", lambda w: None)
    monkeypatch.setattr(worker, "_apply_transparency", lambda: transparency_calls.append(True))
    worker._build_surface()

    assert transparency_calls == [True]
    fake_webkit.WebView.return_value.load_uri.assert_called_once()
