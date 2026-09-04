"""WebKitGTK overlay renderer — IPC client for the out-of-process worker (#739).

This is the production :class:`IOverlayController` implementation. It mirrors
:class:`GstVideoRenderer`: the main process stays GTK/WebKit-free, and the
heavy browser engine runs in its own subprocess (``overlay_worker.py``)
spawned via :func:`subprocess.Popen`. Communication is newline-delimited JSON
over a Unix-domain socket.

The renderer is the event-bus bridge for the overlay:

* It forwards live config (``OverlayConfigChangedEvent``) to the worker.
* It drives opacity from video reveal render actions (``RenderCommand``):
  ``PROMOTE_VIDEO_REVEAL`` -> opacity 0 (video shows through), ``PARK``/``WAKE``
  -> opacity 1, so the overlay stays present + input-capturing, never withdrawn.
* It republishes worker input events (``InputEvent``) as ``CommandEvent``s so
  the playback engine reacts to touch/keyboard navigation from the overlay.

Graceful degradation: if WebKitGTK is not importable, :meth:`is_available`
returns ``False`` and :meth:`start` publishes a
``SystemErrorEvent(code="webkit_unavailable")`` instead of spawning the worker,
so picframe runs unchanged without the overlay.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from multiprocessing.connection import Client, Connection
from pathlib import Path
from typing import Any

from picframe.core.events.dto import (
    RENDER_PARK_VIDEO_REVEAL,
    RENDER_PROMOTE_VIDEO_REVEAL,
    RENDER_WAKE_VIDEO_REVEAL,
    Command,
    CommandEvent,
    OverlayConfigChangedEvent,
    RenderCommand,
    SystemErrorEvent,
)
from picframe.core.events.interfaces import IEventPublisher, IEventSubscriber
from picframe.core.models.overlay import PluginDescriptor
from picframe.core.ports.overlay import IOverlayController
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

logger = logging.getLogger(__name__)

_WEBKIT_UNAVAILABLE_CODE = "webkit_unavailable"
_WORKER_SOCKET_TIMEOUT_SECONDS = 20.0
_WORKER_SOCKET_POLL_SECONDS = 0.1

# Probe priority for the WebKitGTK typelib. ``WebKit`` 6.x targets GTK4; the
# 4.1 series targets GTK3 but is still common on Raspberry Pi OS. We accept
# whichever imports first.
_WEBKIT_PROBE_VERSIONS = (("WebKit", "6.0"), ("WebKit2", "4.1"))

# The gtk4-layer-shell runtime .so must be loaded *before* libwayland-client or
# ``Gtk4LayerShell.init_for_window()`` returns without raising but never
# actually creates a layer surface (the window then renders invisibly behind
# pi3d). The official workaround is ``LD_PRELOAD`` (see gtk4-layer-shell's
# linking.md). We resolve the .so once at spawn time.
_LAYER_SHELL_SONAME = "libgtk4-layer-shell.so.0"
_LAYER_SHELL_SEARCH_DIRS = (
    "/usr/lib/aarch64-linux-gnu",
    "/usr/lib/arm-linux-gnueabihf",
    "/usr/lib/x86_64-linux-gnu",
    "/usr/lib",
    "/usr/local/lib",
)


def _resolve_layer_shell_so() -> str | None:
    """Return the absolute path to the gtk4-layer-shell runtime ``.so``.

    Prefers the path reported by ``ldconfig -p`` (the canonical resolution), and
    falls back to globbing the common multiarch library directories. Returns
    ``None`` when the library is not installed, which keeps the worker env a
    no-op on dev boxes / OSes without the package (the plain-window graceful
    degrade still applies).
    """
    try:
        result = subprocess.run(
            ["ldconfig", "-p"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5.0,
        )
    except (OSError, subprocess.SubprocessError):
        result = None
    if result is not None and result.returncode == 0:
        for line in result.stdout.splitlines():
            # ldconfig lines look like: "\tlibgtk4-layer-shell.so.0 (libc6,AArch64) => /path"
            if _LAYER_SHELL_SONAME in line and "=>" in line:
                path = line.rsplit("=>", 1)[1].strip()
                if path and os.path.exists(path):
                    return path
    for directory in _LAYER_SHELL_SEARCH_DIRS:
        candidate = os.path.join(directory, _LAYER_SHELL_SONAME)
        if os.path.exists(candidate):
            try:
                return os.path.realpath(candidate)
            except OSError:
                return candidate
    return None


def _layer_shell_typelib_present() -> bool:
    """Return ``True`` when the gtk4-layer-shell *typelib* is importable.

    GObject-introspection loads the backing ``.so`` lazily on first call, not
    at import, so this can be ``True`` while the runtime
    ``libgtk4-layer-shell.so.0`` is absent — the exact mismatch that makes the
    overlay render invisibly behind pi3d. Safe to call from the main process
    (it does not dlopen the ``.so``), mirroring :func:`_probe_webkit`.
    """
    try:
        import gi

        gi.require_version("Gtk4LayerShell", "1.0")
        return True
    except (ImportError, ValueError):
        return False


class WebKitOverlayRenderer(IOverlayController):
    """Out-of-process WebKitGTK overlay controller (IPC client)."""

    def __init__(
        self,
        event_publisher: IEventPublisher,
        event_subscriber: IEventSubscriber,
        plugin_loader: PluginLoader,
        html_dir: str,
        plugin_dir: str,
        ws_port: int = 9000,
        overlay_config: dict[str, Any] | None = None,
    ) -> None:
        self._publisher = event_publisher
        self._subscriber = event_subscriber
        self._plugin_loader = plugin_loader
        self._html_dir = html_dir
        self._plugin_dir = plugin_dir
        self._ws_port = ws_port
        self._overlay_config = overlay_config or {}

        self._socket_path = f"/tmp/picframe_overlay_{os.getpid()}.sock"
        self._worker_process: subprocess.Popen[str] | None = None
        self._conn: Connection | None = None
        self._running = False
        self._listener_thread: threading.Thread | None = None
        self._subscribed = False
        self._availability: bool | None = None

    # --- IOverlayController ---

    def list_plugins(self) -> list[PluginDescriptor]:
        """Return discovered plugin descriptors (delegated to the loader)."""
        return self._plugin_loader.list_plugins()

    def is_available(self) -> bool:
        """Return ``True`` when the WebKitGTK backend is importable."""
        if self._availability is None:
            self._availability = _probe_webkit()
        return self._availability

    def start(self) -> None:
        """Start the overlay worker subprocess and subscribe to events."""
        if self._running:
            return
        if not self.is_available():
            logger.warning("WebKitGTK is not available; overlay disabled.")
            self._publisher.publish(
                SystemErrorEvent(
                    message="WebKitGTK is not installed; touch overlay is unavailable.",
                    component="WebKitOverlayRenderer",
                    code=_WEBKIT_UNAVAILABLE_CODE,
                )
            )
            return
        self._start_worker()
        if not self._running:
            return
        self._subscribe_events()
        # Apply the initial config so the shell boots with the right
        # enabled/visible set + display mode + plugin config.
        self._send_command(SetConfigCommand(config=dict(self._overlay_config)))

    def stop(self) -> None:
        """Stop the worker subprocess and unsubscribe from events."""
        self._unsubscribe_events()
        self._cleanup()

    def set_opacity(self, opacity: float) -> None:
        """Set the overlay surface opacity (0.0 = transparent, 1.0 = opaque)."""
        self._send_command(SetOpacityCommand(opacity=float(opacity)))

    def reload(self) -> None:
        """Reload the overlay shell / re-scan plugins after a change."""
        self._send_command(ReloadCommand())

    # --- Worker lifecycle ---

    def _start_worker(self) -> None:
        """Spawn the overlay worker subprocess and establish the IPC socket."""
        worker_script = (
            Path(__file__).parent.parent.parent / "infrastructure" / "overlay" / "overlay_worker.py"
        )
        env = self._worker_environment()
        try:
            self._worker_process = subprocess.Popen(
                [
                    sys.executable,
                    str(worker_script),
                    "--socket",
                    self._socket_path,
                    "--html-dir",
                    str(self._html_dir),
                    "--plugin-dir",
                    str(self._plugin_dir),
                    "--ws-port",
                    str(self._ws_port),
                ],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            self._start_worker_log_reader()

            assert self._worker_process is not None
            deadline = time.monotonic() + _WORKER_SOCKET_TIMEOUT_SECONDS
            while time.monotonic() < deadline and not os.path.exists(self._socket_path):
                return_code = self._worker_process.poll()
                if return_code is not None:
                    raise RuntimeError(
                        f"Overlay worker exited before creating IPC socket "
                        f"(exit code {return_code}).{self._worker_log_summary()}"
                    )
                time.sleep(_WORKER_SOCKET_POLL_SECONDS)

            if not os.path.exists(self._socket_path):
                raise RuntimeError(
                    f"Overlay worker failed to create IPC socket within "
                    f"{_WORKER_SOCKET_TIMEOUT_SECONDS:.0f} seconds."
                    f"{self._worker_log_summary()}"
                )

            self._conn = Client(self._socket_path, family="AF_UNIX")
            self._running = True
            self._listener_thread = threading.Thread(target=self._listen_for_events, daemon=True)
            self._listener_thread.start()
            logger.info("Successfully connected to overlay worker subprocess.")
        except Exception as e:
            logger.error("Failed to start overlay worker: %s", e)
            self._publisher.publish(
                SystemErrorEvent(
                    message=f"Failed to start overlay worker: {e}",
                    component="WebKitOverlayRenderer",
                    code=_WEBKIT_UNAVAILABLE_CODE,
                )
            )
            self._cleanup()

    def _worker_environment(self) -> dict[str, str]:
        """Return the environment for the overlay worker process.

        Enforce ``GDK_BACKEND=wayland`` so GTK4/WebKitGTK always uses native
        Wayland (X11 is not a supported target - see .clinerules). When the
        gtk4-layer-shell runtime ``.so`` is installed, preload it so the library
        links before ``libwayland-client``; otherwise
        ``Gtk4LayerShell.init_for_window()`` silently fails to create a layer
        surface (the window renders invisibly behind pi3d). See
        gtk4-layer-shell's linking.md for the rationale.
        """
        env = os.environ.copy()
        env["GDK_BACKEND"] = "wayland"
        layer_shell_so = _resolve_layer_shell_so()
        if layer_shell_so:
            existing = env.get("LD_PRELOAD", "")
            env["LD_PRELOAD"] = f"{layer_shell_so}:{existing}" if existing else layer_shell_so
            logger.info("Preloading gtk4-layer-shell for overlay worker: %s", layer_shell_so)
        elif _layer_shell_typelib_present():
            # The typelib is installed but its backing runtime .so is missing:
            # ``init_for_window`` will fail to dlopen it and the layer surface
            # never renders on top of pi3d, so the clock stays invisible. This
            # is the common "no clock, photos fine" failure mode — surface it at
            # the default (WARNING) log level instead of only as a worker-side
            # GTK warning buried in INFO-piped output.
            logger.warning(
                "gtk4-layer-shell typelib is installed but the runtime "
                "libgtk4-layer-shell.so.0 could not be resolved; the overlay "
                "surface will render behind pi3d and be invisible. Install the "
                "runtime package, e.g.: sudo apt install libgtk4-layer-shell0"
            )
        return env

    def _start_worker_log_reader(self) -> None:
        if self._worker_process is None or self._worker_process.stdout is None:
            return
        thread = threading.Thread(
            target=self._log_worker_output, args=(self._worker_process.stdout,), daemon=True
        )
        thread.start()

    def _log_worker_output(self, stream: Any) -> None:
        for raw_line in stream:
            line = str(raw_line).rstrip()
            if line:
                logger.info("Overlay worker: %s", line)

    def _worker_log_summary(self) -> str:
        return ""

    def _listen_for_events(self) -> None:
        """Background thread: listen for events from the worker."""
        while self._running and self._conn:
            try:
                if self._conn.poll(1.0):
                    msg_json = self._conn.recv()
                    msg = parse_overlay_ipc_message(msg_json)
                    if msg:
                        self._handle_event(msg)
            except EOFError:
                logger.warning("Overlay IPC connection closed by worker.")
                self._running = False
                break
            except Exception as e:
                logger.error("Error reading overlay IPC event: %s", e)

    def _handle_event(self, event: OverlayIpcMessage) -> None:
        """Translate worker IPC events into domain events."""
        if isinstance(event, ReadyEvent):
            logger.info("Overlay worker reported ready.")
        elif isinstance(event, InputEvent):
            command = _command_for_input_action(event.action)
            if command is not None:
                self._publisher.publish(CommandEvent(command=command))
        elif isinstance(event, OverlayErrorEvent):
            logger.error("Overlay worker error: %s", event.details)
            self._publisher.publish(
                SystemErrorEvent(
                    message=event.details,
                    component="WebKitOverlayRenderer",
                    code=event.code,
                )
            )

    def _send_command(self, cmd: OverlayIpcMessage) -> None:
        """Send a command to the worker."""
        if self._conn:
            try:
                self._conn.send(cmd.to_json())
            except Exception as e:
                logger.error("Failed to send overlay IPC command: %s", e)

    # --- Event subscriptions ---

    def _subscribe_events(self) -> None:
        self._subscriber.subscribe(OverlayConfigChangedEvent, self._on_overlay_config_changed)
        self._subscriber.subscribe(RenderCommand, self._on_render_command)
        self._subscribed = True

    def _unsubscribe_events(self) -> None:
        if self._subscribed:
            self._subscriber.unsubscribe(OverlayConfigChangedEvent, self._on_overlay_config_changed)
            self._subscriber.unsubscribe(RenderCommand, self._on_render_command)
            self._subscribed = False

    def _on_overlay_config_changed(self, event: OverlayConfigChangedEvent) -> None:
        """Forward a live overlay config change to the worker."""
        self._overlay_config = dict(event.overlay_config)
        self._send_command(SetConfigCommand(config=dict(event.overlay_config)))

    def _on_render_command(self, event: RenderCommand) -> None:
        """Drive overlay opacity from video reveal render actions.

        On video promotion the overlay fades to opacity 0 (video shows through)
        but keeps capturing input; on park/wake it returns to opacity 1. The
        overlay is never withdrawn - it stays present and input-capturing.
        """
        action = event.render_action
        if action == RENDER_PROMOTE_VIDEO_REVEAL:
            self.set_opacity(0.0)
        elif action in (RENDER_PARK_VIDEO_REVEAL, RENDER_WAKE_VIDEO_REVEAL):
            self.set_opacity(1.0)

    # --- Cleanup ---

    def _cleanup(self) -> None:
        self._running = False
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
        if self._worker_process:
            self._send_command(ShutdownCommand())
            try:
                self._worker_process.terminate()
                self._worker_process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                self._worker_process.kill()
            except Exception:
                pass
        if os.path.exists(self._socket_path):
            try:
                os.remove(self._socket_path)
            except Exception:
                pass

    def __del__(self) -> None:
        try:
            self._cleanup()
        except Exception:
            pass


def _command_for_input_action(action: str) -> Command | None:
    """Map an overlay input action to a playback Command."""
    if action == INPUT_ACTION_PREV:
        return Command.PREV
    if action == INPUT_ACTION_NEXT:
        return Command.NEXT
    if action == INPUT_ACTION_TOGGLE:
        return Command.PLAY
    if action == INPUT_ACTION_HIDE:
        return Command.STOP
    return None


def _probe_webkit() -> bool:
    """Return ``True`` when a WebKitGTK typelib can be imported."""
    try:
        import gi
    except ImportError:
        return False
    for name, version in _WEBKIT_PROBE_VERSIONS:
        try:
            gi.require_version(name, version)
            return True
        except (ValueError, ImportError):
            continue
    return False
