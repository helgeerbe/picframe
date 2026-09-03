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
import urllib.parse
from multiprocessing.connection import Connection, Listener
from pathlib import Path
from typing import Any

from picframe.core.models.overlay import PluginDescriptor
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
from picframe.infrastructure.overlay.plugin_loader import PluginLoader

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

    # GTK4 init. ``Gtk.init()`` takes no argv in GTK4 (unlike GTK3's
    # ``Gtk.init(sys.argv)``); passing ``None`` raises ``TypeError``. Use the
    # same robust ``init_check``-first pattern as ``gtk_video_presenter.py`` so
    # the worker fails gracefully (and logs) instead of crashing when no
    # display/Wayland session is available.
    if hasattr(Gtk, "init_check"):
        try:
            init_result = Gtk.init_check()
        except TypeError:
            init_result = Gtk.init_check([])
        gtk_initialized = (
            bool(init_result[0]) if isinstance(init_result, tuple) else bool(init_result)
        )
        if not gtk_initialized:
            raise RuntimeError("Gtk.init_check returned False (no display available)")
    else:
        try:
            Gtk.init()
        except TypeError:
            Gtk.init([])
    WEBKIT_AVAILABLE = True
except (ImportError, ValueError, RuntimeError) as exc:
    gi = Any
    Gtk = Any
    WebKit = Any
    GLib = Any
    logger.error("WebKitGTK not available. Worker cannot start: %s", exc)
    WEBKIT_AVAILABLE = False

