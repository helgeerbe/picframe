"""
GStreamer Video Renderer implementation (IPC Client).
"""

from __future__ import annotations

import logging
import os
import stat
import subprocess
import sys
import threading
import time
from collections import deque
from multiprocessing.connection import Client, Connection
from pathlib import Path
from typing import Any

from picframe.core.events.dto import (
    PlaybackCompletedEvent,
    SystemErrorEvent,
    VideoFirstFrameRenderedEvent,
    VideoPlaybackDiagnosticsEvent,
    VideoPlaybackWarningEvent,
)
from picframe.core.events.interfaces import IEventPublisher
from picframe.core.models.media import MediaItem
from picframe.core.renderers.interfaces import IVideoPlayer
from picframe.core.renderers.ipc_protocol import (
    EosEvent,
    ErrorEvent,
    FirstFrameRenderedEvent,
    IpcMessage,
    PauseCommand,
    PlayCommand,
    ResumeCommand,
    SetPauseOverlayCommand,
    SetVolumeCommand,
    StopCommand,
    VideoDiagnosticsEvent,
    WarningEvent,
    parse_ipc_message,
)

logger = logging.getLogger(__name__)
_WORKER_SOCKET_TIMEOUT_SECONDS = 20.0
_WORKER_SOCKET_POLL_SECONDS = 0.1


