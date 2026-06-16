"""
GStreamer Subprocess Worker.

This script runs in an isolated subprocess to handle GStreamer video playback.
It communicates with the main application process via an IPC socket using JSON messages.
"""

import argparse
import logging
import os
import re
import sys
import time
from dataclasses import dataclass
from multiprocessing.connection import Connection, Listener
from typing import Any
from urllib.parse import unquote, urlparse

from picframe.core.renderers.ipc_protocol import (
    CapsResultEvent,
    CheckCapsCommand,
    EosEvent,
    ErrorEvent,
    FirstFrameRenderedEvent,
    IpcMessage,
    PauseCommand,
    PlayCommand,
    SetVolumeCommand,
    StopCommand,
    VideoDiagnosticsEvent,
    WarningEvent,
    parse_ipc_message,
)

# Configure logging for the worker
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("gst_worker")

PIPELINE_COMPATIBLE = "compatible"
PIPELINE_HARDWARE_DIRECT = "hardware_direct"
PIPELINE_HARDWARE_PLAYBIN = "hardware_playbin"
PIPELINE_GTK_PLAYBIN = "gtk_playbin"
PIPELINE_GTK_COMPATIBLE = "gtk_compatible"
PIPELINE_SKIPPED = "skipped"
DEFAULT_SOFTWARE_DECODE_LIMIT = "1280x720"
UNSUPPORTED_MEDIA_CODE = "unsupported_media"
GTK_PRESENTATION_UNAVAILABLE_CODE = "gtk_presentation_unavailable"
EOS_GTK_WINDOW_OPACITY = 0.99
STARTUP_GTK_WINDOW_OPACITY = 0.0
FIRST_FRAME_PROBE_INTERVAL_MS = 16
FIRST_FRAME_PROBE_TIMEOUT_SECONDS = 2.0
GTK_TRANSPARENT_HOST_CLASS = "picframe-transparent-video-host"
GTK_OPAQUE_HOST_CLASS = "picframe-opaque-video-host"


@dataclass(frozen=True)
class DecodeResolutionLimit:
    width: int
    height: int


@dataclass(frozen=True)
class DecodeHardwareLimit:
    width: int
    height: int
    max_fps: float | None
    model_family: str
    source: str


@dataclass(frozen=True)
class VideoStreamFacts:
    caps: Any | None
    caps_string: str | None
    codec: str | None
    width: int | None
    height: int | None
    framerate: float | None = None
    container: str | None = None


@dataclass(frozen=True)
class PlaybackDecision:
    pipeline_variant: str
    force_software_decoders: bool
    decision: str
    fallback_reason: str | None = None
    skip_reason: str | None = None
    error_code: str | None = None
    hardware_limit: str | None = None
    software_limit: str | None = None


@dataclass(frozen=True)
class PlayRequest:
    uri: str
    x: int
    y: int
    w: int
    h: int
    fit_display: bool
    host_background: list[float] | tuple[float, ...] | None = None


RPI_HARDWARE_DECODE_LIMITS: dict[str, dict[str, DecodeHardwareLimit]] = {
    "pi5": {
        "h265": DecodeHardwareLimit(
            width=3840,
            height=2160,
            max_fps=60.0,
            model_family="Raspberry Pi 5 / Compute Module 5",
            source="official",
        ),
    },
    "pi4": {
        "h264": DecodeHardwareLimit(
            width=1920,
            height=1080,
            max_fps=60.0,
            model_family="Raspberry Pi 4 / 400 / Compute Module 4",
            source="official",
        ),
        "h265": DecodeHardwareLimit(
            width=3840,
            height=2160,
            max_fps=60.0,
            model_family="Raspberry Pi 4 / 400 / Compute Module 4",
            source="official",
        ),
    },
    "pi3": {
        "h264": DecodeHardwareLimit(
            width=1920,
            height=1080,
            max_fps=30.0,
            model_family="Raspberry Pi 3 / Compute Module 3",
            source="official",
        ),
    },
    "zero2": {
        "h264": DecodeHardwareLimit(
            width=1920,
            height=1080,
            max_fps=30.0,
            model_family="Raspberry Pi Zero 2 W",
            source="official",
        ),
    },
    "zero": {
        "h264": DecodeHardwareLimit(
            width=1920,
            height=1080,
            max_fps=30.0,
            model_family="Raspberry Pi Zero / Zero W / Zero WH",
            source="official",
        ),
    },
}

try:
    import gi
    gi.require_version('Gst', '1.0')
    gi.require_version('GstPbutils', '1.0')
    from gi.repository import GLib, Gst, GstPbutils
    Gst.init(None)
    GST_AVAILABLE = True
except ImportError as exc:
    Gst = Any
    GLib = Any
    GstPbutils = Any
    logger.error("GStreamer not available. Worker cannot start: %s", exc)
    GST_AVAILABLE = False

from picframe.core.renderers.gst_utils import find_best_element  # noqa: E402


