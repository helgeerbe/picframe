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
    CurrentMediaChangedEvent,
    DisplayPowerEvent,
    OverlayConfigChangedEvent,
    OverlayVisibilityChangedEvent,
    RenderCommand,
    RendererConfigUpdatedEvent,
    SystemErrorEvent,
)
from picframe.core.events.interfaces import IEventPublisher, IEventSubscriber
from picframe.core.models.media import DisplayItem, MediaItem
from picframe.core.models.overlay import PluginDescriptor
from picframe.core.ports.overlay import IOverlayController
from picframe.core.renderers.overlay_ipc import (
    INPUT_ACTION_DISPLAY_OFF,
    INPUT_ACTION_NEXT,
    INPUT_ACTION_PREV,
    INPUT_ACTION_REBOOT_HOST,
    INPUT_ACTION_RESTART_SERVICE,
    INPUT_ACTION_SHUTDOWN_HOST,
    INPUT_ACTION_STOP,
    INPUT_ACTION_TOGGLE,
    InputEvent,
    MediaChangedCommand,
    OnScreenPluginsChangedEvent,
    OverlayErrorEvent,
    OverlayIpcMessage,
    ReadyEvent,
    ReloadCommand,
    SetConfigCommand,
    SetOpacityCommand,
    ShutdownCommand,
    VisiblePluginsChangedEvent,
    parse_overlay_ipc_message,
)
from picframe.infrastructure.overlay.plugin_loader import PluginLoader

logger = logging.getLogger(__name__)

_WEBKIT_UNAVAILABLE_CODE = "webkit_unavailable"
_WORKER_SOCKET_TIMEOUT_SECONDS = float(
    os.environ.get("PICFRAME_OVERLAY_WORKER_SOCKET_TIMEOUT", "20")
)
_WORKER_SOCKET_POLL_SECONDS = 0.1

# Exif keys mirrored from ``api.app.MEDIA_DTO_EXIF_KEYS`` so the overlay's
# ``CurrentMedia.exif`` blob is identical to the ``/ws/state`` payload shape.
# The controller is a core module and must not import from the API layer, so the
# key set is duplicated here with a reference to the canonical source.
_OVERLAY_EXIF_KEYS = (
    "make",
    "model",
    "lens",
    "f_number",
    "exposure_time",
    "iso",
    "focal_length",
    "exif_datetime",
    "caption",
    "tags",
    "location",
    "title",
    "rating",
    "width",
    "height",
    "orientation",
    "duration",
    "codec",
    "pixel_format",
    "framerate",
    "bitrate",
    "displayed_count",
    "last_displayed",
)


def _media_item_to_overlay_dict(item: MediaItem) -> dict[str, Any]:
    """Build a ``CurrentMedia``-shaped dict from a core ``MediaItem``.

    Mirrors ``api.app._media_item_to_dto`` but works from the core model
    directly, without a ``MediaRepository``: the indexer already resolved
    ``MediaItem.location`` to a name string at scan time, so ``location_name``
    is derived from that field without a live reverse-geocode lookup. The result
    is the same ``{file_path, media_type, exif, location}`` shape the
    ``/ws/state`` WebSocket produces, so plugins consume both paths
    identically (#757).
    """
    data: dict[str, Any] = item.to_dict()
    file_path = str(data.get("filepath") or "no_pictures.jpg")
    location: dict[str, float] | None = None
    if data.get("latitude") is not None and data.get("longitude") is not None:
        location = {"lat": float(data["latitude"]), "lon": float(data["longitude"])}
    exif: dict[str, Any] = {}
    for key in _OVERLAY_EXIF_KEYS:
        if key in data and data[key] is not None:
            if key == "location" and isinstance(data[key], dict):
                continue
            exif[key] = data[key]
    # ``MediaItem.location`` is the resolved location-name string; expose it as
    # ``location_name`` in exif (same as the WS DTO path).
    loc = data.get("location")
    if isinstance(loc, str) and loc:
        exif["location_name"] = loc
    elif "location" in exif and isinstance(exif["location"], str):
        exif["location_name"] = exif["location"]
    return {
        "file_path": file_path,
        "media_type": "video" if str(data.get("media_type", "")).lower() == "video" else "image",
        "exif": exif,
        "location": location,
    }