class GstVideoRenderer(IVideoPlayer):
    """
    Video player implementation using an out-of-process GStreamer worker via IPC.
    """

    def __init__(
        self,
        event_publisher: IEventPublisher,
        max_software_decode_resolution: str = "1280x720",
    ):
        self._publisher = event_publisher
        self._max_software_decode_resolution = max_software_decode_resolution
        self._current_media: MediaItem | None = None
        self._geometry: tuple[int, int, int, int] = (0, 0, 0, 0)
        self._fit_display = False
        self._host_background: list[float] | tuple[float, ...] | None = None
        self._host_backdrop_path: str | None = None
        self._host_backdrop_rect: tuple[int, int, int, int] | list[int] | None = None
        self._content_fit: str | None = None
        self._volume: float = 1.0

        self._socket_path = f"/tmp/picframe_gst_{os.getpid()}.sock"
        self._worker_process: subprocess.Popen[str] | None = None
        self._conn: Connection | None = None
        self._running = False
        self._listener_thread: threading.Thread | None = None
        self._worker_log_thread: threading.Thread | None = None
        self._worker_log_tail: deque[str] = deque(maxlen=20)

        self._start_worker()

    def _start_worker(self) -> None:
        """Spawn the GStreamer worker subprocess and establish IPC connection."""
        worker_script = Path(__file__).parent / "gst_worker.py"

        env = self._worker_environment()

        try:
            self._worker_process = subprocess.Popen(
                [sys.executable, str(worker_script), "--socket", self._socket_path],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            self._start_worker_log_reader()

            # Wait for the worker to finish importing GStreamer and create the
            # IPC socket. This can be slow on small Pis immediately after boot.
            assert self._worker_process is not None
            deadline = time.monotonic() + _WORKER_SOCKET_TIMEOUT_SECONDS
            while time.monotonic() < deadline and not os.path.exists(self._socket_path):
                return_code = self._worker_process.poll()
                if return_code is not None:
                    hint = ""
                    if return_code < 0:
                        hint = (
                            " A negative exit code indicates the worker was killed "
                            "by a signal (e.g. SIGSEGV), which often points to a "
                            "GTK4/Wayland display initialization failure."
                        )
                    raise RuntimeError(
                        f"GStreamer worker exited before creating IPC socket "
                        f"(exit code {return_code}).{hint}{self._worker_log_summary()}"
                    )
                time.sleep(_WORKER_SOCKET_POLL_SECONDS)

            if not os.path.exists(self._socket_path):
                raise RuntimeError(
                    "Worker failed to create IPC socket within "
                    f"{_WORKER_SOCKET_TIMEOUT_SECONDS:.0f} seconds."
                    f"{self._worker_log_summary()}"
                )

            self._conn = Client(self._socket_path, family="AF_UNIX")
            self._running = True

            self._listener_thread = threading.Thread(target=self._listen_for_events, daemon=True)
            self._listener_thread.start()

            logger.info("Successfully connected to GStreamer worker subprocess.")

        except Exception as e:
            logger.error(f"Failed to start GStreamer worker: {e}")
            self._cleanup()

    def _start_worker_log_reader(self) -> None:
        """Forward worker stdout/stderr into the main Picframe logs."""
        if self._worker_process is None or self._worker_process.stdout is None:
            return
        self._worker_log_thread = threading.Thread(
            target=self._log_worker_output,
            args=(self._worker_process.stdout,),
            daemon=True,
        )
        self._worker_log_thread.start()

    def _log_worker_output(self, stream: Any) -> None:
        for raw_line in stream:
            line = str(raw_line).rstrip()
            if not line:
                continue
            self._worker_log_tail.append(line)
            logger.info("GStreamer worker: %s", line)

    def _worker_log_summary(self) -> str:
        if not self._worker_log_tail:
            return ""
        return " Recent worker output: " + " | ".join(self._worker_log_tail)

    def _worker_environment(self) -> dict[str, str]:
        """Return the environment used for the GStreamer worker process.

        The worker spawns GTK4 for ``gtk4paintablesink`` video rendering.  GTK4
        defaults to the X11/Xwayland backend when both ``WAYLAND_DISPLAY`` and
        ``DISPLAY`` are present, which causes green-screen / segfault crashes on
        Raspberry Pi 5 under labwc.  Enforce ``GDK_BACKEND=wayland`` so GTK4
        always uses native Wayland (X11 is not a supported target — see
        .clinerules).
        """
        env = os.environ.copy()
        if "GST_V4L2_ENABLE_PROBE" not in env and self._is_raspberry_pi_hardware():
            env["GST_V4L2_ENABLE_PROBE"] = "1"
        env["GDK_BACKEND"] = "wayland"
        if not env.get("WAYLAND_DISPLAY"):
            detected = self._detect_wayland_display(env.get("XDG_RUNTIME_DIR", ""))
            if detected:
                env["WAYLAND_DISPLAY"] = detected
                logger.info(
                    "WAYLAND_DISPLAY was not set; detected Wayland socket '%s' "
                    "in XDG_RUNTIME_DIR for the GStreamer worker.",
                    detected,
                )
            else:
                logger.warning(
                    "GDK_BACKEND=wayland is set for the GStreamer worker but "
                    "WAYLAND_DISPLAY is missing or empty and no Wayland socket "
                    "was found in XDG_RUNTIME_DIR — GTK4 may fail to "
                    "initialize. Check that the Wayland compositor is running and "
                    "WAYLAND_DISPLAY is exported in the picframe service environment."
                )
        return env

    @staticmethod
    def _detect_wayland_display(xdg_runtime_dir: str) -> str | None:
        """Detect a Wayland socket in *xdg_runtime_dir*.

        Scans the directory for entries named ``wayland-*`` that are actual
        Unix-domain sockets.  Returns the socket name (e.g. ``wayland-0``) when
        exactly one candidate is found, or ``None`` when the directory is
        inaccessible, empty, or contains multiple candidates (ambiguous — leave
        it to the environment).
        """
        if not xdg_runtime_dir:
            return None
        runtime_dir = Path(xdg_runtime_dir)
        try:
            candidates = [
                p.name
                for p in runtime_dir.iterdir()
                if p.name.startswith("wayland-") and stat.S_ISSOCK(p.lstat().st_mode)
            ]
        except OSError:
            return None
        if len(candidates) == 1:
            return candidates[0]
        return None

    @staticmethod
    def _is_raspberry_pi_hardware() -> bool:
        try:
            model = Path("/proc/device-tree/model").read_text(errors="ignore")
        except OSError:
            return False
        model = model.strip("\x00\n ").lower()
        return "raspberry pi" in model or "compute module" in model

    def _listen_for_events(self) -> None:
        """Background thread to listen for events from the worker."""
        while self._running and self._conn:
            try:
                if self._conn.poll(1.0):
                    msg_json = self._conn.recv()
                    msg = parse_ipc_message(msg_json)
                    if msg:
                        self._handle_event(msg)
            except EOFError:
                logger.warning("IPC connection closed by worker.")
                self._running = False
                break
            except Exception as e:
                logger.error(f"Error reading IPC event: {e}")

    def _handle_event(self, event: IpcMessage) -> None:
        """Translate IPC events into domain events."""
        if isinstance(event, EosEvent):
            logger.info("Received EOS from worker.")
            if event.last_sample_pts_seconds is not None:
                logger.info(
                    "Worker EOS last sample: pts=%.6fs duration=%s caps=%s",
                    event.last_sample_pts_seconds,
                    (
                        f"{event.last_sample_duration_seconds:.6f}s"
                        if event.last_sample_duration_seconds is not None
                        else "unknown"
                    ),
                    event.last_sample_caps or "unknown",
                )
            self._publisher.publish(PlaybackCompletedEvent())
        elif isinstance(event, ErrorEvent):
            if event.code == "unsupported_media":
                logger.warning("Unsupported video skipped by worker: %s", event.details)
                self._publisher.publish(
                    VideoPlaybackWarningEvent(
                        warning_type="unsupported_media",
                        decoder=event.details,
                    )
                )
                self._publisher.publish(PlaybackCompletedEvent())
                return
            logger.error(f"Received Error from worker: {event.details}")
            self._publisher.publish(
                SystemErrorEvent(
                    message=event.details,
                    component="GstVideoRenderer",
                    code=event.code,
                )
            )
            self._publisher.publish(PlaybackCompletedEvent())
        elif isinstance(event, WarningEvent):
            logger.warning(f"Worker Warning: {event.warning_type} - {event.decoder}")
            self._publisher.publish(
                VideoPlaybackWarningEvent(
                    warning_type=event.warning_type,
                    decoder=event.decoder,
                )
            )
        elif isinstance(event, VideoDiagnosticsEvent):
            logger.info(
                "Worker video diagnostics: stage=%s variant=%s decoder=%s "
                "hardware=%s dmabuf=%s sink=%s decision=%s fallback=%s "
                "hardware_limit=%s software_limit=%s",
                event.stage,
                event.pipeline_variant,
                event.decoder,
                event.decoder_is_hardware,
                event.uses_dmabuf,
                event.sink,
                event.decision,
                event.fallback_reason,
                event.hardware_limit,
                event.software_limit,
            )
            self._publisher.publish(
                VideoPlaybackDiagnosticsEvent(
                    pipeline_variant=event.pipeline_variant,
                    stage=event.stage,
                    sink=event.sink,
                    decoder=event.decoder,
                    decoder_is_hardware=event.decoder_is_hardware,
                    caps=event.caps,
                    uses_dmabuf=event.uses_dmabuf,
                    fallback_reason=event.fallback_reason,
                    hardware_limit=event.hardware_limit,
                    software_limit=event.software_limit,
                    decision=event.decision,
                )
            )
        elif isinstance(event, FirstFrameRenderedEvent):
            logger.info("Received FirstFrameRenderedEvent from worker.")
            self._publisher.publish(VideoFirstFrameRenderedEvent())

    def _send_command(self, cmd: IpcMessage) -> None:
        """Send a command to the worker."""
        if self._conn:
            try:
                self._conn.send(cmd.to_json())
            except Exception as e:
                logger.error(f"Failed to send IPC command: {e}")

    def play(
        self,
        media_item: MediaItem,
        x: int = 0,
        y: int = 0,
        w: int = 0,
        h: int = 0,
        fit_display: bool = False,
        host_background: list[float] | tuple[float, ...] | None = None,
        host_backdrop_path: str | None = None,
        host_backdrop_rect: tuple[int, int, int, int] | list[int] | None = None,
        content_fit: str | None = None,
    ) -> None:
        """Start playing the specified video media item."""
        if not self._running:
            logger.error("Cannot play video: Worker is not running.")
            self._publisher.publish(PlaybackCompletedEvent())
            return

        self.stop()
        self._current_media = media_item
        self._geometry = (x, y, w, h)
        self._fit_display = fit_display
        self._host_background = host_background
        self._host_backdrop_path = host_backdrop_path
        self._host_backdrop_rect = host_backdrop_rect
        self._content_fit = content_fit

        uri = Path(media_item.filepath).absolute().as_uri()

        # Send play command
        self._send_command(
            PlayCommand(
                uri=uri,
                x=x,
                y=y,
                w=w,
                h=h,
                max_software_decode_resolution=self._max_software_decode_resolution,
                fit_display=fit_display,
                host_background=host_background,
                host_backdrop_path=host_backdrop_path,
                host_backdrop_rect=host_backdrop_rect,
                content_fit=content_fit,
            )
        )
        logger.info(f"Sent play command for: {media_item.filepath} at ({x},{y}) {w}x{h}")

    def stop(self) -> None:
        """Stop video playback."""
        self._send_command(StopCommand())
        self._current_media = None
        logger.debug("Sent stop command.")

    def pause(self) -> None:
        """Pause video playback."""
        self._send_command(PauseCommand())
        logger.debug("Sent pause command.")

    def resume(self) -> None:
        """Resume paused video playback."""
        if self._current_media:
            self._send_command(ResumeCommand())
            logger.debug("Sent resume command.")

    def set_pause_overlay(self, visible: bool, text: str = "") -> None:
        """Show or hide the video-window pause status overlay."""
        self._send_command(SetPauseOverlayCommand(visible=visible, text=text))
        logger.debug("Sent pause overlay command: visible=%s text=%r.", visible, text)

    def set_volume(self, level: float) -> None:
        """Set the audio volume level (0.0 to 1.0)."""
        self._volume = max(0.0, min(1.0, level))
        self._send_command(SetVolumeCommand(level=self._volume))
        logger.debug(f"Sent set_volume command: {self._volume}")

    def set_max_software_decode_resolution(self, value: str) -> None:
        """Update the software decode ceiling for future play commands."""
        self._max_software_decode_resolution = value
        logger.info("Updated GStreamer software decode ceiling to %s.", value)

    def _cleanup(self) -> None:
        """Clean up resources."""
        self._running = False
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
        if self._worker_process:
            self._worker_process.terminate()
            try:
                self._worker_process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                self._worker_process.kill()
        if os.path.exists(self._socket_path):
            try:
                os.remove(self._socket_path)
            except Exception:
                pass

    def __del__(self) -> None:
        self._cleanup()
