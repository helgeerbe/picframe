"""Out-of-process WebKitGTK overlay worker (#739).

Runs in its own subprocess (spawned via :func:`subprocess.Popen` by
:class:`WebKitOverlayRenderer`) so a WebKitGTK crash/leak never takes down the
frame - the same isolation non-negotiable that applies to the GStreamer worker
(:mod:`picframe.core.renderers.gst_worker`).

Communication with the main process is JSON over a Unix-domain socket:

* Commands (main -> worker): ``set_opacity``, ``set_config``, ``reload``,
  ``shutdown``.
* Events (worker -> main): ``ready``, ``input``, ``error``.

The WebKitGTK/GTK setup needs a real Wayland display, so it is isolated behind
:meth:`OverlayWorker.run` which is only invoked from ``main()``. The IPC plumbing
(``handle_command`` / ``_serve``) is GTK-free so it can be unit-tested headless.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from multiprocessing.connection import Connection, Listener
from typing import Any

from picframe.core.renderers.overlay_ipc import (
    INPUT_ACTION_HIDE,
    INPUT_ACTION_NEXT,
    INPUT_ACTION_PREV,
    INPUT_ACTION_TOGGLE,
    InputEvent,
    OverlayErrorEvent,
    OverlayIpcMessage,
    ReadyEvent,
    ReloadCommand,
    SetConfigCommand,
    SetOpacityCommand,
    ShutdownCommand,
    parse_overlay_ipc_message,
)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("overlay_worker")

try:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("WebKit", "6.0")
    from gi.repository import GLib, Gtk, WebKit

    Gtk.init(None)
    WEBKIT_AVAILABLE = True
except (ImportError, ValueError) as exc:
    gi = Any
    Gtk = Any
    WebKit = Any
    GLib = Any
    logger.error("WebKitGTK not available. Worker cannot start: %s", exc)
    WEBKIT_AVAILABLE = False

logger.info(
    "Overlay worker display environment: "
    "WAYLAND_DISPLAY=%s DISPLAY=%s XDG_RUNTIME_DIR=%s GDK_BACKEND=%s",
    os.environ.get("WAYLAND_DISPLAY", ""),
    os.environ.get("DISPLAY", ""),
    os.environ.get("XDG_RUNTIME_DIR", ""),
    os.environ.get("GDK_BACKEND", ""),
)


class OverlayWorker:
    """IPC server for the WebKitGTK overlay subprocess.

    The GTK/WebKit surface is created lazily by :meth:`run`; the IPC plumbing in
    this class is GTK-free so it can be unit-tested headless.
    """

    def __init__(self, socket_path: str, html_dir: str, plugin_dir: str, ws_port: int) -> None:
        self.socket_path = socket_path
        self.html_dir = html_dir
        self.plugin_dir = plugin_dir
        self.ws_port = ws_port
        self._opacity = 1.0
        self._config: dict[str, Any] = {}
        self._listener: Listener | None = None
        self._conn: Connection | None = None
        self._loop: Any = None
        self._web_view: Any = None
        self._window: Any = None

    # --- IPC plumbing (GTK-free, unit-tested) ---

    def handle_command(self, command: OverlayIpcMessage) -> bool:
        """Apply an IPC command. Return ``False`` to request shutdown."""
        if isinstance(command, SetOpacityCommand):
            self._opacity = max(0.0, min(1.0, command.opacity))
            self._apply_opacity()
        elif isinstance(command, SetConfigCommand):
            self._config = dict(command.config)
            self._apply_config()
        elif isinstance(command, ReloadCommand):
            self._apply_config()
        elif isinstance(command, ShutdownCommand):
            return False
        return True

    def _apply_opacity(self) -> None:
        """Apply the current opacity to the GTK surface when it exists.

        In headless/test mode (no surface, or WebKitGTK absent) this is a no-op,
        which keeps the GTK-free IPC plumbing unit-testable. In GTK mode the
        window stays present and input-capturing at every opacity - "hide" is
        opacity 0, never withdrawn (see the video + overlay stacking decision).
        """
        if self._window is not None and WEBKIT_AVAILABLE:
            self._window.set_opacity(self._opacity)
        else:
            logger.debug("Opacity set to %.3f (no surface in headless mode).", self._opacity)

    def _apply_config(self) -> None:
        """Apply the current config to the shell (the JS shell reads /ws/state)."""
        logger.debug("Config applied (no surface in headless mode).")

    def emit_input(self, action: str) -> None:
        """Send an input event to the main process."""
        self._send_event(InputEvent(action=action))

    def _send_event(self, event: OverlayIpcMessage) -> None:
        if self._conn is not None:
            try:
                self._conn.send(event.to_json())
            except Exception as exc:
                logger.error("Failed to send overlay IPC event: %s", exc)

    def _serve(self, conn: Connection) -> None:
        """Read commands from ``conn`` until shutdown or the socket closes."""
        self._conn = conn
        self._send_event(ReadyEvent())
        keep_running = True
        while keep_running:
            try:
                if not conn.poll(1.0):
                    continue
                raw = conn.recv()
            except EOFError:
                logger.info("Main process closed the overlay IPC connection.")
                break
            except Exception as exc:
                logger.error("Error reading overlay IPC command: %s", exc)
                break
            if isinstance(raw, str):
                command = parse_overlay_ipc_message(raw)
            else:
                command = raw if isinstance(raw, OverlayIpcMessage) else None
            if command is None:
                continue
            try:
                keep_running = self.handle_command(command)
            except Exception as exc:
                self._send_event(OverlayErrorEvent(details=str(exc)))

    # --- GTK/WebKit surface (needs a Wayland display) ---

    def run(self) -> None:
        """Create the WebKitGTK surface and serve IPC until shutdown."""
        if not WEBKIT_AVAILABLE:
            self._send_error_to_listener(
                "WebKitGTK is not installed; overlay worker cannot start.",
                code="webkit_unavailable",
            )
            return
        self._loop = GLib.MainLoop()
        self._build_surface()
        self._start_listener_async()
        self._loop.run()

    def _build_surface(self) -> None:
        """Create the transparent borderless Wayland window + WebKit WebView."""
        self._window = Gtk.Window()
        self._window.set_decorated(False)
        self._window.set_default_size(1920, 1080)
        self._window.connect("close-request", lambda *_: self._shutdown())

        self._web_view = WebKit.WebView()
        # The shell connects to the picframe state WebSocket itself; we only
        # load the local file:// entry here.
        self._web_view.load_uri(self._shell_uri())
        self._install_js_bridge()
        self._window.set_child(self._web_view)
        self._window.present()

    def _shell_uri(self) -> str:
        from pathlib import Path

        path = Path(self.html_dir) / "overlay" / "index.html"
        if not path.is_file():
            path = Path(self.html_dir) / "overlay.html"
        return path.resolve().absolute().as_uri()

    def _install_js_bridge(self) -> None:
        """Inject ``window.picframe`` for shell<->worker bidirectional calls."""
        manager = self._web_view.get_user_content_manager()

        def _bridge_call(_web_view: Any, result: Any) -> None:
            try:
                args = result.get_js_value().to_string()
                data = json.loads(args) if args else {}
            except (json.JSONDecodeError, ValueError):
                return
            action = str(data.get("action", ""))
            if action in (
                INPUT_ACTION_PREV,
                INPUT_ACTION_NEXT,
                INPUT_ACTION_TOGGLE,
                INPUT_ACTION_HIDE,
            ):
                self.emit_input(action)

        manager.register_script_message_handler("picframe")
        self._web_view.connect("user-message-received", _bridge_call)
        self._web_view.evaluate_javascript(
            "window.picframe = { send: (a) => "
            "webkit.messageHandlers.picframe.postMessage(JSON.stringify(a)) };",
            -1,
            None,
            None,
            None,
        )

    def _start_listener_async(self) -> None:
        """Accept the main process connection on a GLib idle callback."""
        if os.path.exists(self.socket_path):
            try:
                os.remove(self.socket_path)
            except OSError:
                pass
        listener = Listener(self.socket_path, family="AF_UNIX")
        self._listener = listener

        def _accept(*_args: Any) -> bool:
            conn = listener.accept()
            GLib.idle_add(lambda: self._serve_in_loop(conn))
            return False

        GLib.idle_add(_accept)

    def _serve_in_loop(self, conn: Connection) -> bool:
        """Drive the blocking IPC serve loop off the GLib main loop."""
        import threading

        thread = threading.Thread(target=self._serve, args=(conn,), daemon=True)
        thread.start()
        return False

    def _send_error_to_listener(self, details: str, code: str | None = None) -> None:
        """Publish an error without a running GLib loop (init-failure path)."""
        if os.path.exists(self.socket_path):
            try:
                os.remove(self.socket_path)
            except OSError:
                pass
        try:
            listener = Listener(self.socket_path, family="AF_UNIX")
            conn = listener.accept()
            conn.send(OverlayErrorEvent(details=details, code=code).to_json())
            conn.close()
            listener.close()
        except Exception as exc:
            logger.error("Could not report overlay init error: %s", exc)

    def _shutdown(self) -> None:
        if self._loop is not None:
            self._loop.quit()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the worker CLI arguments."""
    parser = argparse.ArgumentParser(description="Picframe WebKitGTK overlay worker")
    parser.add_argument("--socket", required=True, help="Unix-domain IPC socket path")
    parser.add_argument("--html-dir", required=True, help="Overlay shell HTML directory")
    parser.add_argument("--plugin-dir", required=True, help="Overlay plugins directory")
    parser.add_argument("--ws-port", type=int, default=9000, help="picframe state WebSocket port")
    return parser.parse_args(argv)


def main() -> None:
    """Worker entry point."""
    args = parse_args()
    worker = OverlayWorker(
        socket_path=args.socket,
        html_dir=args.html_dir,
        plugin_dir=args.plugin_dir,
        ws_port=args.ws_port,
    )
    worker.run()


if __name__ == "__main__":
    main()