# Optional wlr-layer-shell binding (``gtk4-layer-shell``). When the typelib is
# absent the worker falls back to a plain borderless ``Gtk.Window`` (#739 task
# 8), so this is a graceful degrade rather than a hard requirement. Probed only
# when WebKitGTK itself imported, since both need a running GTK/Wayland session.
LAYER_SHELL_AVAILABLE = False
Gtk4LayerShell: Any = Any
if WEBKIT_AVAILABLE:
    try:
        gi.require_version("Gtk4LayerShell", "1.0")
        from gi.repository import Gtk4LayerShell as _Gtk4LayerShell

        Gtk4LayerShell = _Gtk4LayerShell
        LAYER_SHELL_AVAILABLE = True
    except (ImportError, ValueError):
        logger.info("gtk4-layer-shell not available; using a plain borderless window.")

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
        self._plugin_loader = PluginLoader(plugin_dir)
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
        if self._web_view is not None and WEBKIT_AVAILABLE:
            self._push_config_to_shell()
        else:
            logger.debug("Config applied (no surface in headless mode).")

    def _handle_bridge_message(self, data: dict[str, Any]) -> None:
        """Handle a parsed message from the JS shell bridge (GTK-free, testable).

        Called by the GTK ``user-message-received`` closure so the message
        dispatch stays pure and unit-testable.
        """
        action = str(data.get("action", ""))
        if action in (
            INPUT_ACTION_PREV,
            INPUT_ACTION_NEXT,
            INPUT_ACTION_TOGGLE,
            INPUT_ACTION_HIDE,
        ):
            self.emit_input(action)
        elif action == "__request_config":
            self._push_config_to_shell()

    def _build_shell_config(self) -> dict[str, Any]:
        """Build the config payload pushed to the JS shell.

        Merges the live overlay config (received via ``set_config``) with the
        discovered plugin list (slim descriptors carrying the plugin ``entry``
        as a ``file://`` URI) plus the connection info the shell cannot derive
        from its ``file://`` origin: the picframe WS port and the plugin dir URI.
        """
        config: dict[str, Any] = dict(self._config)
        config["_plugins"] = [self._plugin_payload(p) for p in self._plugin_loader.list_plugins()]
        config["_ws_port"] = self.ws_port
        config["_plugin_uri"] = self._plugin_dir_uri()
        return config

    def _plugin_payload(self, descriptor: PluginDescriptor) -> dict[str, Any]:
        """Slim a ``PluginDescriptor`` to the fields the shell dock needs."""
        entry = Path(descriptor.directory) / descriptor.entry
        return {
            "id": descriptor.id,
            "name": descriptor.name,
            "icon": descriptor.icon,
            "position": descriptor.position,
            "entry_uri": entry.resolve().absolute().as_uri(),
        }

    def _plugin_dir_uri(self) -> str:
        """Return the plugin directory as a ``file://`` URI."""
        return Path(self.plugin_dir).expanduser().resolve().absolute().as_uri()

    def _push_config_to_shell(self) -> None:
        """Push the current shell config to the WebView (no-op in headless mode)."""
        if self._web_view is None or not WEBKIT_AVAILABLE:
            return
        payload = json.dumps(self._build_shell_config())
        # Guard against the shell not having registered applyConfig yet (a race
        # between an early set_config and the page finishing boot).
        js = (
            "if(window.picframe&&window.picframe.applyConfig)"
            f"{{window.picframe.applyConfig({payload});}}"
        )
        self._push_to_shell(js)

    def _push_to_shell(self, js: str) -> None:
        """Run ``js`` in the WebView on the GLib main thread (no-op headless)."""
        if self._web_view is None or not WEBKIT_AVAILABLE or self._loop is None:
            return

        def _run() -> bool:
            try:
                self._web_view.evaluate_javascript(js, -1, None, None, None)
            except Exception as exc:
                logger.error("Failed to push to overlay shell: %s", exc)
            return False

        GLib.idle_add(_run)

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
        """Create the transparent overlay surface + WebKit WebView.

        Uses the ``wlr-layer-shell`` protocol (via ``gtk4-layer-shell``) when the
        typelib is available so the overlay sits above pi3d/video, covers the
        whole output, and stays input-capturing at every opacity (#739 task 8).
        Falls back to a plain borderless ``Gtk.Window`` on compositors without
        layer-shell; the rest of the surface setup is identical.
        """
        self._window = Gtk.Window()
        self._window.set_decorated(False)
        self._window.set_default_size(1920, 1080)
        self._window.connect("close-request", lambda *_: self._shutdown())

        if LAYER_SHELL_AVAILABLE:
            self._setup_layer_shell(self._window)

        self._web_view = WebKit.WebView()
        # The shell connects to the picframe state WebSocket itself; we only
        # load the local file:// entry here.
        self._web_view.load_uri(self._shell_uri())
        self._install_js_bridge()
        self._window.set_child(self._web_view)
        self._window.present()

    def _setup_layer_shell(self, window: Any) -> None:
        """Configure ``window`` as a fullscreen overlay layer surface.

        Kept GTK-free apart from the ``Gtk4LayerShell`` calls (which receive a
        ready window) so the layer wiring can be unit-tested with a mock window
        and a mocked ``Gtk4LayerShell`` module.

        The typelib import can succeed while the backing shared library
        (``libgtk4-layer-shell.so.0``) is absent — GObject-introspection loads
        the ``.so`` lazily on first call, not at import. In that case the first
        ``Gtk4LayerShell.*`` invocation raises ``GLib.GError``. We degrade
        gracefully: log the failure and leave the window as the plain borderless
        ``Gtk.Window`` already constructed by the caller, matching the
        documented fallback (#739 task 8).
        """
        try:
            Gtk4LayerShell.init_for_window(window)
            # OVERLAY is the topmost layer, above normal application windows.
            Gtk4LayerShell.set_layer(window, Gtk4LayerShell.Layer.OVERLAY)
            # Anchor to all four edges so the surface covers the whole output.
            for edge in (
                Gtk4LayerShell.Edge.TOP,
                Gtk4LayerShell.Edge.LEFT,
                Gtk4LayerShell.Edge.RIGHT,
                Gtk4LayerShell.Edge.BOTTOM,
            ):
                Gtk4LayerShell.set_anchor(window, edge, True)
            # -1 = do not reserve exclusive space; the overlay floats on top.
            Gtk4LayerShell.set_exclusive_zone(window, -1)
            # Receive keyboard when the surface has focus without globally stealing
            # it (Escape/arrows still work after a tap focuses the surface).
            Gtk4LayerShell.set_keyboard_mode(window, Gtk4LayerShell.KeyboardMode.ON_DEMAND)
        except Exception as exc:  # noqa: BLE001 - graceful degrade, see docstring
            global LAYER_SHELL_AVAILABLE
            LAYER_SHELL_AVAILABLE = False
            logger.warning(
                "gtk4-layer-shell runtime call failed (libgtk4-layer-shell.so.0 "
                "missing or incompatible); falling back to a plain borderless "
                "window. Detail: %s",
                exc,
            )

    def _shell_uri(self) -> str:
        """Return the ``file://`` URI of the overlay shell, with query params.

        The shell cannot derive the picframe WS port or the plugin dir from its
        ``file://`` origin, so the worker appends ``?ws=<port>&plugins=<uri>``.

        The frontend overlay build (``vite.overlay.config.ts``) emits the shell
        to ``<html>/overlay/overlay.html``. Older layouts used
        ``<html>/overlay/index.html`` or ``<html>/overlay.html``; those are kept
        as fallbacks so the worker is robust to either layout.
        """
        candidates = (
            Path(self.html_dir) / "overlay" / "overlay.html",
            Path(self.html_dir) / "overlay" / "index.html",
            Path(self.html_dir) / "overlay.html",
        )
        path = next((c for c in candidates if c.is_file()), candidates[0])
        base = path.resolve().absolute().as_uri()
        params = urllib.parse.urlencode({"ws": self.ws_port, "plugins": self._plugin_dir_uri()})
        return f"{base}?{params}"

    def _install_js_bridge(self) -> None:
        """Inject ``window.picframe`` for shell<->worker bidirectional calls."""
        manager = self._web_view.get_user_content_manager()

        def _bridge_call(_web_view: Any, result: Any) -> None:
            try:
                args = result.get_js_value().to_string()
                data = json.loads(args) if args else {}
            except (json.JSONDecodeError, ValueError):
                return
            if isinstance(data, dict):
                self._handle_bridge_message(data)

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