def _display_item_to_overlay_dict(media_item: Any) -> dict[str, Any]:
    """Extract the primary ``MediaItem`` from a ``CurrentMediaChangedEvent`` payload.

    The event carries a :class:`DisplayItem` (one slideshow slot, possibly a
    portrait pair). The overlay only needs the primary item's metadata, so we
    resolve via the ``primary`` property and map it. Falls back to an empty
    placeholder dict for unexpected payload shapes so a malformed event never
    crashes the listener.
    """
    if isinstance(media_item, DisplayItem):
        return _media_item_to_overlay_dict(media_item.primary)
    if isinstance(media_item, MediaItem):
        return _media_item_to_overlay_dict(media_item)
    return {"file_path": "no_pictures.jpg", "media_type": "image", "exif": {}, "location": None}


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
        time_fade: float = 2.0,
    ) -> None:
        self._publisher = event_publisher
        self._subscriber = event_subscriber
        self._plugin_loader = plugin_loader
        self._html_dir = html_dir
        self._plugin_dir = plugin_dir
        self._ws_port = ws_port
        self._overlay_config = overlay_config or {}
        # Image blend time (``model.fade_time`` / ``RendererConfig.time_fade``),
        # injected into the shell config so the ``media_change`` wake-after-blend
        # driver (#757) waits for the new photo to finish crossfading before
        # revealing the auto-shown text panel. Kept live via
        # ``RendererConfigUpdatedEvent`` so Appearance edits take effect without
        # a restart.
        self._time_fade = float(time_fade)

        self._socket_path = f"/tmp/picframe_overlay_{os.getpid()}.sock"
        self._worker_process: subprocess.Popen[str] | None = None
        self._conn: Connection | None = None
        self._running = False
        self._listener_thread: threading.Thread | None = None
        self._subscribed = False
        self._stopped = False  # set by public stop() (shutdown); NOT by worker crash
        self._availability: bool | None = None
        # Guard for the display power-on restart path so a rapid sequence of
        # ``DisplayPowerEvent``s cannot overlap a stop/start cycle, and so the
        # restart is skipped during shutdown. ``threading.Lock`` serializes the
        # check-and-set of ``_restarting``; ``_restarting`` prevents re-entrancy.
        self._restart_lock = threading.Lock()
        self._restarting = False

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
        self._stopped = False
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
        self._send_command(SetConfigCommand(config=self._worker_config()))

    def _worker_config(self) -> dict[str, Any]:
        """Return the overlay config dict augmented with the live ``time_fade``.

        The shell reads ``time_fade`` to delay the ``media_change`` auto-wake
        until the image blend has finished (#757). The worker's
        ``_build_shell_config`` passes extra keys through unchanged, and the
        shell's ``OverlayShellConfig`` type treats it as optional.
        """
        config = dict(self._overlay_config)
        config["time_fade"] = self._time_fade
        return config

    def stop(self) -> None:
        """Stop the worker subprocess and unsubscribe from events."""
        self._stopped = True
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
        elif isinstance(event, VisiblePluginsChangedEvent):
            # The dock toggle changed the expanded plugin set (#765). Republish
            # it as the exact ``CommandEvent(SET_CONFIG, {overlay:
            # {visible_plugins}})`` the Remote/Appearance REST endpoint
            # (``PUT /api/workflow-config``) publishes. ConfigService then
            # persists it to ``config.db3`` and emits
            # ``OverlayConfigChangedEvent``, which this renderer forwards back
            # to the worker/shell — so the dock's optimistic update is
            # reconciled with the persisted truth and both UIs stay in sync.
            self._publisher.publish(
                CommandEvent(
                    command=Command.SET_CONFIG,
                    payload={"overlay": {"visible_plugins": list(event.visible_plugins)}},
                )
            )
        elif isinstance(event, OnScreenPluginsChangedEvent):
            # The on-screen (runtime) visibility of expanded plugins changed
            # (#766) — an auto-hide fade, wake, media_change re-arm, or toggle.
            # This is **not** persisted to ``config.db3`` (auto-hide is a
            # client-side CSS fade), so it does NOT go through
            # ``CommandEvent(SET_CONFIG)``. Republish it directly as the
            # ``OverlayVisibilityChangedEvent`` domain event the ``/ws/state``
            # endpoint forwards to browsers, so the Remote tile highlights
            # mirror the on-screen state instead of the persisted
            # ``visible_plugins`` set.
            self._publisher.publish(
                OverlayVisibilityChangedEvent(on_screen_plugins=event.on_screen_plugins)
            )

    def _send_command(self, cmd: OverlayIpcMessage) -> None:
        """Send a command to the worker."""
        if self._conn:
            try:
                self._conn.send(cmd.to_json())
            except Exception as e:
                logger.error("Failed to send overlay IPC command: %s", e)
        elif self._running:
            # A command arrived while running but the IPC connection was lost
            # (e.g. worker crashed). Without this line every media_changed /
            # config command is silently dropped, hiding a dead overlay.
            logger.warning(
                "Overlay IPC send dropped (no connection): type=%s",
                getattr(cmd, "type", type(cmd).__name__),
            )

    # --- Event subscriptions ---

    def _subscribe_events(self) -> None:
        self._subscriber.subscribe(OverlayConfigChangedEvent, self._on_overlay_config_changed)
        self._subscriber.subscribe(RenderCommand, self._on_render_command)
        self._subscriber.subscribe(DisplayPowerEvent, self._on_display_power_event)
        self._subscriber.subscribe(RendererConfigUpdatedEvent, self._on_renderer_config_updated)
        self._subscriber.subscribe(CurrentMediaChangedEvent, self._on_media_changed)
        self._subscribed = True

    def _unsubscribe_events(self) -> None:
        if self._subscribed:
            self._subscriber.unsubscribe(OverlayConfigChangedEvent, self._on_overlay_config_changed)
            self._subscriber.unsubscribe(RenderCommand, self._on_render_command)
            self._subscriber.unsubscribe(DisplayPowerEvent, self._on_display_power_event)
            self._subscriber.unsubscribe(
                RendererConfigUpdatedEvent, self._on_renderer_config_updated
            )
            self._subscriber.unsubscribe(CurrentMediaChangedEvent, self._on_media_changed)
            self._subscribed = False

    def _on_overlay_config_changed(self, event: OverlayConfigChangedEvent) -> None:
        """Forward a live overlay config change to the worker."""
        self._overlay_config = dict(event.overlay_config)
        self._send_command(SetConfigCommand(config=self._worker_config()))

    def _on_media_changed(self, event: CurrentMediaChangedEvent) -> None:
        """Forward the current media to the worker so ``media_change`` plugins wake.

        The controller is in-process with the event bus, so this path bypasses
        the cross-origin ``/ws/state`` WebSocket (which the ``file://`` overlay
        shell may not be able to establish under WebKitGTK). The worker pushes
        the media to the shell via the same ``evaluate_javascript`` bridge used
        for config, so the text overlay's ``media_change`` trigger fires on
        every photo change (#757).
        """
        if not self._running:
            logger.warning(
                "Overlay media_changed received but overlay not running (dropped): file=%s",
                getattr(event.media_item.primary, "filepath", "?"),
            )
            return
        media = _display_item_to_overlay_dict(event.media_item)
        logger.debug(
            "Overlay media_changed: file=%s type=%s",
            media.get("file_path"),
            media.get("media_type"),
        )
        self._send_command(MediaChangedCommand(media=media))

    def _on_renderer_config_updated(self, event: RendererConfigUpdatedEvent) -> None:
        """Keep the injected ``time_fade`` live and re-push the shell config (#757).

        ``model.fade_time`` / ``RendererConfig.time_fade`` is the image blend
        duration the shell waits before revealing a ``media_change`` panel.
        Appearance edits publish this event; we update the stored value and
        re-push so the new blend time takes effect without an overlay restart.
        """
        self._time_fade = float(event.config.time_fade)
        if self._running:
            self._send_command(SetConfigCommand(config=self._worker_config()))

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

    def _on_display_power_event(self, event: DisplayPowerEvent) -> None:
        """Restart the worker when the display is turned back on.

        The overlay is a ``wlr-layer-shell`` surface bound to a specific Wayland
        output. When the display is powered off the compositor destroys that
        output and the layer-shell surface is orphaned (labwc: "view has no
        output"); when the display is powered back on the recreated output is a
        new object the orphaned surface never re-attaches to, so the overlay
        stays invisible until picframe is restarted. Respawning the worker
        re-runs the proven surface-creation path against the now-live output.

        The respawn runs off the single-threaded event bus worker (the socket
        wait can block up to ``_WORKER_SOCKET_TIMEOUT_SECONDS``) and is guarded
        so a burst of power events cannot stack restarts or race shutdown.
        """
        if not event.power_on or self._stopped:
            return
        self._schedule_respawn()

    def _schedule_respawn(self) -> None:
        """Guarded, single-flight worker respawn for display/output recovery.

        Driven by the ``DisplayPowerEvent`` (poll/watcher) path. The
        ``_restart_lock`` serializes the check-and-set of ``_restarting`` so a
        burst of events collapses to exactly one respawn; ``_stopped`` skips
        the respawn during an intentional shutdown.
        """
        if self._stopped:
            return
        with self._restart_lock:
            if self._restarting:
                return
            self._restarting = True
        thread = threading.Thread(target=self._restart_worker, daemon=True)
        thread.start()

    def _restart_worker(self) -> None:
        """Stop and re-``start`` the worker subprocess (display power-on path).

        Calls the internal cleanup directly rather than the public :meth:`stop`
        so the ``_stopped`` flag (shutdown-only) is never set during a respawn —
        otherwise a subsequent ``DisplayPowerEvent`` arriving while the restart
        thread is between cleanup and re-start would be incorrectly skipped.
        """
        try:
            logger.info("Display powered on; restarting overlay worker to re-attach layer surface.")
            self._unsubscribe_events()
            self._cleanup()
            self.start()
        except Exception as e:  # pragma: no cover - defensive; cleanup self-heals
            logger.error("Failed to restart overlay worker after display power-on: %s", e)
        finally:
            with self._restart_lock:
                self._restarting = False

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
    """Map an overlay input action to a playback/system Command.

    Navigation actions (prev/next/toggle) map to playback commands; the
    danger-menu actions (#763, #740) map to system commands handled by
    :class:`SystemManager` (reboot/shutdown/restart) and
    :class:`DisplayPowerManager` (display off). The exception is ``stop``
    (:data:`INPUT_ACTION_STOP`) which maps to :data:`Command.STOP` — a
    graceful :class:`PlaybackEngine` shutdown that tears down the main
    loop in ``main.py`` rather than invoking a system manager.
    """
    if action == INPUT_ACTION_PREV:
        return Command.PREV
    if action == INPUT_ACTION_NEXT:
        return Command.NEXT
    if action == INPUT_ACTION_TOGGLE:
        return Command.PLAY
    if action == INPUT_ACTION_DISPLAY_OFF:
        return Command.DISPLAY_OFF
    if action == INPUT_ACTION_RESTART_SERVICE:
        return Command.RESTART_SERVICE
    if action == INPUT_ACTION_REBOOT_HOST:
        return Command.REBOOT_HOST
    if action == INPUT_ACTION_SHUTDOWN_HOST:
        return Command.SHUTDOWN_HOST
    if action == INPUT_ACTION_STOP:
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
