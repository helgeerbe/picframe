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

# Log display-related environment variables *before* the GTK import/init block
# (mirrors gst_worker.py). The worker may segfault during ``Gtk.init_check()``
# before any surface code runs, so this log line is often the only output
# visible when that happens; it shows which Wayland display the worker tried.
logger.info(
    "Overlay worker display environment: "
    "WAYLAND_DISPLAY=%s DISPLAY=%s XDG_RUNTIME_DIR=%s GDK_BACKEND=%s",
    os.environ.get("WAYLAND_DISPLAY", ""),
    os.environ.get("DISPLAY", ""),
    os.environ.get("XDG_RUNTIME_DIR", ""),
    os.environ.get("GDK_BACKEND", ""),
)

try:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("WebKit", "6.0")
    gi.require_version("Gdk", "4.0")
    from gi.repository import Gdk, GLib, Gtk, WebKit

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
    Gdk = Any
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
        if action == "__console":
            # Forwarded JS console / uncaught-error messages from the injected
            # diagnostic script (#739). WebKitGTK does not surface page console
            # output to the embedding process, so the shell installs a forwarder
            # that posts each line here; logging it makes a silently-blocked or
            # runtime-failing shell visible in the journal.
            level = str(data.get("level", "log")).upper()
            text = str(data.get("text", ""))
            logfn = {
                "ERROR": logger.error,
                "WARN": logger.warning,
                "WARNING": logger.warning,
                "INFO": logger.info,
                "DEBUG": logger.debug,
                "LOG": logger.info,
            }.get(level, logger.info)
            logfn("[overlay-js] %s", text)
            return
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
        # The overlay shell loads from a ``file://`` URI. WebKitGTK treats ES
        # module scripts (``<script type="module">``, which Vite emits) as
        # CORS-requiring and silently blocks them under ``file://``; it also
        # blocks the cross-origin ``ws://localhost`` state WebSocket the shell
        # opens for live media/state. Lift both file-access restrictions so
        # the Vite-built shell boots and connects (#739). Without this the
        # worker reports ``ready`` but the JS never executes -> no clock.
        settings = self._web_view.get_settings()
        settings.set_allow_file_access_from_file_urls(True)
        settings.set_allow_universal_access_from_file_urls(True)
        # Surface load diagnostics: forward WebKit load state + JS console to
        # the worker logger so a blocked/failed shell is visible in the journal
        # instead of silently swallowed (#739). Under ``file://`` WebKitGTK can
        # drop an ES module script without any console error surfacing to the
        # embedding process; connecting these *before* ``load_uri`` ensures the
        # signals fire for this load.
        shell_uri = self._shell_uri()
        logger.info("Overlay shell load URI: %s", shell_uri)
        self._log_shell_html_resolution()
        self._web_view.connect("load-changed", self._on_load_changed)
        self._web_view.connect("load-failed", self._on_load_failed)
        # The shell connects to the picframe state WebSocket itself; we only
        # load the local file:// entry here.
        self._web_view.load_uri(shell_uri)
        self._install_js_bridge()
        self._window.set_child(self._web_view)
        self._apply_transparency()
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

    def _apply_transparency(self) -> None:
        """Make the overlay surface transparent so pi3d/video shows through.

        WebKitGTK defaults to an opaque white surface, so without this the clock
        (white text) renders invisible and the overlay hides the photo beneath
        (see ``docs/dev/architecture/overlay.md`` §1 and the
        ``overlay.transparent`` config). The window background, the WebKit
        background, and the Wayland surface opacity hint are all set
        transparent. Gated by ``overlay.transparent`` (default ``true``).

        Applied once at surface build time (before the first ``set_config`` IPC
        arrives) using the config default, so a ``transparent: false`` override
        takes effect on the next service restart. No-op in headless mode (no
        surface / WebKitGTK absent) so the GTK-free IPC plumbing stays
        unit-testable.
        """
        if self._window is None or self._web_view is None or not WEBKIT_AVAILABLE:
            return
        if not bool(self._config.get("transparent", True)):
            return
        # Transparent window background via a CSS provider. Use the GTK4
        # non-deprecated ``add_provider_for_display`` (the per-widget
        # ``get_style_context().add_provider()`` path is deprecated in GTK4).
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(
            b"window { background-color: transparent; }"
            b" window decoration { background-color: transparent; box-shadow: none; }"
        )
        display = self._window.get_display()
        if display is not None:
            Gtk.StyleContext.add_provider_for_display(
                display, css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
        # The compositor blends the surface with what is below only when it
        # knows the surface is not opaque. ``set_opaque(False)`` must run after
        # the GdkSurface exists (window realized, which happens during
        # ``present()``), so connect the handler before presenting.
        self._window.connect("realize", self._on_realize_transparent)
        # WebKit WebView transparent background (overrides its default white).
        # Construct ``Gdk.RGBA`` without positional args (passing them is
        # deprecated in newer PyGObject and the args are ignored); set the
        # channel fields explicitly for a fully transparent black.
        bg = Gdk.RGBA()
        bg.red = 0.0
        bg.green = 0.0
        bg.blue = 0.0
        bg.alpha = 0.0
        self._web_view.set_background_color(bg)

    def _on_realize_transparent(self, window: Any) -> None:
        """Mark the realized Wayland surface as non-opaque for alpha blending."""
        surface = window.get_surface()
        if surface is not None and hasattr(surface, "set_opaque"):
            surface.set_opaque(False)

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

    def _log_shell_html_resolution(self) -> None:
        """Log which overlay shell HTML file (if any) was found on disk.

        A missing HTML file is the most common packaging fault (frontend build
        not run, wrong ``html_dir``); without this check the WebView just shows
        WebKit's "not found" page and there is no clock. Logging the resolved
        path (or the absence of one) makes that failure mode obvious in the
        journal (#739).
        """
        candidates = (
            Path(self.html_dir) / "overlay" / "overlay.html",
            Path(self.html_dir) / "overlay" / "index.html",
            Path(self.html_dir) / "overlay.html",
        )
        found = next((c for c in candidates if c.is_file()), None)
        if found is None:
            logger.error(
                "Overlay shell HTML not found under %s; searched overlay/overlay.html, "
                "overlay/index.html, overlay.html. The WebView will load a not-found page "
                "(no clock).",
                self.html_dir,
            )
        else:
            logger.info("Overlay shell HTML resolved: %s", found)

    def _on_load_changed(self, _web_view: Any, load_event: Any) -> None:
        """Log WebKit load progress; inject JS console forwarding on commit.

        WebKitGTK does not surface page ``console.*`` or uncaught errors to the
        embedding process, so a shell whose ES module script is silently
        blocked under ``file://`` leaves *no* trace in the journal (#739). At
        ``COMMITTED`` (the document exists but deferred module scripts have not
        yet run) we inject a classic-script override of ``console`` plus
        ``window.onerror`` / ``unhandledrejection`` that forwards each message
        to the registered ``picframe`` message handler, which
        :meth:`_handle_bridge_message` logs. The injected script runs in the
        page's main world via ``evaluate_javascript`` and so executes even when
        the Vite ES module bundle itself is CORS-blocked.
        """
        name = _load_event_name(load_event)
        logger.info("Overlay WebView load state: %s", name)
        if name == "COMMITTED":
            self._inject_console_forwarding()

    def _on_load_failed(self, _web_view: Any, load_event: Any, error: Any) -> None:
        """Log a failed overlay load (e.g. a missing ``file://`` resource)."""
        try:
            msg = error.message if hasattr(error, "message") else str(error)
        except Exception:  # noqa: BLE001 - never let logging raise
            msg = str(error)
        logger.error("Overlay WebView load FAILED (%s): %s", _load_event_name(load_event), msg)

    def _inject_console_forwarding(self) -> None:
        """Inject a main-world classic script that forwards console + errors.

        Reuses :meth:`_push_to_shell` (GLib main-thread ``evaluate_javascript``)
        so it runs in the page's main world independent of the module-script
        CORS state. Idempotent (guards with ``window.__pfConsoleFwd``) so a
        ``reload`` does not stack handlers.
        """
        if self._web_view is None or not WEBKIT_AVAILABLE:
            return
        js = (
            "(function(){"
            "if(window.__pfConsoleFwd){return;}"
            "window.__pfConsoleFwd=true;"
            "var send=function(level,args){"
            "try{var t=Array.prototype.map.call(args,function(a){"
            "try{return typeof a==='object'?JSON.stringify(a):String(a);}"
            "catch(e){return String(a);}}).join(' ');"
            "window.webkit.messageHandlers.picframe.postMessage("
            "JSON.stringify({action:'__console',level:level,text:t}));}"
            "catch(e){}};"
            "['log','info','warn','error','debug'].forEach(function(m){"
            "var o=console[m]?console[m].bind(console):function(){};"
            "console[m]=function(){send(m,arguments);"
            "try{o.apply(console,arguments);}catch(e){}};});"
            "window.addEventListener('error',function(e){"
            "send('error',['window.onerror: '+(e.message||'')+' @ '"
            "+(e.filename||'')+':'+(e.lineno||0)+':'+(e.colno||0)"
            "+(e.error&&e.error.stack?(' '+e.error.stack):'')]);});"
            "window.addEventListener('unhandledrejection',function(e){"
            "var r=e.reason;send('error',['unhandledrejection: '"
            "+(r&&r.stack?r.stack:String(r))]);});"
            "})();"
        )
        self._push_to_shell(js)

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


def _load_event_name(load_event: Any) -> str:
    """Return a human-readable name for a ``WebKit.LoadEvent`` value.

    Tolerates the unavailable-WebKit case (``WebKit`` is the ``typing.Any``
    placeholder) and mock values in unit tests by falling back to ``str()``.
    """
    try:
        le = WebKit.LoadEvent
        if load_event == le.STARTED:
            return "STARTED"
        if load_event == le.COMMITTED:
            return "COMMITTED"
        if load_event == le.FINISHED:
            return "FINISHED"
    except Exception:  # noqa: BLE001 - fallback below
        pass
    return str(load_event)


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