class GstWorker:
    def __init__(self, socket_path: str):
        self.socket_path = socket_path
        self.conn: Connection | None = None
        self.listener: Listener | None = None
        self.pipeline: Any = None
        self.bus: Any = None
        self.volume: float = 1.0
        self.running = True
        self.loop: Any = GLib.MainLoop() if GST_AVAILABLE else None
        self._current_play_request: PlayRequest | None = None
        self._current_stream_facts: VideoStreamFacts | None = None
        self._current_max_software_decode_resolution: str | None = None
        self._software_decode_retry_attempted = False
        self._compatible_pipeline_retry_attempted = False
        self._current_pipeline_variant = PIPELINE_COMPATIBLE
        self._current_sink_name: str | None = None
        self._selected_decoder_name: str | None = None
        self._selected_decoder_is_hardware = False
        self._last_video_caps: str | None = None
        self._last_uses_dmabuf = False
        self._current_hardware_limit: str | None = None
        self._current_software_limit: str | None = None
        self._current_decision: str | None = None
        self._hardware_model = self._read_hardware_model()
        self._gtk: Any | None = None
        self._gdk: Any | None = None
        self._gtk_window: Any = None
        self._gtk_host: Any = None
        self._gtk_sink_widget: Any = None
        self._gtk_video_sink: Any = None
        self._gtk_pump_source_id: int | None = None
        self._gtk_presentation_failure: str | None = None
        self._first_frame_event_sent = False
        self._first_frame_probe_source_id: int | None = None
        self._first_frame_probe_started_at = 0.0

    @staticmethod
    def _read_hardware_model() -> str:
        try:
            with open("/proc/device-tree/model", "rb") as model_file:
                return model_file.read().decode(errors="ignore").strip("\x00\n ")
        except OSError:
            return ""

    def start(self) -> None:
        """Start the worker and listen for IPC connections."""
        if not GST_AVAILABLE:
            sys.exit(1)

        # Ensure socket path directory exists
        os.makedirs(os.path.dirname(self.socket_path), exist_ok=True)
        
        # Remove existing socket if it exists
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)

        logger.info(f"Starting IPC listener on {self.socket_path}")
        self.listener = Listener(self.socket_path, family='AF_UNIX')
        
        # Accept the initial connection
        self._accept_connection()

        # Run the GLib main loop (required for GStreamer bus signals)
        try:
            if self.loop:
                self.loop.run()
        except KeyboardInterrupt:
            pass
        finally:
            self.cleanup()

    def _accept_connection(self) -> None:
        """Accept a connection and set up the IO watch."""
        if self.listener:
            try:
                self.conn = self.listener.accept()
                logger.info("Main process connected.")
                # Add the connection's file descriptor to the GLib main loop
                if self.conn and hasattr(self.conn, 'fileno'):
                    GLib.io_add_watch(
                        self.conn.fileno(),
                        GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR,
                        self._on_ipc_data,
                    )
            except Exception as e:
                logger.error(f"Failed to accept connection: {e}")

    def _on_ipc_data(self, fd: int, condition: Any) -> bool:
        """Callback for GLib IO watch when data is available on the IPC socket."""
        if condition & (GLib.IO_HUP | GLib.IO_ERR):
            logger.info("IPC connection closed or errored.")
            self._handle_disconnect()
            return False # Remove the watch

        if condition & GLib.IO_IN:
            try:
                if self.conn:
                    msg_json = self.conn.recv()
                    msg = parse_ipc_message(msg_json)
                    if msg:
                        self._dispatch_command(msg)
                    else:
                        logger.warning(f"Failed to parse IPC message: {msg_json}")
            except EOFError:
                logger.info("IPC connection closed by main process (EOF).")
                self._handle_disconnect()
                return False # Remove the watch
            except Exception as e:
                logger.error(f"Error reading IPC message: {e}")
                self._handle_disconnect()
                return False # Remove the watch

        return True # Keep the watch active

    def _handle_disconnect(self) -> None:
        """Handle disconnection from the main process."""
        self._handle_stop()
        if self.conn:
            self.conn.close()
            self.conn = None
        
        # In a robust system, we might want to wait for a new connection here.
        # For now, we exit the worker so the main process can respawn it cleanly.
        logger.info("Exiting worker due to disconnect.")
        self.running = False
        if self.loop:
            self.loop.quit()

    def _send_event(self, event: IpcMessage) -> None:
        """Send an event back to the main process."""
        if self.conn and not self.conn.closed:
            try:
                self.conn.send(event.to_json())
            except Exception as e:
                logger.error(f"Failed to send IPC event: {e}")

    def _send_first_frame_rendered_once(self) -> None:
        if self._first_frame_event_sent:
            return
        self._first_frame_event_sent = True
        self._first_frame_probe_source_id = None
        self._reveal_gtk_video_window()
        self._send_event(FirstFrameRenderedEvent())

    def _current_video_sink(self) -> Any | None:
        if self._gtk_video_sink is not None:
            return self._gtk_video_sink
        if self.pipeline is None:
            return None
        try:
            return self.pipeline.get_by_name("sink")
        except Exception:
            return None

    @staticmethod
    def _stats_rendered_count(stats: Any) -> int | None:
        if stats is None:
            return None

        if isinstance(stats, dict):
            value = stats.get("rendered")
            try:
                return int(value)
            except (TypeError, ValueError):
                return None

        try:
            value = stats.get_value("rendered")
            return int(value)
        except Exception:
            pass

        try:
            stats_text = stats.to_string()
        except Exception:
            stats_text = str(stats)
        match = re.search(r"\brendered\s*[:=]\s*(?:\([^)]*\))?(\d+)", stats_text)
        if match is None:
            return None
        try:
            return int(match.group(1))
        except ValueError:
            return None

    def _current_sink_rendered_count(self) -> int | None:
        sink = self._current_video_sink()
        if sink is None:
            return None
        try:
            stats = sink.get_property("stats")
        except Exception:
            return None
        return self._stats_rendered_count(stats)

    def _schedule_first_frame_probe(self) -> None:
        if self._first_frame_event_sent:
            return

        rendered_count = self._current_sink_rendered_count()
        if rendered_count is None:
            logger.debug("Video sink render stats unavailable; accepting async-done.")
            self._send_first_frame_rendered_once()
            return
        if rendered_count > 0:
            self._send_first_frame_rendered_once()
            return

        if self._first_frame_probe_source_id is not None or not GST_AVAILABLE:
            return
        self._first_frame_probe_started_at = time.monotonic()
        self._first_frame_probe_source_id = GLib.timeout_add(
            FIRST_FRAME_PROBE_INTERVAL_MS,
            self._first_frame_probe_tick,
        )

    def _first_frame_probe_tick(self) -> bool:
        if self.pipeline is None or self._first_frame_event_sent:
            self._first_frame_probe_source_id = None
            return False

        rendered_count = self._current_sink_rendered_count()
        if rendered_count is None:
            logger.debug("Video sink render stats became unavailable; accepting async-done.")
            self._send_first_frame_rendered_once()
            return False
        if rendered_count > 0:
            logger.debug("Video sink rendered first frame.")
            self._send_first_frame_rendered_once()
            return False

        elapsed = time.monotonic() - self._first_frame_probe_started_at
        if elapsed >= FIRST_FRAME_PROBE_TIMEOUT_SECONDS:
            logger.warning(
                "Timed out waiting for video sink rendered-frame stats; "
                "main process first-frame timeout remains active."
            )
            self._first_frame_probe_source_id = None
            return False
        return True

    def _stop_first_frame_probe(self) -> None:
        if self._first_frame_probe_source_id is not None and GST_AVAILABLE:
            try:
                GLib.source_remove(self._first_frame_probe_source_id)
            except Exception:
                pass
        self._first_frame_probe_source_id = None
        self._first_frame_probe_started_at = 0.0

    def _dispatch_command(self, cmd: IpcMessage) -> None:
        """Dispatch an incoming command to the appropriate handler."""
        if isinstance(cmd, PlayCommand):
            self._handle_play(
                cmd.uri,
                cmd.x,
                cmd.y,
                cmd.w,
                cmd.h,
                cmd.max_software_decode_resolution,
                cmd.fit_display,
                cmd.host_background,
            )
        elif isinstance(cmd, PauseCommand):
            self._handle_pause()
        elif isinstance(cmd, StopCommand):
            self._handle_stop()
        elif isinstance(cmd, SetVolumeCommand):
            self._handle_set_volume(cmd.level)
        elif isinstance(cmd, CheckCapsCommand):
            self._handle_check_caps(cmd.uri)

    def _handle_play(
        self,
        uri: str,
        x: int,
        y: int,
        w: int,
        h: int,
        max_software_decode_resolution: str | None = None,
        fit_display: bool = False,
        host_background: list[float] | tuple[float, ...] | None = None,
    ) -> None:
        try:
            stream_facts, reason = self._discover_video_stream_facts(uri)
            if stream_facts is None:
                details = reason or "No playable video stream found."
                logger.error(f"Skipping {uri}: {details}")
                self._send_event(ErrorEvent(details=details, code=UNSUPPORTED_MEDIA_CODE))
                return

            self._current_play_request = PlayRequest(
                uri=uri,
                x=x,
                y=y,
                w=w,
                h=h,
                fit_display=fit_display,
                host_background=host_background,
            )
            self._current_stream_facts = stream_facts
            self._current_max_software_decode_resolution = max_software_decode_resolution
            self._software_decode_retry_attempted = False
            self._compatible_pipeline_retry_attempted = False
            self._start_pipeline(
                uri,
                x,
                y,
                w,
                h,
                force_software_decoders=False,
                max_software_decode_resolution=max_software_decode_resolution,
                stream_facts=stream_facts,
                fit_display=fit_display,
                host_background=host_background,
            )
        except Exception as e:
            logger.error(f"Exception during playback setup: {e}")
            self._send_event(ErrorEvent(details=str(e)))
            self._handle_stop()

    def _start_pipeline(
        self,
        uri: str,
        x: int,
        y: int,
        w: int,
        h: int,
        *,
        force_software_decoders: bool,
        pipeline_variant: str | None = None,
        fallback_reason: str | None = None,
        max_software_decode_resolution: str | None = None,
        stream_facts: VideoStreamFacts | None = None,
        fit_display: bool = False,
        host_background: list[float] | tuple[float, ...] | None = None,
    ) -> None:
        self._handle_stop()

        try:
            sink_name = self._select_sink_name()
            stream_facts = stream_facts or self._current_stream_facts
            max_software_decode_resolution = (
                max_software_decode_resolution
                or self._current_max_software_decode_resolution
                or DEFAULT_SOFTWARE_DECODE_LIMIT
            )
            if pipeline_variant is None or force_software_decoders:
                decision = self._select_playback_decision(
                    uri,
                    sink_name,
                    force_software_decoders=force_software_decoders,
                    max_software_decode_resolution=max_software_decode_resolution,
                    stream_facts=stream_facts,
                    fallback_reason=fallback_reason,
                )
                pipeline_variant = decision.pipeline_variant
                force_software_decoders = decision.force_software_decoders
                fallback_reason = decision.fallback_reason
            else:
                decision = PlaybackDecision(
                    pipeline_variant=pipeline_variant,
                    force_software_decoders=force_software_decoders,
                    decision=(
                        "software_fallback"
                        if force_software_decoders
                        else pipeline_variant
                    ),
                    fallback_reason=fallback_reason,
                    hardware_limit=self._format_hardware_limit(
                        self._known_hardware_decode_limit(stream_facts)
                    ),
                    software_limit=self._format_resolution_limit(
                        self._software_decode_limit(max_software_decode_resolution)
                    ),
                )

            if (
                fit_display
                and pipeline_variant in {PIPELINE_HARDWARE_DIRECT, PIPELINE_HARDWARE_PLAYBIN}
            ):
                pipeline_variant = PIPELINE_COMPATIBLE
                fallback_reason = fallback_reason or "video_fit_display"

            if decision.skip_reason is not None:
                self._reset_pipeline_telemetry(
                    pipeline_variant,
                    sink_name,
                    decision=decision.decision,
                    hardware_limit=decision.hardware_limit,
                    software_limit=decision.software_limit,
                )
                if stream_facts is not None:
                    self._last_video_caps = stream_facts.caps_string
                logger.warning("Skipping %s: %s", uri, decision.skip_reason)
                self._send_video_diagnostics(
                    stage="decision",
                    fallback_reason=decision.fallback_reason,
                )
                self._send_event(
                    ErrorEvent(
                        details=decision.skip_reason,
                        code=decision.error_code or UNSUPPORTED_MEDIA_CODE,
                    )
                )
                return

            logger.info(
                "Video playback decision for %s: decision=%s variant=%s "
                "force_software=%s hardware_limit=%s software_limit=%s "
                "fallback=%s",
                uri,
                decision.decision,
                pipeline_variant,
                force_software_decoders,
                decision.hardware_limit,
                decision.software_limit,
                decision.fallback_reason,
            )
            gtk_pipeline = None
            gtk_playbin_attempted = False
            self._gtk_presentation_failure = None
            if not self._gtk_paintable_sink_available():
                self._gtk_presentation_failure = "gtk4paintablesink element is not installed"
                self._send_gtk_presentation_unavailable_error()
                return

            if self._should_attempt_gtk_playbin(
                sink_name,
                x,
                y,
                w,
                h,
                force_software_decoders=force_software_decoders,
                pipeline_variant=pipeline_variant,
            ):
                gtk_playbin_attempted = True
                gtk_pipeline = self._create_gtk_playbin_pipeline(
                    uri,
                    x,
                    y,
                    w,
                    h,
                    fit_display=fit_display,
                    host_background=host_background,
                )
                if gtk_pipeline is not None:
                    pipeline_variant = PIPELINE_GTK_PLAYBIN
                    sink_name = "gtk4paintablesink"
                    logger.info("Using GTK4-backed gtk4paintablesink presentation path.")
                else:
                    logger.warning(
                        "GTK-backed video presentation unavailable or geometry "
                        "could not be confirmed.",
                    )
            if gtk_pipeline is None and self._should_attempt_gtk_compatible(
                sink_name,
                x,
                y,
                w,
                h,
                pipeline_variant=(
                    PIPELINE_COMPATIBLE if gtk_playbin_attempted else pipeline_variant
                ),
            ):
                gtk_pipeline = self._create_gtk_compatible_pipeline(
                    uri,
                    x,
                    y,
                    w,
                    h,
                    force_software_decoders=force_software_decoders,
                    fit_display=fit_display,
                    host_background=host_background,
                )
                if gtk_pipeline is not None:
                    pipeline_variant = PIPELINE_GTK_COMPATIBLE
                    sink_name = "gtk4paintablesink"
                    logger.info("Using GTK4-compatible gtk4paintablesink presentation path.")
                else:
                    logger.warning(
                        "GTK-compatible video presentation unavailable or geometry "
                        "could not be confirmed.",
                    )

            if gtk_pipeline is None:
                self._gtk_presentation_failure = (
                    self._gtk_presentation_failure
                    or "No GTK4 presentation path matched the playback decision"
                )
                self._send_gtk_presentation_unavailable_error()
                return

            self._reset_pipeline_telemetry(
                pipeline_variant,
                sink_name,
                decision=decision.decision,
                hardware_limit=decision.hardware_limit,
                software_limit=decision.software_limit,
            )
            self._send_video_diagnostics(
                stage="decision",
                fallback_reason=fallback_reason,
            )
            self.pipeline = gtk_pipeline
            if force_software_decoders:
                logger.info("Retrying %s with software decoders forced.", uri)
            self._connect_pipeline_telemetry_hooks()
            self._send_video_diagnostics(
                stage="pipeline",
                fallback_reason=fallback_reason,
            )
            
            try:
                self.pipeline.set_property("volume", self.volume)
            except TypeError:
                pass
                
            self.bus = self.pipeline.get_bus()
            self.bus.add_signal_watch()
            self.bus.connect("message::eos", self._on_eos)
            self.bus.connect("message::error", self._on_error)
            self.bus.connect("message::async-done", self._on_async_done)
            
            ret = self.pipeline.set_state(Gst.State.PLAYING)
            if ret == Gst.StateChangeReturn.FAILURE:
                logger.error(f"Failed to set pipeline state to PLAYING for {uri}")
                if self._should_retry_with_compatible_pipeline(
                    "Pipeline failed to start playing.",
                    "",
                ):
                    self._retry_with_compatible_pipeline(
                        "Pipeline failed to start playing.",
                        "",
                    )
                else:
                    self._send_event(ErrorEvent(details="Pipeline failed to start playing."))
                    self._handle_stop()
            else:
                logger.info(f"Playing {uri}")
        except Exception as e:
            logger.error(f"Exception during playback setup: {e}")
            self._send_event(ErrorEvent(details=str(e)))
            self._handle_stop()

    def _select_sink_name(self) -> str:
        sink_name = find_best_element(
            ["waylandsink", "glimagesink", "ximagesink", "autovideosink"]
        )
        return sink_name or "autovideosink"

    @staticmethod
    def _gtk_paintable_sink_available() -> bool:
        return find_best_element(["gtk4paintablesink"]) == "gtk4paintablesink"

    def _send_gtk_presentation_unavailable_error(self) -> None:
        details = (
            "GTK4 video presentation is required on Wayland but could not "
            "be initialized or confirmed."
        )
        if self._gtk_presentation_failure:
            details = f"{details} Last GTK4 failure: {self._gtk_presentation_failure}."
        logger.error(details)
        self._send_event(
            ErrorEvent(
                details=details,
                code=GTK_PRESENTATION_UNAVAILABLE_CODE,
            )
        )

    def _should_attempt_gtk_playbin(
        self,
        sink_name: str,
        x: int,
        y: int,
        w: int,
        h: int,
        *,
        force_software_decoders: bool,
        pipeline_variant: str,
    ) -> bool:
        if (w <= 0 or h <= 0) and (x != 0 or y != 0):
            return False

        is_raspberry_pi = self._raspberry_pi_model_family(self._hardware_model) is not None
        if is_raspberry_pi:
            return (
                not force_software_decoders
                and pipeline_variant in {
                    PIPELINE_HARDWARE_DIRECT,
                    PIPELINE_HARDWARE_PLAYBIN,
                }
            )

        return False

    def _should_attempt_gtk_compatible(
        self,
        sink_name: str,
        x: int,
        y: int,
        w: int,
        h: int,
        *,
        pipeline_variant: str,
    ) -> bool:
        if pipeline_variant != PIPELINE_COMPATIBLE:
            return False
        if (w <= 0 or h <= 0) and (x != 0 or y != 0):
            return False
        return True

    def _ensure_gtk(self) -> Any | None:
        if self._gtk is not None:
            return self._gtk
        try:
            Gtk, Gdk = self._init_gtk4()
        except Exception as exc:
            logger.warning("GTK4 unavailable for gtk4paintablesink presentation: %s", exc)
            self._gtk_presentation_failure = f"GTK4 initialization failed: {exc}"
            return None
        self._gtk = Gtk
        self._gdk = Gdk
        self._gtk_presentation_failure = None
        return self._gtk

    def _init_gtk4(self) -> tuple[Any, Any]:
        gi.require_version("Gtk", "4.0")
        gi.require_version("Gdk", "4.0")
        from gi.repository import Gdk, Gtk

        self._initialize_gtk(Gtk)
        return Gtk, Gdk

    @staticmethod
    def _initialize_gtk(Gtk: Any) -> None:
        if hasattr(Gtk, "init_check"):
            try:
                init_result = Gtk.init_check()
            except TypeError:
                init_result = Gtk.init_check([])
            gtk_initialized = (
                bool(init_result[0])
                if isinstance(init_result, tuple)
                else bool(init_result)
            )
            if not gtk_initialized:
                raise RuntimeError("Gtk.init_check returned False")
        else:
            try:
                Gtk.init()
            except TypeError:
                Gtk.init([])

    @staticmethod
    def _set_property_if_supported(element: Any, property_name: str, value: Any) -> None:
        if element is None:
            return
        try:
            if element.find_property(property_name) is None:
                return
        except Exception:
            return
        try:
            element.set_property(property_name, value)
        except Exception as exc:
            logger.debug("Could not set %s on %s: %s", property_name, element, exc)

    def _create_gtk_playbin_pipeline(
        self,
        uri: str,
        x: int,
        y: int,
        w: int,
        h: int,
        *,
        fit_display: bool = False,
        host_background: list[float] | tuple[float, ...] | None = None,
    ) -> Any | None:
        Gtk = self._ensure_gtk()
        if Gtk is None:
            self._gtk_presentation_failure = (
                self._gtk_presentation_failure or "GTK4 could not be initialized"
            )
            return None

        playbin = Gst.ElementFactory.make("playbin", "player")
        video_sink = Gst.ElementFactory.make("gtk4paintablesink", "sink")
        audio_sink = Gst.ElementFactory.make("fakesink", "audiosink")
        if playbin is None or video_sink is None or audio_sink is None:
            logger.warning(
                "Could not create playbin/gtk4paintablesink/fakesink elements."
            )
            self._gtk_presentation_failure = (
                "Could not create playbin, gtk4paintablesink, or fakesink"
            )
            return None

        self._set_property_if_supported(audio_sink, "sync", False)
        self._set_property_if_supported(video_sink, "show-preroll-frame", True)

        try:
            playbin.set_property("uri", uri)
            playbin.set_property("flags", 0x00000001)
            playbin.set_property("video-sink", video_sink)
            playbin.set_property("audio-sink", audio_sink)
        except Exception as exc:
            logger.warning("Could not configure GTK playbin pipeline: %s", exc)
            self._gtk_presentation_failure = f"Could not configure GTK playbin: {exc}"
            return None

        try:
            paintable = video_sink.get_property("paintable")
        except Exception as exc:
            logger.warning("gtk4paintablesink did not provide a paintable: %s", exc)
            self._gtk_presentation_failure = (
                f"gtk4paintablesink paintable lookup failed: {exc}"
            )
            return None
        if paintable is None:
            logger.warning("gtk4paintablesink did not provide a paintable.")
            self._gtk_presentation_failure = "gtk4paintablesink did not provide a paintable"
            return None

        self._configure_gtk_paintable(paintable)
        if not self._present_gtk_paintable_sink(
            Gtk,
            video_sink,
            paintable,
            x,
            y,
            w,
            h,
            set_sink_window_size=True,
            content_fit="fill" if fit_display else "contain",
            host_background=host_background,
        ):
            self._gtk_presentation_failure = (
                self._gtk_presentation_failure or "GTK4 paintable window presentation failed"
            )
            return None
        return playbin

    def _build_gtk_compatible_pipeline_description(
        self,
        uri: str,
        w: int,
        h: int,
        *,
        force_software_decoders: bool,
        fit_display: bool = False,
    ) -> str:
        force_sw = " force-sw-decoders=true" if force_software_decoders else ""

        return (
            f'uridecodebin name=decoder uri="{uri}"{force_sw} '
            "decoder. ! "
            "queue name=video_queue ! "
            "videoconvert ! "
            "video/x-raw,format=RGBA,pixel-aspect-ratio=1/1 ! "
            "gtk4paintablesink name=sink"
        )

    def _create_gtk_compatible_pipeline(
        self,
        uri: str,
        x: int,
        y: int,
        w: int,
        h: int,
        *,
        force_software_decoders: bool,
        fit_display: bool = False,
        host_background: list[float] | tuple[float, ...] | None = None,
    ) -> Any | None:
        Gtk = self._ensure_gtk()
        if Gtk is None:
            self._gtk_presentation_failure = (
                self._gtk_presentation_failure or "GTK4 could not be initialized"
            )
            return None

        _, _, widget_w, widget_h = self._gtk_video_widget_geometry(
            x,
            y,
            w,
            h,
        )
        pipeline_description = self._build_gtk_compatible_pipeline_description(
            uri,
            widget_w,
            widget_h,
            force_software_decoders=force_software_decoders,
            fit_display=fit_display,
        )
        logger.info(
            "GTK-compatible video pipeline for %s,%s %sx%s fit_display=%s: %s",
            x,
            y,
            w,
            h,
            fit_display,
            pipeline_description,
        )

        try:
            pipeline = Gst.parse_launch(pipeline_description)
        except Exception as exc:
            logger.warning("Could not create GTK-compatible pipeline: %s", exc)
            self._gtk_presentation_failure = (
                f"Could not create GTK-compatible pipeline: {exc}"
            )
            return None

        try:
            video_sink = pipeline.get_by_name("sink")
        except Exception as exc:
            logger.warning("GTK-compatible pipeline did not expose a sink: %s", exc)
            self._gtk_presentation_failure = (
                f"GTK-compatible pipeline did not expose a sink: {exc}"
            )
            return None
        if video_sink is None:
            logger.warning("GTK-compatible pipeline did not expose a sink.")
            self._gtk_presentation_failure = "GTK-compatible pipeline did not expose a sink"
            return None

        self._set_property_if_supported(video_sink, "show-preroll-frame", True)
        try:
            paintable = video_sink.get_property("paintable")
        except Exception as exc:
            logger.warning("gtk4paintablesink did not provide a paintable: %s", exc)
            self._gtk_presentation_failure = (
                f"gtk4paintablesink paintable lookup failed: {exc}"
            )
            return None
        if paintable is None:
            logger.warning("gtk4paintablesink did not provide a paintable.")
            self._gtk_presentation_failure = "gtk4paintablesink did not provide a paintable"
            return None

        self._configure_gtk_paintable(paintable)
        if not self._present_gtk_paintable_sink(
            Gtk,
            video_sink,
            paintable,
            x,
            y,
            w,
            h,
            set_sink_window_size=True,
            content_fit="fill" if fit_display else "contain",
            host_background=host_background,
        ):
            self._gtk_presentation_failure = (
                self._gtk_presentation_failure or "GTK4 paintable window presentation failed"
            )
            return None
        return pipeline

    def _present_gtk_paintable_sink(
        self,
        Gtk: Any,
        video_sink: Any,
        paintable: Any,
        x: int,
        y: int,
        w: int,
        h: int,
        *,
        set_sink_window_size: bool,
        content_fit: str,
        host_background: list[float] | tuple[float, ...] | None = None,
    ) -> bool:
        transparent_host = self._gtk_video_host_uses_transparency()
        fullscreen_video = self._gtk_geometry_is_fullscreen(x, y, w, h)
        fixed_host = not fullscreen_video or not transparent_host
        _, _, widget_w, widget_h = self._gtk_video_widget_geometry(
            x,
            y,
            w,
            h,
        )
        picture = self._create_gtk_video_picture(Gtk, paintable, content_fit=content_fit)
        widget = picture

        self._pin_gtk_video_widget(Gtk, widget)

        if set_sink_window_size:
            self._set_property_if_supported(video_sink, "window-width", widget_w)
            self._set_property_if_supported(video_sink, "window-height", widget_h)
        logger.info(
            "GTK4 video paintable content-fit=%s widget-size=%sx%s.",
            content_fit,
            widget_w,
            widget_h,
        )
        try:
            widget.set_size_request(widget_w, widget_h)
        except Exception:
            pass
        window = Gtk.Window(title="picframe-video")
        self._configure_gtk_video_window(window, transparent=transparent_host)
        self._configure_gtk_video_host_background(
            window,
            transparent=transparent_host,
            host_background=host_background,
        )
        host = None
        if fixed_host:
            host_x, host_y, host_w, host_h = self._gtk_fixed_host_child_rect(
                x,
                y,
                w,
                h,
                fullscreen=fullscreen_video,
                transparent=transparent_host,
            )
            host = self._create_gtk_fixed_video_host(
                Gtk,
                window,
                widget,
                host_x,
                host_y,
                host_w,
                host_h,
                transparent=transparent_host,
                host_background=host_background,
            )
            window.set_child(host)
            self._apply_gtk_host_window_geometry(window, x, y, w, h)
        else:
            window.set_child(widget)
            self._apply_gtk_window_geometry(
                window,
                x,
                y,
                w,
                h,
                fullscreen=fullscreen_video,
                widget=widget,
            )
        self._present_gtk_video_window(
            window,
            fullscreen=fullscreen_video or fixed_host,
            opacity=STARTUP_GTK_WINDOW_OPACITY,
        )
        self._log_gtk_window_diagnostics(
            window,
            widget,
            x,
            y,
            w,
            h,
            fullscreen_video,
            fixed_host=fixed_host,
            host_transparent=transparent_host,
        )
        self._hide_gtk_cursor(window, widget)

        if not self._gtk_window_matches_geometry(
            window,
            x,
            y,
            w,
            h,
            fullscreen=fullscreen_video,
            widget=widget,
            fixed_host=fixed_host,
            host_transparent=transparent_host,
        ):
            logger.warning(
                "GTK video window geometry did not match requested "
                "%s,%s %sx%s; continuing with GTK4 presentation.",
                x,
                y,
                w,
                h,
            )

        self._gtk_window = window
        self._gtk_host = host
        self._gtk_sink_widget = widget
        self._gtk_video_sink = video_sink
        self._start_gtk_pump()
        logger.info("GTK4 video window geometry confirmed at %s,%s %sx%s.", x, y, w, h)
        return True

    def _create_gtk_video_picture(
        self,
        Gtk: Any,
        paintable: Any,
        *,
        content_fit: str = "contain",
    ) -> Any:
        if hasattr(Gtk.Picture, "new_for_paintable"):
            picture = Gtk.Picture.new_for_paintable(paintable)
        else:
            picture = Gtk.Picture()
            picture.set_paintable(paintable)
        try:
            picture.set_can_shrink(True)
        except Exception:
            pass
        if hasattr(Gtk, "ContentFit"):
            try:
                fit = Gtk.ContentFit.FILL if content_fit == "fill" else Gtk.ContentFit.CONTAIN
                picture.set_content_fit(fit)
            except Exception:
                pass
        else:
            try:
                picture.set_keep_aspect_ratio(content_fit != "fill")
            except Exception:
                pass
        return picture

    @staticmethod
    def _pin_gtk_video_widget(Gtk: Any, widget: Any) -> None:
        try:
            widget.set_hexpand(True)
            widget.set_vexpand(True)
        except Exception:
            pass
        try:
            widget.set_halign(Gtk.Align.START)
            widget.set_valign(Gtk.Align.START)
        except Exception:
            pass

    def _configure_gtk_paintable(self, paintable: Any) -> None:
        self._set_property_if_supported(paintable, "force-aspect-ratio", True)
        try:
            force_aspect_ratio = paintable.get_property("force-aspect-ratio")
        except Exception:
            force_aspect_ratio = "unknown"
        logger.info("GTK4 paintable force-aspect-ratio=%s.", force_aspect_ratio)

    def _gtk_geometry_is_fullscreen(self, x: int, y: int, w: int, h: int) -> bool:
        if x != 0 or y != 0:
            return False
        if w <= 0 or h <= 0:
            return True

        monitor_geometry = self._gtk_primary_monitor_geometry()
        if monitor_geometry is None:
            return False
        monitor_x, monitor_y, monitor_w, monitor_h = monitor_geometry
        return monitor_x == 0 and monitor_y == 0 and monitor_w == w and monitor_h == h

    def _gtk_primary_monitor_geometry(self) -> tuple[int, int, int, int] | None:
        monitor = self._gtk_primary_monitor()
        if monitor is None:
            return None
        try:
            geometry = monitor.get_geometry()
            return (
                int(getattr(geometry, "x", 0)),
                int(getattr(geometry, "y", 0)),
                int(getattr(geometry, "width")),
                int(getattr(geometry, "height")),
            )
        except Exception:
            return None

    def _gtk_primary_monitor(self) -> Any | None:
        Gdk = self._gdk
        if Gdk is None:
            return None
        try:
            display = Gdk.Display.get_default()
            if display is None:
                return None
            monitor = None
            if hasattr(display, "get_primary_monitor"):
                monitor = display.get_primary_monitor()
            if monitor is None and hasattr(display, "get_monitor"):
                monitor = display.get_monitor(0)
            if monitor is None and hasattr(display, "get_monitors"):
                monitors = display.get_monitors()
                if hasattr(monitors, "get_item"):
                    monitor = monitors.get_item(0)
                elif hasattr(monitors, "__getitem__"):
                    monitor = monitors[0]
            return monitor
        except Exception:
            return None

    def _configure_gtk_video_window(self, window: Any, *, transparent: bool = True) -> None:
        window.set_decorated(False)
        set_app_paintable = getattr(window, "set_app_paintable", None)
        if callable(set_app_paintable):
            set_app_paintable(transparent)
        for method_name, value in (
            ("set_deletable", False),
            ("set_resizable", False),
            ("set_hide_on_close", True),
            ("set_skip_taskbar_hint", True),
            ("set_skip_pager_hint", True),
            ("set_focusable", True),
            ("set_can_focus", True),
            ("set_focus_on_map", True),
        ):
            method = getattr(window, method_name, None)
            if not callable(method):
                continue
            try:
                method(value)
            except Exception:
                pass

    def _gtk_video_host_uses_transparency(self) -> bool:
        if self._raspberry_pi_model_family(self._hardware_model) is not None:
            return True
        desktop_text = " ".join(
            os.environ.get(name, "")
            for name in ("XDG_CURRENT_DESKTOP", "DESKTOP_SESSION", "WAYLAND_DISPLAY")
        ).lower()
        if "labwc" in desktop_text:
            return True
        return self._find_labwc_pid() is not None

    @staticmethod
    def _find_labwc_pid() -> int | None:
        pid = os.getpid()
        seen: set[int] = set()
        while pid > 1 and pid not in seen:
            seen.add(pid)
            try:
                with open(f"/proc/{pid}/comm", encoding="utf-8") as comm_file:
                    comm = comm_file.read().strip()
                if comm == "labwc":
                    return pid
                with open(f"/proc/{pid}/status", encoding="utf-8") as status_file:
                    status = status_file.read()
            except OSError:
                return None

            parent_pid = None
            for line in status.splitlines():
                if line.startswith("PPid:"):
                    try:
                        parent_pid = int(line.split()[1])
                    except (IndexError, ValueError):
                        return None
                    break
            if parent_pid is None or parent_pid == pid:
                return None
            pid = parent_pid
        return None

    def _configure_gtk_video_host_background(
        self,
        window: Any,
        *,
        transparent: bool,
        host_background: list[float] | tuple[float, ...] | None = None,
    ) -> None:
        Gdk = self._gdk
        Gtk = self._gtk
        if Gdk is None or Gtk is None:
            return
        self._set_gtk_video_host_background(
            window,
            transparent=transparent,
            host_background=host_background,
        )
        logger.info(
            "GTK video host background=%s.",
            "transparent"
            if transparent
            else self._gtk_opaque_host_background_css(host_background),
        )

    def _set_gtk_video_host_background(
        self,
        widget: Any,
        *,
        transparent: bool,
        host_background: list[float] | tuple[float, ...] | None = None,
    ) -> None:
        Gdk = self._gdk
        Gtk = self._gtk
        if Gdk is None or Gtk is None:
            return
        try:
            display = Gdk.Display.get_default()
            if display is None:
                return
            opaque_background = self._gtk_opaque_host_background_css(host_background)
            css_provider = Gtk.CssProvider()
            css_provider.load_from_data(
                f"""
                window.{GTK_TRANSPARENT_HOST_CLASS},
                .{GTK_TRANSPARENT_HOST_CLASS} {{
                    background-color: rgba(0, 0, 0, 0);
                }}
                window.{GTK_OPAQUE_HOST_CLASS},
                .{GTK_OPAQUE_HOST_CLASS} {{
                    background-color: {opaque_background};
                }}
                """.encode("utf-8")
            )
            Gtk.StyleContext.add_provider_for_display(
                display,
                css_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )
            selected_class = (
                GTK_TRANSPARENT_HOST_CLASS if transparent else GTK_OPAQUE_HOST_CLASS
            )
            remove_css_class = getattr(widget, "remove_css_class", None)
            if callable(remove_css_class):
                remove_css_class(GTK_TRANSPARENT_HOST_CLASS)
                remove_css_class(GTK_OPAQUE_HOST_CLASS)
            add_css_class = getattr(widget, "add_css_class", None)
            if callable(add_css_class):
                add_css_class(selected_class)
        except Exception as exc:
            logger.debug("Could not configure GTK video host background: %s", exc)

    @staticmethod
    def _gtk_opaque_host_background_css(
        host_background: list[float] | tuple[float, ...] | None,
    ) -> str:
        try:
            if host_background is None or len(host_background) < 3:
                return "rgba(0, 0, 0, 1)"
            rgb = tuple(float(host_background[index]) for index in range(3))
        except (TypeError, ValueError):
            return "rgba(0, 0, 0, 1)"
        channels = tuple(round(max(0.0, min(1.0, value)) * 255) for value in rgb)
        return f"rgba({channels[0]}, {channels[1]}, {channels[2]}, 1)"

    def _create_gtk_fixed_video_host(
        self,
        Gtk: Any,
        window: Any,
        widget: Any,
        x: int,
        y: int,
        w: int,
        h: int,
        *,
        transparent: bool = True,
        host_background: list[float] | tuple[float, ...] | None = None,
    ) -> Any:
        host = Gtk.Fixed()
        widget_x, widget_y, widget_w, widget_h = self._gtk_video_widget_geometry(
            x,
            y,
            w,
            h,
        )
        self._set_gtk_video_host_background(
            host,
            transparent=transparent,
            host_background=host_background,
        )
        try:
            host.set_hexpand(True)
            host.set_vexpand(True)
        except Exception:
            pass
        self._pin_gtk_video_widget(Gtk, widget)
        try:
            widget.set_size_request(widget_w, widget_h)
        except Exception:
            pass
        try:
            host.put(widget, widget_x, widget_y)
        except Exception:
            logger.warning(
                "Could not place GTK video widget at %s,%s; custom geometry may fail.",
                widget_x,
                widget_y,
            )
        try:
            _, _, host_w, host_h = self._gtk_video_host_geometry(x, y, w, h)
            window.set_default_size(host_w, host_h)
            host.set_size_request(host_w, host_h)
        except Exception:
            pass
        return host

    def _apply_gtk_eos_opacity_probe(self) -> None:
        if self._gtk_window is None:
            return
        try:
            if self.pipeline is not None:
                self.pipeline.set_state(Gst.State.PAUSED)
        except Exception as exc:
            logger.debug("Could not pause GTK4 video pipeline at EOS: %s", exc)
        try:
            set_opacity = getattr(self._gtk_window, "set_opacity", None)
            if not callable(set_opacity):
                return
            logger.info(
                "GTK4 EOS opacity probe: setting window opacity to %.3f.",
                EOS_GTK_WINDOW_OPACITY,
            )
            set_opacity(EOS_GTK_WINDOW_OPACITY)
            self._pump_gtk_events()
        except Exception as exc:
            logger.debug("Could not apply GTK4 EOS opacity probe: %s", exc)

    def _gtk_video_host_geometry(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
    ) -> tuple[int, int, int, int]:
        monitor_geometry = self._gtk_primary_monitor_geometry()
        if monitor_geometry is not None:
            return monitor_geometry
        return (0, 0, max(1, w, x + w), max(1, h, y + h))

    def _gtk_video_widget_geometry(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
    ) -> tuple[int, int, int, int]:
        if w > 0 and h > 0:
            return (x, y, w, h)
        _, _, host_w, host_h = self._gtk_video_host_geometry(x, y, w, h)
        return (0, 0, host_w, host_h)

    def _gtk_fixed_host_child_rect(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        *,
        fullscreen: bool,
        transparent: bool,
    ) -> tuple[int, int, int, int]:
        if fullscreen and not transparent:
            _, _, host_w, host_h = self._gtk_video_host_geometry(x, y, w, h)
            return (0, 0, host_w, host_h)
        return (x, y, w, h)

    def _apply_gtk_host_window_geometry(
        self,
        window: Any,
        x: int,
        y: int,
        w: int,
        h: int,
    ) -> None:
        _, _, host_w, host_h = self._gtk_video_host_geometry(x, y, w, h)
        self._apply_gtk_window_geometry(
            window,
            0,
            0,
            host_w,
            host_h,
            fullscreen=True,
        )

    @staticmethod
    def _apply_gtk_window_geometry(
        window: Any,
        x: int,
        y: int,
        w: int,
        h: int,
        *,
        fullscreen: bool,
        widget: Any | None = None,
    ) -> None:
        if fullscreen:
            if w > 0 and h > 0:
                window.set_default_size(w, h)
                if widget is not None:
                    try:
                        widget.set_size_request(w, h)
                    except Exception:
                        pass
            set_fullscreened = getattr(window, "set_fullscreened", None)
            if callable(set_fullscreened):
                set_fullscreened(True)
            window.fullscreen()
            return
        if widget is not None:
            try:
                widget.set_size_request(w, h)
            except Exception:
                pass
        window.set_default_size(w, h)

    def _present_gtk_video_window(
        self,
        window: Any,
        *,
        fullscreen: bool,
        opacity: float = 1.0,
    ) -> None:
        try:
            set_opacity = getattr(window, "set_opacity", None)
            if callable(set_opacity):
                set_opacity(opacity)
            if fullscreen:
                set_fullscreened = getattr(window, "set_fullscreened", None)
                if callable(set_fullscreened):
                    set_fullscreened(True)
                window.fullscreen()
            present = getattr(window, "present", None)
            if callable(present):
                present()
            self._focus_gtk_video_window(window)
            if fullscreen:
                self._pump_gtk_events()
                window.fullscreen()
                if callable(present):
                    present()
                self._focus_gtk_video_window(window)
        except Exception as exc:
            logger.debug("Could not present GTK video window: %s", exc)
        self._pump_gtk_events()

    def _reveal_gtk_video_window(self) -> None:
        window = self._gtk_window
        if window is None:
            return
        try:
            set_opacity = getattr(window, "set_opacity", None)
            if callable(set_opacity):
                set_opacity(1.0)
            present = getattr(window, "present", None)
            if callable(present):
                present()
            self._focus_gtk_video_window(window)
        except Exception as exc:
            logger.debug("Could not reveal GTK video window: %s", exc)
        self._pump_gtk_events()

    @staticmethod
    def _focus_gtk_video_window(window: Any) -> None:
        for method_name in ("grab_focus", "present"):
            method = getattr(window, method_name, None)
            if callable(method):
                try:
                    method()
                except Exception:
                    pass

    def _log_gtk_window_diagnostics(
        self,
        window: Any,
        widget: Any,
        x: int,
        y: int,
        w: int,
        h: int,
        fullscreen: bool,
        *,
        fixed_host: bool = False,
        host_transparent: bool = True,
    ) -> None:
        try:
            actual_w, actual_h = window.get_size()
        except Exception:
            actual_w, actual_h = None, None
        try:
            actual_x, actual_y = window.get_position()
        except Exception:
            actual_x, actual_y = None, None
        try:
            allocation = widget.get_allocation()
            widget_w = int(getattr(allocation, "width"))
            widget_h = int(getattr(allocation, "height"))
        except Exception:
            widget_w, widget_h = None, None
        try:
            widget_pos = widget.translate_coordinates(window, 0, 0)
            if widget_pos is None:
                widget_x, widget_y = None, None
            else:
                widget_x, widget_y = int(widget_pos[0]), int(widget_pos[1])
        except Exception:
            widget_x, widget_y = None, None

        logger.info(
            "GTK video window mode=%s requested=%s,%s %sx%s actual=%s,%s %sx%s "
            "widget=%sx%s widget_at=%s,%s",
            "fullscreen" if fullscreen else "custom",
            x,
            y,
            w,
            h,
            actual_x,
            actual_y,
            actual_w,
            actual_h,
            widget_w,
            widget_h,
            widget_x,
            widget_y,
        )
        if fixed_host:
            logger.info(
                "GTK video uses monitor-sized %s host with fixed child placement.",
                "transparent" if host_transparent else "opaque",
            )

    def _hide_gtk_cursor(self, window: Any, widget: Any) -> None:
        try:
            for target in (widget, window):
                set_cursor_from_name = getattr(target, "set_cursor_from_name", None)
                if callable(set_cursor_from_name):
                    set_cursor_from_name("none")
        except Exception as exc:
            logger.debug("Could not hide GTK video cursor: %s", exc)

    def _gtk_window_matches_geometry(
        self,
        window: Any,
        x: int,
        y: int,
        w: int,
        h: int,
        *,
        fullscreen: bool = False,
        widget: Any | None = None,
        fixed_host: bool = False,
        host_transparent: bool = True,
    ) -> bool:
        self._pump_gtk_events()
        if fixed_host:
            if fullscreen:
                return True
            if widget is None:
                return False
            expected_x, expected_y, expected_w, expected_h = (
                self._gtk_fixed_host_child_rect(
                    x,
                    y,
                    w,
                    h,
                    fullscreen=fullscreen,
                    transparent=host_transparent,
                )
            )
            try:
                allocation = widget.get_allocation()
                widget_w = int(getattr(allocation, "width"))
                widget_h = int(getattr(allocation, "height"))
            except Exception:
                return False
            if widget_w != expected_w or widget_h != expected_h:
                return False
            try:
                widget_pos = widget.translate_coordinates(window, 0, 0)
            except Exception:
                widget_pos = None
            if widget_pos is None:
                return True
            return int(widget_pos[0]) == expected_x and int(widget_pos[1]) == expected_y

        if fullscreen:
            return True

        return True

    def _start_gtk_pump(self) -> None:
        if self._gtk_pump_source_id is not None or not GST_AVAILABLE:
            return
        try:
            self._gtk_pump_source_id = GLib.timeout_add(16, self._pump_gtk_events_tick)
        except Exception:
            self._gtk_pump_source_id = None

    def _stop_gtk_pump(self) -> None:
        if self._gtk_pump_source_id is None or not GST_AVAILABLE:
            return
        try:
            GLib.source_remove(self._gtk_pump_source_id)
        except Exception:
            pass
        self._gtk_pump_source_id = None

    def _pump_gtk_events_tick(self) -> bool:
        self._pump_gtk_events()
        return self._gtk_window is not None

    def _pump_gtk_events(self) -> None:
        if self._gtk is None:
            return
        try:
            context = GLib.MainContext.default()
            while context.pending():
                context.iteration(False)
        except Exception:
            pass

    def _destroy_gtk_video_window(self) -> None:
        self._stop_gtk_pump()
        if self._gtk_window is not None:
            try:
                set_visible = getattr(self._gtk_window, "set_visible", None)
                if callable(set_visible):
                    set_visible(False)
                self._gtk_window.destroy()
            except Exception as exc:
                logger.debug("Could not destroy GTK video window: %s", exc)
        self._gtk_window = None
        self._gtk_host = None
        self._gtk_sink_widget = None
        self._gtk_video_sink = None
        self._pump_gtk_events()

    def _select_pipeline_variant(
        self,
        uri: str,
        sink_name: str,
        force_software_decoders: bool,
        stream_facts: VideoStreamFacts | None = None,
        max_software_decode_resolution: str | None = None,
    ) -> str:
        return self._select_playback_decision(
            uri,
            sink_name,
            force_software_decoders=force_software_decoders,
            max_software_decode_resolution=max_software_decode_resolution,
            stream_facts=stream_facts,
        ).pipeline_variant

    def _select_playback_decision(
        self,
        uri: str,
        sink_name: str,
        *,
        force_software_decoders: bool,
        max_software_decode_resolution: str | None,
        stream_facts: VideoStreamFacts | None,
        fallback_reason: str | None = None,
    ) -> PlaybackDecision:
        software_limit = self._software_decode_limit(max_software_decode_resolution)
        software_limit_str = self._format_resolution_limit(software_limit)
        hardware_limit = self._known_hardware_decode_limit(stream_facts)
        hardware_limit_str = self._format_hardware_limit(hardware_limit)
        software_allowed = self._within_resolution_limit(
            stream_facts,
            software_limit,
            allow_rotation=True,
        )

        if force_software_decoders and self._requires_pi_hardware_only(stream_facts):
            return self._skip_decision(
                stream_facts,
                hardware_limit_str,
                software_limit_str,
                fallback_reason or "hardware_presentation_unsupported",
            )

        if force_software_decoders:
            if not software_allowed:
                return self._skip_decision(
                    stream_facts,
                    hardware_limit_str,
                    software_limit_str,
                    "software_limit_exceeded",
                )
            return PlaybackDecision(
                pipeline_variant=PIPELINE_COMPATIBLE,
                force_software_decoders=True,
                decision="software_fallback",
                fallback_reason=fallback_reason or "software_fallback",
                hardware_limit=hardware_limit_str,
                software_limit=software_limit_str,
            )

        hardware_rejection_reason = self._hardware_limit_rejection_reason(
            stream_facts,
            hardware_limit,
        )
        if hardware_rejection_reason is not None:
            if self._requires_pi_hardware_only(stream_facts):
                return self._skip_decision(
                    stream_facts,
                    hardware_limit_str,
                    software_limit_str,
                    hardware_rejection_reason,
                )
            if software_allowed:
                return PlaybackDecision(
                    pipeline_variant=PIPELINE_COMPATIBLE,
                    force_software_decoders=True,
                    decision="software_fallback",
                    fallback_reason=hardware_rejection_reason,
                    hardware_limit=hardware_limit_str,
                    software_limit=software_limit_str,
                )
            return self._skip_decision(
                stream_facts,
                hardware_limit_str,
                software_limit_str,
                hardware_rejection_reason,
            )

        hardware_available = self._hardware_decode_available_for_facts(stream_facts)
        if not hardware_available:
            if self._requires_pi_hardware_only(stream_facts):
                return self._skip_decision(
                    stream_facts,
                    hardware_limit_str,
                    software_limit_str,
                    "hardware_decoder_unavailable",
                )
            if software_allowed:
                return PlaybackDecision(
                    pipeline_variant=PIPELINE_COMPATIBLE,
                    force_software_decoders=True,
                    decision="software_fallback",
                    fallback_reason="hardware_decoder_unavailable",
                    hardware_limit=hardware_limit_str,
                    software_limit=software_limit_str,
                )
            return self._skip_decision(
                stream_facts,
                hardware_limit_str,
                software_limit_str,
                "hardware_decoder_unavailable",
            )

        unsupported_presentation = self._unsupported_hardware_presentation_reason(
            stream_facts,
            sink_name,
            uri,
        )
        if unsupported_presentation is not None:
            return self._skip_decision(
                stream_facts,
                hardware_limit_str,
                software_limit_str,
                unsupported_presentation,
            )

        if sink_name == "waylandsink":
            if self._uses_playbin_hardware_presentation(stream_facts):
                return PlaybackDecision(
                    pipeline_variant=PIPELINE_HARDWARE_PLAYBIN,
                    force_software_decoders=False,
                    decision="hardware_playbin",
                    hardware_limit=hardware_limit_str,
                    software_limit=software_limit_str,
                )
            if self._requires_compatible_hardware_presentation(stream_facts):
                return PlaybackDecision(
                    pipeline_variant=PIPELINE_COMPATIBLE,
                    force_software_decoders=False,
                    decision="hardware_compatible",
                    fallback_reason="hardware_direct_unsupported_caps",
                    hardware_limit=hardware_limit_str,
                    software_limit=software_limit_str,
                )
            return PlaybackDecision(
                pipeline_variant=PIPELINE_HARDWARE_DIRECT,
                force_software_decoders=False,
                decision="hardware_direct",
                hardware_limit=hardware_limit_str,
                software_limit=software_limit_str,
            )

        return PlaybackDecision(
            pipeline_variant=PIPELINE_COMPATIBLE,
            force_software_decoders=False,
            decision="hardware_compatible",
            hardware_limit=hardware_limit_str,
            software_limit=software_limit_str,
        )

    def _hardware_decode_available_for_uri(self, uri: str) -> bool:
        stream_facts, _reason = self._discover_video_stream_facts(uri)
        return self._hardware_decode_available_for_facts(stream_facts)

    def _hardware_decode_available_for_caps(self, caps: Any) -> bool:
        caps_str = caps.to_string()
        if "video/x-h264" in caps_str and find_best_element(
            ["v4l2h264dec", "v4l2slh264dec"]
        ):
            return True
        if "video/x-h265" in caps_str and find_best_element(["v4l2slh265dec"]):
            return True

        registry = Gst.Registry.get()
        factories = registry.get_feature_list(Gst.ElementFactory)
        for factory in factories:
            klass = factory.get_metadata(Gst.ELEMENT_METADATA_KLASS)
            if not (klass and "Decoder" in klass and "Video" in klass and "Hardware" in klass):
                continue
            for template in factory.get_static_pad_templates():
                if template.direction != Gst.PadDirection.SINK:
                    continue
                template_caps = template.get_caps()
                if template_caps and template_caps.can_intersect(caps):
                    return True
        return False

    def _hardware_decode_available_for_facts(
        self,
        stream_facts: VideoStreamFacts | None,
    ) -> bool:
        if stream_facts is None or stream_facts.caps is None:
            return False
        codec = self._normalized_codec(stream_facts.codec) or self._codec_from_caps_string(
            stream_facts.caps_string
        )
        if codec == "h264":
            return find_best_element(["v4l2h264dec", "v4l2slh264dec"]) is not None
        if codec == "h265":
            return find_best_element(["v4l2slh265dec"]) is not None
        return self._hardware_decode_available_for_caps(stream_facts.caps)

    def _requires_compatible_hardware_presentation(
        self,
        stream_facts: VideoStreamFacts | None,
    ) -> bool:
        if stream_facts is None or self._normalized_codec(stream_facts.codec) != "h265":
            return False
        caps_string = (stream_facts.caps_string or "").lower()
        return (
            "profile=(string)main-10" in caps_string
            or "bit-depth-luma=(uint)10" in caps_string
            or "bt2100" in caps_string
        )

    def _requires_pi_hardware_only(
        self,
        stream_facts: VideoStreamFacts | None,
    ) -> bool:
        return (
            self._raspberry_pi_model_family(self._hardware_model) is not None
            and self._requires_compatible_hardware_presentation(stream_facts)
        )

    def _uses_playbin_hardware_presentation(
        self,
        stream_facts: VideoStreamFacts | None,
    ) -> bool:
        return (
            stream_facts is not None
            and self._normalized_codec(stream_facts.codec) == "h265"
            and not self._requires_compatible_hardware_presentation(stream_facts)
        )

    def _unsupported_hardware_presentation_reason(
        self,
        stream_facts: VideoStreamFacts | None,
        sink_name: str,
        uri: str,
    ) -> str | None:
        if sink_name != "waylandsink":
            return None
        if stream_facts is None or self._normalized_codec(stream_facts.codec) != "h265":
            return None

        model = self._hardware_model.lower()
        is_pi4_like = (
            "raspberry pi 4" in model
            or "raspberry pi 400" in model
            or "compute module 4" in model
        )
        if not is_pi4_like:
            return None

        if self._requires_compatible_hardware_presentation(stream_facts):
            return "hardware_presentation_unsupported"
        container = stream_facts.container or self._container_hint_from_uri(uri)
        if (
            stream_facts.framerate is not None
            and stream_facts.framerate > 30.0
            and container in {"mov", "quicktime"}
        ):
            return "hardware_quicktime_framerate_unsupported"
        return None

    def _known_hardware_decode_limit(
        self,
        stream_facts: VideoStreamFacts | None,
    ) -> DecodeHardwareLimit | None:
        if stream_facts is None or stream_facts.codec is None:
            return None

        model_family = self._raspberry_pi_model_family(self._hardware_model)
        codec = self._normalized_codec(stream_facts.codec) or self._codec_from_caps_string(
            stream_facts.caps_string
        )
        if model_family is None or codec is None:
            return None

        return RPI_HARDWARE_DECODE_LIMITS.get(model_family, {}).get(codec)

    @staticmethod
    def _raspberry_pi_model_family(model: str) -> str | None:
        normalized = model.strip("\x00\n ").lower()
        if "raspberry pi" not in normalized and "compute module" not in normalized:
            return None
        if (
            "raspberry pi 5" in normalized
            or "raspberry pi 500" in normalized
            or "compute module 5" in normalized
        ):
            return "pi5"
        if (
            "raspberry pi 4" in normalized
            or "raspberry pi 400" in normalized
            or "compute module 4" in normalized
        ):
            return "pi4"
        if "raspberry pi 3" in normalized or "compute module 3" in normalized:
            return "pi3"
        if "raspberry pi zero 2" in normalized:
            return "zero2"
        if "raspberry pi zero" in normalized:
            return "zero"
        return None

    @staticmethod
    def _normalized_codec(codec: str | None) -> str | None:
        if codec is None:
            return None
        normalized = codec.lower()
        if normalized == "hevc":
            return "h265"
        return normalized

    def _software_decode_limit(
        self,
        value: str | None,
    ) -> DecodeResolutionLimit | None:
        raw_value = value or DEFAULT_SOFTWARE_DECODE_LIMIT
        limit = self._parse_resolution_limit(raw_value)
        if limit is None:
            logger.warning(
                "Invalid max software decode resolution %r; using default %s.",
                raw_value,
                DEFAULT_SOFTWARE_DECODE_LIMIT,
            )
            return self._parse_resolution_limit(DEFAULT_SOFTWARE_DECODE_LIMIT)
        return limit

    @staticmethod
    def _parse_resolution_limit(value: str | None) -> DecodeResolutionLimit | None:
        if value is None:
            return None
        normalized = value.strip().lower().replace(" ", "")
        if normalized in {"", "none", "off", "unlimited"}:
            return None
        parts = normalized.split("x", maxsplit=1)
        if len(parts) != 2:
            return None
        try:
            width = int(parts[0])
            height = int(parts[1])
        except ValueError:
            return None
        if width <= 0 or height <= 0:
            return None
        return DecodeResolutionLimit(width=width, height=height)

    @staticmethod
    def _format_resolution_limit(limit: DecodeResolutionLimit | None) -> str | None:
        if limit is None:
            return None
        return f"{limit.width}x{limit.height}"

    @staticmethod
    def _format_hardware_limit(limit: DecodeHardwareLimit | None) -> str | None:
        if limit is None:
            return None
        if limit.max_fps is None:
            return f"{limit.width}x{limit.height}"
        return f"{limit.width}x{limit.height}@{limit.max_fps:g}"

    @staticmethod
    def _within_resolution_limit(
        stream_facts: VideoStreamFacts | None,
        limit: DecodeResolutionLimit | DecodeHardwareLimit | None,
        *,
        allow_rotation: bool,
    ) -> bool:
        if stream_facts is None or limit is None:
            return True
        if stream_facts.width is None or stream_facts.height is None:
            return True

        width = stream_facts.width
        height = stream_facts.height
        if width <= limit.width and height <= limit.height:
            return True
        return allow_rotation and width <= limit.height and height <= limit.width

    def _hardware_limit_rejection_reason(
        self,
        stream_facts: VideoStreamFacts | None,
        limit: DecodeHardwareLimit | None,
    ) -> str | None:
        if limit is None:
            return "hardware_unsupported_for_model"
        if not self._within_resolution_limit(
            stream_facts,
            limit,
            allow_rotation=False,
        ):
            return "hardware_limit_exceeded"
        if not self._within_hardware_framerate_limit(stream_facts, limit):
            return "hardware_framerate_exceeded"
        return None

    @staticmethod
    def _within_hardware_framerate_limit(
        stream_facts: VideoStreamFacts | None,
        limit: DecodeHardwareLimit | None,
    ) -> bool:
        if (
            stream_facts is None
            or stream_facts.framerate is None
            or limit is None
            or limit.max_fps is None
        ):
            return True
        return stream_facts.framerate <= limit.max_fps + 0.01

    def _skip_decision(
        self,
        stream_facts: VideoStreamFacts | None,
        hardware_limit: str | None,
        software_limit: str | None,
        fallback_reason: str,
    ) -> PlaybackDecision:
        dimensions = self._format_stream_dimensions(stream_facts)
        details = (
            f"Skipping video {dimensions}: exceeds safe hardware decode limit "
            f"{hardware_limit or 'unknown'} and software decode limit "
            f"{software_limit or 'unknown'}."
        )
        if fallback_reason == "hardware_unsupported_for_model":
            details = (
                f"Skipping video {dimensions}: this codec is not hardware decoded "
                "on this Raspberry Pi model or host, and software decode limit "
                f"is {software_limit or 'unknown'}."
            )
        if fallback_reason == "hardware_decoder_unavailable":
            details = (
                f"Skipping video {dimensions}: no matching GStreamer V4L2 "
                "hardware decoder is available, and software decode limit "
                f"is {software_limit or 'unknown'}."
            )
        if fallback_reason == "hardware_limit_exceeded":
            details = (
                f"Skipping video {dimensions}: exceeds safe hardware decode limit "
                f"{hardware_limit or 'unknown'} and software decode limit "
                f"{software_limit or 'unknown'}."
            )
        if fallback_reason == "hardware_framerate_exceeded":
            details = (
                f"Skipping video {dimensions}"
                f"{self._format_stream_framerate(stream_facts)}: exceeds safe "
                f"hardware decode limit {hardware_limit or 'unknown'} and "
                f"software decode limit {software_limit or 'unknown'}."
            )
        if fallback_reason == "hardware_presentation_unsupported":
            details = (
                f"Skipping video {dimensions}: HEVC Main 10/HDR hardware decode "
                "is available, but the decoded format cannot be presented smoothly "
                "on this Raspberry Pi display path."
            )
        if fallback_reason == "hardware_framerate_unsupported":
            details = (
                f"Skipping video {dimensions}"
                f"{self._format_stream_framerate(stream_facts)}: HEVC hardware "
                "decode is available, but this Raspberry Pi 4 Wayland display "
                "path is only validated up to 30 fps."
            )
        if fallback_reason == "hardware_quicktime_framerate_unsupported":
            details = (
                f"Skipping video {dimensions}"
                f"{self._format_stream_framerate(stream_facts)}: HEVC hardware "
                "decode is available, but this Raspberry Pi 4 Wayland display "
                "path cannot present this MOV/QuickTime 60 fps stream smoothly."
            )
        if fallback_reason == "software_limit_exceeded":
            details = (
                f"Skipping video {dimensions}: no suitable hardware decoder path "
                f"and software decode limit is {software_limit or 'unknown'}."
            )
        return PlaybackDecision(
            pipeline_variant=PIPELINE_SKIPPED,
            force_software_decoders=False,
            decision="skip",
            fallback_reason=fallback_reason,
            skip_reason=details,
            error_code=UNSUPPORTED_MEDIA_CODE,
            hardware_limit=hardware_limit,
            software_limit=software_limit,
        )

    @staticmethod
    def _format_stream_dimensions(stream_facts: VideoStreamFacts | None) -> str:
        if (
            stream_facts is None
            or stream_facts.width is None
            or stream_facts.height is None
        ):
            return "with unknown resolution"
        return f"{stream_facts.width}x{stream_facts.height}"

    @staticmethod
    def _format_stream_framerate(stream_facts: VideoStreamFacts | None) -> str:
        if stream_facts is None or stream_facts.framerate is None:
            return ""
        return f" at {stream_facts.framerate:g} fps"

    @staticmethod
    def _codec_from_caps_string(caps_string: str | None) -> str | None:
        if not caps_string:
            return None
        if "video/x-h264" in caps_string:
            return "h264"
        if "video/x-h265" in caps_string:
            return "h265"
        return None

    @staticmethod
    def _container_hint_from_uri(uri: str) -> str | None:
        path = unquote(urlparse(uri).path or uri)
        suffix = os.path.splitext(path)[1].lower()
        if suffix in {".mov", ".qt"}:
            return "mov"
        if suffix in {".mkv", ".mk3d", ".mka", ".mks"}:
            return "matroska"
        if suffix in {".mp4", ".m4v"}:
            return "mp4"
        return suffix.removeprefix(".") or None

    def _reset_pipeline_telemetry(
        self,
        pipeline_variant: str,
        sink_name: str,
        *,
        decision: str | None = None,
        hardware_limit: str | None = None,
        software_limit: str | None = None,
    ) -> None:
        self._current_pipeline_variant = pipeline_variant
        self._current_sink_name = sink_name
        self._selected_decoder_name = None
        self._selected_decoder_is_hardware = False
        self._last_video_caps = None
        self._last_uses_dmabuf = False
        self._current_decision = decision
        self._current_hardware_limit = hardware_limit
        self._current_software_limit = software_limit
        self._first_frame_event_sent = False
        self._first_frame_probe_started_at = 0.0

    def _send_video_diagnostics(
        self,
        *,
        stage: str,
        fallback_reason: str | None = None,
    ) -> None:
        self._send_event(
            VideoDiagnosticsEvent(
                pipeline_variant=self._current_pipeline_variant,
                stage=stage,
                sink=self._current_sink_name,
                decoder=self._selected_decoder_name,
                decoder_is_hardware=self._selected_decoder_is_hardware,
                caps=self._last_video_caps,
                uses_dmabuf=self._last_uses_dmabuf,
                fallback_reason=fallback_reason,
                hardware_limit=self._current_hardware_limit,
                software_limit=self._current_software_limit,
                decision=self._current_decision,
            )
        )

    @staticmethod
    def _caps_uses_dmabuf(caps: Any) -> bool:
        return "memory:DMABuf" in caps.to_string()

    def _connect_pipeline_telemetry_hooks(self) -> None:
        if self.pipeline is None:
            return

        decoder = self.pipeline.get_by_name("decoder")
        if decoder is not None:
            decoder.connect("autoplug-select", self._on_autoplug_select)
            decoder.connect("pad-added", self._on_decoder_pad_added)
            decoder.connect("element-added", self._on_element_added)
            return

        try:
            self.pipeline.connect("element-added", self._on_element_added)
        except Exception:
            pass
        try:
            self.pipeline.connect("deep-element-added", self._on_deep_element_added)
        except Exception:
            pass

    def _discover_video_stream_facts(
        self,
        uri: str,
    ) -> tuple[VideoStreamFacts | None, str | None]:
        try:
            discoverer = GstPbutils.Discoverer.new(5 * Gst.SECOND)
            info = discoverer.discover_uri(uri)
            video_streams = info.get_video_streams()
            if not video_streams:
                return None, "No playable video stream found."

            stream = video_streams[0]
            caps = stream.get_caps()
            caps_string = caps.to_string() if caps else None
            return (
                VideoStreamFacts(
                    caps=caps,
                    caps_string=caps_string,
                    codec=self._codec_from_caps_string(caps_string),
                    width=self._stream_int_value(stream, "get_width"),
                    height=self._stream_int_value(stream, "get_height"),
                    framerate=self._stream_framerate(stream),
                    container=self._container_hint_from_uri(uri),
                ),
                None,
            )
        except Exception as e:
            return None, f"Could not discover playable video stream: {e}"

    @staticmethod
    def _stream_int_value(stream: Any, method_name: str) -> int | None:
        try:
            value = getattr(stream, method_name)()
        except Exception:
            return None
        try:
            value = int(value)
        except (TypeError, ValueError):
            return None
        return value or None

    @staticmethod
    def _stream_framerate(stream: Any) -> float | None:
        try:
            numerator = int(stream.get_framerate_num())
            denominator = int(stream.get_framerate_denom())
        except Exception:
            return None
        if denominator <= 0:
            return None
        return numerator / denominator

    def _discover_playable_video(self, uri: str) -> tuple[bool, str | None]:
        """Return whether GStreamer can discover at least one playable video stream."""
        stream_facts, reason = self._discover_video_stream_facts(uri)
        return stream_facts is not None, reason

    def _on_decoder_pad_added(self, element: Any, pad: Any) -> None:
        caps = pad.get_current_caps()
        if not caps:
            caps = pad.query_caps()
        if not caps:
            return

        if not self._caps_structure_name(caps).startswith("video/"):
            return

        self._last_video_caps = caps.to_string()
        self._last_uses_dmabuf = self._caps_uses_dmabuf(caps)
        logger.info(
            "Decoded video caps for %s: %s",
            self._current_pipeline_variant,
            self._last_video_caps,
        )
        self._send_video_diagnostics(stage="caps")

    def _on_element_added(self, bin: Any, element: Any) -> None:
        self._record_decoder_element(element)
        self._configure_added_element(element)
        try:
            element.connect("element-added", self._on_element_added)
        except Exception:
            pass

    def _on_deep_element_added(self, bin: Any, sub_bin: Any, element: Any) -> None:
        self._record_decoder_element(element)
        self._configure_added_element(element)

    def _record_decoder_element(self, element: Any) -> None:
        try:
            factory = element.get_factory()
        except Exception:
            return
        if factory is None:
            return

        try:
            klass = factory.get_metadata(Gst.ELEMENT_METADATA_KLASS)
            factory_name = factory.get_name()
        except Exception:
            return
        if not (klass and "Decoder" in klass and "Video" in klass):
            return

        decoder_is_hardware = "Hardware" in klass
        if (
            self._selected_decoder_name == factory_name
            and self._selected_decoder_is_hardware == decoder_is_hardware
        ):
            self._record_decoder_src_caps(element)
            return

        self._selected_decoder_name = factory_name
        self._selected_decoder_is_hardware = decoder_is_hardware
        logger.info(
            "Selected video decoder element: %s (hardware=%s)",
            self._selected_decoder_name,
            self._selected_decoder_is_hardware,
        )
        self._record_decoder_src_caps(element)
        self._send_video_diagnostics(stage="decoder")

        if not self._selected_decoder_is_hardware:
            self._send_event(
                WarningEvent(warning_type="software_fallback", decoder=factory_name)
            )

    def _record_decoder_src_caps(self, element: Any) -> None:
        try:
            pad = element.get_static_pad("src")
        except Exception:
            return
        if pad is None:
            return

        try:
            caps = pad.get_current_caps() or pad.query_caps()
            if not caps:
                return
            if not self._caps_structure_name(caps).startswith("video/"):
                return
        except Exception:
            return

        self._last_video_caps = caps.to_string()
        self._last_uses_dmabuf = self._caps_uses_dmabuf(caps)
        logger.info(
            "Decoded video caps for %s: %s",
            self._current_pipeline_variant,
            self._last_video_caps,
        )
        self._send_video_diagnostics(stage="caps")

    def _configure_added_element(self, element: Any) -> None:
        try:
            factory = element.get_factory()
            factory_name = factory.get_name() if factory else element.get_name()
        except Exception:
            return

        if not factory_name.startswith("v4l2") or "dec" not in factory_name:
            return
        if self._current_pipeline_variant in {
            PIPELINE_HARDWARE_DIRECT,
            PIPELINE_HARDWARE_PLAYBIN,
            PIPELINE_GTK_PLAYBIN,
        }:
            return

        try:
            Gst.util_set_object_arg(element, "capture-io-mode", "mmap")
            logger.info(
                "Configured %s capture-io-mode=mmap for compatible presentation path.",
                factory_name,
            )
        except Exception as e:
            logger.debug("Could not set capture-io-mode=mmap on %s: %s", factory_name, e)

    def _on_pad_added(self, element: Any, pad: Any, sink_pad_element: Any) -> None:
        caps = pad.get_current_caps()
        if not caps:
            caps = pad.query_caps()
            
        if caps:
            name = self._caps_structure_name(caps)
            logger.debug("Decoded pad added with caps: %s", caps.to_string())
            if name.startswith("video/"):
                sink_pad = sink_pad_element.get_static_pad("sink")
                if not sink_pad.is_linked():
                    result = pad.link(sink_pad)
                    if result != Gst.PadLinkReturn.OK:
                        logger.error(
                            "Failed to link decoded video pad to sink bin: %s",
                            result.value_nick if hasattr(result, "value_nick") else result,
                        )
                    else:
                        logger.debug("Linked decoded video pad to sink chain.")

    def _on_autoplug_select(self, bin: Any, pad: Any, caps: Any, factory: Any) -> int:
        klass = factory.get_metadata(Gst.ELEMENT_METADATA_KLASS)
        if not (klass and "Decoder" in klass and "Video" in klass):
            return 0

        self._selected_decoder_name = factory.get_name()
        self._selected_decoder_is_hardware = "Hardware" in klass
        logger.info(
            "Selected video decoder candidate: %s (hardware=%s)",
            self._selected_decoder_name,
            self._selected_decoder_is_hardware,
        )
        self._send_video_diagnostics(stage="decoder")

        if not self._selected_decoder_is_hardware:
            self._send_event(
                WarningEvent(warning_type="software_fallback", decoder=factory.get_name())
            )
        return 0

    @staticmethod
    def _caps_structure_name(caps: Any) -> str:
        try:
            struct = caps.get_structure(0)
        except Exception:
            struct = None

        if struct is not None:
            get_name = getattr(struct, "get_name", None)
            if callable(get_name):
                try:
                    return str(get_name())
                except Exception:
                    pass

            name = getattr(struct, "name", None)
            if isinstance(name, str):
                return name

            text = str(struct).strip()
            if text and not text.startswith("<"):
                return text.split(",", 1)[0].strip()

        try:
            return str(caps.to_string()).split(",", 1)[0].strip()
        except Exception:
            return ""

    def _handle_pause(self) -> None:
        if self.pipeline:
            self.pipeline.set_state(Gst.State.PAUSED)

    def _handle_stop(self) -> None:
        self._stop_first_frame_probe()
        self._first_frame_event_sent = False
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
            if self.bus:
                self.bus.remove_signal_watch()
            self.pipeline = None
            self.bus = None
        self._destroy_gtk_video_window()

    def _handle_set_volume(self, level: float) -> None:
        self.volume = max(0.0, min(1.0, level))
        if self.pipeline:
            try:
                self.pipeline.set_property("volume", self.volume)
            except TypeError:
                pass

    def _handle_check_caps(self, uri: str) -> None:
        if not GST_AVAILABLE:
            self._send_event(CapsResultEvent(supported=False))
            return

        try:
            stream_facts, _reason = self._discover_video_stream_facts(uri)
            hardware_limit = self._known_hardware_decode_limit(stream_facts)
            supported = (
                self._hardware_limit_rejection_reason(stream_facts, hardware_limit)
                is None
                and self._hardware_decode_available_for_facts(stream_facts)
            )
            self._send_event(CapsResultEvent(supported=supported))
            
        except Exception as e:
            logger.error(f"Caps discovery failed for {uri}: {e}")
            self._send_event(CapsResultEvent(supported=False))

    @staticmethod
    def _valid_gst_time(value: Any) -> bool:
        try:
            int_value = int(value)
        except (TypeError, ValueError, OverflowError):
            return False
        try:
            none_value = int(Gst.CLOCK_TIME_NONE)
        except Exception:
            none_value = -1
        return int_value >= 0 and int_value != none_value

    @staticmethod
    def _gst_time_seconds(value: Any) -> float | None:
        if not GstWorker._valid_gst_time(value):
            return None
        return int(value) / Gst.SECOND

    def _last_sample_diagnostics(self) -> tuple[float | None, float | None, str | None]:
        sink = self._gtk_video_sink
        if sink is None and self.pipeline is not None:
            try:
                sink = self.pipeline.get_by_name("sink")
            except Exception:
                sink = None
        if sink is None:
            return None, None, None

        try:
            if sink.find_property("last-sample") is None:
                return None, None, None
            sample = sink.get_property("last-sample")
        except Exception:
            return None, None, None
        if sample is None:
            return None, None, None

        try:
            buffer = sample.get_buffer()
            caps = sample.get_caps()
        except Exception:
            return None, None, None
        if buffer is None:
            return None, None, None

        pts_seconds = self._gst_time_seconds(getattr(buffer, "pts", None))
        duration_seconds = self._gst_time_seconds(getattr(buffer, "duration", None))
        caps_text = None
        if caps is not None:
            try:
                caps_text = caps.to_string()
            except Exception:
                caps_text = None
        logger.info(
            "EOS last sample diagnostics: pts=%s duration=%s caps=%s",
            pts_seconds,
            duration_seconds,
            caps_text,
        )
        return pts_seconds, duration_seconds, caps_text

    def _on_eos(self, bus: Any, msg: Any) -> None:
        pts_seconds, duration_seconds, caps_text = self._last_sample_diagnostics()
        self._apply_gtk_eos_opacity_probe()
        self._send_event(
            EosEvent(
                last_sample_pts_seconds=pts_seconds,
                last_sample_duration_seconds=duration_seconds,
                last_sample_caps=caps_text,
            )
        )
        # Do NOT call _handle_stop() here. We want the last frame to remain visible
        # until the main process explicitly sends a StopCommand after the pi3d transition.

    def _on_error(self, bus: Any, msg: Any) -> None:
        err, debug = msg.parse_error()
        debug_text = str(debug or "")
        logger.error("GStreamer error: %s", err.message)
        if debug_text:
            logger.error("GStreamer debug info: %s", debug_text)
        if self._should_retry_with_compatible_pipeline(err.message, debug_text):
            self._retry_with_compatible_pipeline(err.message, debug_text)
            return
        if self._should_retry_with_software_decode(err.message, debug_text):
            self._retry_with_software_decode(err.message, debug_text)
            return
        self._send_event(ErrorEvent(details=err.message))
        self._handle_stop()

    def _is_negotiation_or_stream_error(self, message: str, debug: str) -> bool:
        combined = f"{message}\n{debug}".lower()
        return (
            "not-negotiated" in combined
            or "reason not-negotiated" in combined
            or "internal data stream error" in combined
        )

    def _should_retry_with_compatible_pipeline(self, message: str, debug: str) -> bool:
        return (
            self._current_play_request is not None
            and self._current_pipeline_variant in {PIPELINE_HARDWARE_DIRECT, PIPELINE_GTK_PLAYBIN}
            and not self._compatible_pipeline_retry_attempted
            and self._is_negotiation_or_stream_error(message, debug)
        )

    def _retry_with_compatible_pipeline(self, message: str, debug: str) -> None:
        request = self._current_play_request
        if request is None:
            self._send_event(ErrorEvent(details=message))
            self._handle_stop()
            return

        self._compatible_pipeline_retry_attempted = True
        logger.warning(
            "Hardware presentation video path failed; retrying compatible pipeline. "
            "Message=%s Debug=%s",
            message,
            debug,
        )
        self._start_pipeline(
            request.uri,
            request.x,
            request.y,
            request.w,
            request.h,
            force_software_decoders=False,
            pipeline_variant=PIPELINE_COMPATIBLE,
            fallback_reason="hardware_direct_failed",
            max_software_decode_resolution=self._current_max_software_decode_resolution,
            stream_facts=self._current_stream_facts,
            fit_display=request.fit_display,
            host_background=request.host_background,
        )

    def _should_retry_with_software_decode(self, message: str, debug: str) -> bool:
        if self._software_decode_retry_attempted or self._current_play_request is None:
            return False
        if self._requires_pi_hardware_only(self._current_stream_facts):
            return False
        return self._is_negotiation_or_stream_error(message, debug)

    def _retry_with_software_decode(self, message: str, debug: str) -> None:
        request = self._current_play_request
        if request is None:
            self._send_event(ErrorEvent(details=message))
            self._handle_stop()
            return

        self._software_decode_retry_attempted = True
        logger.warning(
            "Hardware/autoplug video path failed; retrying with software decoders. "
            "Message=%s Debug=%s",
            message,
            debug,
        )
        software_limit = self._software_decode_limit(
            self._current_max_software_decode_resolution
        )
        if self._within_resolution_limit(
            self._current_stream_facts,
            software_limit,
            allow_rotation=True,
        ):
            self._send_event(
                WarningEvent(
                    warning_type="software_fallback",
                    decoder="force-sw-decoders",
                )
            )
        self._start_pipeline(
            request.uri,
            request.x,
            request.y,
            request.w,
            request.h,
            force_software_decoders=True,
            fallback_reason="software_fallback",
            max_software_decode_resolution=self._current_max_software_decode_resolution,
            stream_facts=self._current_stream_facts,
            fit_display=request.fit_display,
            host_background=request.host_background,
        )

    def _on_async_done(self, bus: Any, msg: Any) -> None:
        # Ensure pipeline is playing after async-done
        if self.pipeline:
            self.pipeline.set_state(Gst.State.PLAYING)
        self._schedule_first_frame_probe()

    def cleanup(self) -> None:
        self._handle_stop()
        if self.conn:
            self.conn.close()
        if self.listener:
            self.listener.close()
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GStreamer IPC Worker")
    parser.add_argument(
        "--socket",
        required=False,
        default="/tmp/picframe_gst_worker.sock",
        help="Path to the Unix domain socket",
    )
    args = parser.parse_args()
    
    worker = GstWorker(args.socket)
    worker.start()
