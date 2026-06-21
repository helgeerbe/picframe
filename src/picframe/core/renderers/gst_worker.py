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

from picframe.core.renderers.gst_pipeline_builder import GstPipelineBuilder
from picframe.core.renderers.gst_playback_policy import (
    DEFAULT_SOFTWARE_DECODE_LIMIT,
    PIPELINE_COMPATIBLE,
    PIPELINE_GTK_COMPATIBLE,
    PIPELINE_GTK_PLAYBIN,
    PIPELINE_HARDWARE_DIRECT,
    PIPELINE_HARDWARE_PLAYBIN,
    PIPELINE_SKIPPED,  # noqa: F401 - re-exported for compatibility with tests
    UNSUPPORTED_MEDIA_CODE,
    DecodeHardwareLimit,
    DecodeResolutionLimit,
    GstHardwareSupport,
    PlaybackDecision,
    PlaybackPolicy,
    VideoStreamFacts,
)
from picframe.core.renderers.gtk_video_presenter import GtkVideoPresenter
from picframe.core.renderers.ipc_protocol import (
    CapsResultEvent,
    CheckCapsCommand,
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

# Configure logging for the worker
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("gst_worker")

GTK_PRESENTATION_UNAVAILABLE_CODE = "gtk_presentation_unavailable"
EOS_GTK_WINDOW_OPACITY = 0.99
STARTUP_GTK_WINDOW_OPACITY = 0.0
FIRST_FRAME_PROBE_INTERVAL_MS = 16
FIRST_FRAME_PROBE_TIMEOUT_SECONDS = 2.0
GTK_TRANSPARENT_HOST_CLASS = "picframe-transparent-video-host"
GTK_OPAQUE_HOST_CLASS = "picframe-opaque-video-host"


@dataclass(frozen=True)
class PlayRequest:
    uri: str
    x: int
    y: int
    w: int
    h: int
    fit_display: bool
    host_background: list[float] | tuple[float, ...] | None = None
    host_backdrop_path: str | None = None
    host_backdrop_rect: tuple[int, int, int, int] | list[int] | None = None
    content_fit: str | None = None


try:
    import gi
    gi.require_version('Gst', '1.0')
    gi.require_version('GstPbutils', '1.0')
    from gi.repository import GLib, Gst, GstPbutils
    Gst.init(None)
    GST_AVAILABLE = True
except ImportError as exc:
    gi = Any
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
        self._hardware_model_value = self._read_hardware_model()
        self._hardware_support = GstHardwareSupport(
            Gst,
            lambda names: find_best_element(names),
        )
        self._gtk_presenter = GtkVideoPresenter(
            self._hardware_model_value,
            Gst,
            GLib,
            gi,
            gst_available=GST_AVAILABLE,
        )
        self._pipeline_builder = GstPipelineBuilder(Gst, self._gtk_presenter)
        self._first_frame_event_sent = False
        self._first_frame_probe_source_id: int | None = None
        self._first_frame_probe_started_at = 0.0
        self._pause_requested = False

    @staticmethod
    def _read_hardware_model() -> str:
        try:
            with open("/proc/device-tree/model", "rb") as model_file:
                return model_file.read().decode(errors="ignore").strip("\x00\n ")
        except OSError:
            return ""

    @property
    def _hardware_model(self) -> str:
        return self._hardware_model_value

    @_hardware_model.setter
    def _hardware_model(self, value: str) -> None:
        self._hardware_model_value = value
        if hasattr(self, "_gtk_presenter"):
            self._gtk_presenter._hardware_model = value

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
                cmd.host_backdrop_path,
                cmd.host_backdrop_rect,
                cmd.content_fit,
            )
        elif isinstance(cmd, PauseCommand):
            self._handle_pause()
        elif isinstance(cmd, ResumeCommand):
            self._handle_resume()
        elif isinstance(cmd, SetPauseOverlayCommand):
            self._handle_pause_overlay(cmd.visible, cmd.text)
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
        host_backdrop_path: str | None = None,
        host_backdrop_rect: tuple[int, int, int, int] | list[int] | None = None,
        content_fit: str | None = None,
    ) -> None:
        try:
            self._pause_requested = False
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
                host_backdrop_path=host_backdrop_path,
                host_backdrop_rect=host_backdrop_rect,
                content_fit=content_fit,
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
                host_backdrop_path=host_backdrop_path,
                host_backdrop_rect=host_backdrop_rect,
                content_fit=content_fit,
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
        host_backdrop_path: str | None = None,
        host_backdrop_rect: tuple[int, int, int, int] | list[int] | None = None,
        content_fit: str | None = None,
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
                    host_backdrop_path=host_backdrop_path,
                    host_backdrop_rect=host_backdrop_rect,
                    content_fit=content_fit,
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
                    host_backdrop_path=host_backdrop_path,
                    host_backdrop_rect=host_backdrop_rect,
                    content_fit=content_fit,
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

    @property
    def _gtk(self) -> Any | None:
        return self._gtk_presenter.gtk

    @_gtk.setter
    def _gtk(self, value: Any | None) -> None:
        self._gtk_presenter.gtk = value

    @property
    def _gdk(self) -> Any | None:
        return self._gtk_presenter.gdk

    @_gdk.setter
    def _gdk(self, value: Any | None) -> None:
        self._gtk_presenter.gdk = value

    @property
    def _gtk_window(self) -> Any:
        return self._gtk_presenter.window

    @_gtk_window.setter
    def _gtk_window(self, value: Any) -> None:
        self._gtk_presenter.window = value

    @property
    def _gtk_host(self) -> Any:
        return self._gtk_presenter.host

    @_gtk_host.setter
    def _gtk_host(self, value: Any) -> None:
        self._gtk_presenter.host = value

    @property
    def _gtk_sink_widget(self) -> Any:
        return self._gtk_presenter.sink_widget

    @_gtk_sink_widget.setter
    def _gtk_sink_widget(self, value: Any) -> None:
        self._gtk_presenter.sink_widget = value

    @property
    def _gtk_video_sink(self) -> Any:
        return self._gtk_presenter.video_sink

    @_gtk_video_sink.setter
    def _gtk_video_sink(self, value: Any) -> None:
        self._gtk_presenter.video_sink = value

    @property
    def _gtk_pump_source_id(self) -> int | None:
        return self._gtk_presenter.pump_source_id

    @_gtk_pump_source_id.setter
    def _gtk_pump_source_id(self, value: int | None) -> None:
        self._gtk_presenter.pump_source_id = value

    @property
    def _gtk_presentation_failure(self) -> str | None:
        return self._gtk_presenter.last_failure

    @_gtk_presentation_failure.setter
    def _gtk_presentation_failure(self, value: str | None) -> None:
        self._gtk_presenter.last_failure = value

    def _ensure_gtk(self) -> Any | None:
        return self._gtk_presenter._ensure_gtk()

    def _init_gtk4(self) -> tuple[Any, Any]:
        return self._gtk_presenter._init_gtk4()

    @staticmethod
    def _initialize_gtk(Gtk: Any) -> None:
        GtkVideoPresenter._initialize_gtk(Gtk)

    @staticmethod
    def _set_property_if_supported(element: Any, property_name: str, value: Any) -> None:
        GtkVideoPresenter._set_property_if_supported(element, property_name, value)

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
        host_backdrop_path: str | None = None,
        host_backdrop_rect: tuple[int, int, int, int] | list[int] | None = None,
        content_fit: str | None = None,
    ) -> Any | None:
        pipeline = self._pipeline_builder.build_gtk_playbin_pipeline(
            uri,
            x,
            y,
            w,
            h,
            fit_display=fit_display,
            host_background=host_background,
            host_backdrop_path=host_backdrop_path,
            host_backdrop_rect=host_backdrop_rect,
            content_fit=content_fit,
        )
        self._gtk_presentation_failure = self._pipeline_builder.last_failure
        return pipeline

    def _build_gtk_compatible_pipeline_description(
        self,
        uri: str,
        w: int,
        h: int,
        *,
        force_software_decoders: bool,
        fit_display: bool = False,
    ) -> str:
        return self._pipeline_builder.build_gtk_compatible_pipeline_description(
            uri,
            w,
            h,
            force_software_decoders=force_software_decoders,
            fit_display=fit_display,
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
        host_backdrop_path: str | None = None,
        host_backdrop_rect: tuple[int, int, int, int] | list[int] | None = None,
        content_fit: str | None = None,
    ) -> Any | None:
        pipeline = self._pipeline_builder.build_gtk_compatible_pipeline(
            uri,
            x,
            y,
            w,
            h,
            force_software_decoders=force_software_decoders,
            fit_display=fit_display,
            host_background=host_background,
            host_backdrop_path=host_backdrop_path,
            host_backdrop_rect=host_backdrop_rect,
            content_fit=content_fit,
        )
        self._gtk_presentation_failure = self._pipeline_builder.last_failure
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
        host_backdrop_path: str | None = None,
        host_backdrop_rect: tuple[int, int, int, int] | list[int] | None = None,
    ) -> bool:
        return self._gtk_presenter.present_paintable(
            Gtk,
            video_sink,
            paintable,
            x,
            y,
            w,
            h,
            set_sink_window_size=set_sink_window_size,
            content_fit=content_fit,
            host_background=host_background,
            host_backdrop_path=host_backdrop_path,
            host_backdrop_rect=host_backdrop_rect,
        )

    def _create_gtk_video_picture(
        self,
        Gtk: Any,
        paintable: Any,
        *,
        content_fit: str = "contain",
    ) -> Any:
        return self._gtk_presenter._create_gtk_video_picture(
            Gtk,
            paintable,
            content_fit=content_fit,
        )

    @staticmethod
    def _pin_gtk_video_widget(Gtk: Any, widget: Any) -> None:
        GtkVideoPresenter._pin_gtk_video_widget(Gtk, widget)

    def _configure_gtk_paintable(self, paintable: Any) -> None:
        self._gtk_presenter._configure_gtk_paintable(paintable)

    def _gtk_geometry_is_fullscreen(self, x: int, y: int, w: int, h: int) -> bool:
        return self._gtk_presenter._gtk_geometry_is_fullscreen(x, y, w, h)

    def _gtk_primary_monitor_geometry(self) -> tuple[int, int, int, int] | None:
        return self._gtk_presenter._gtk_primary_monitor_geometry()

    def _gtk_primary_monitor(self) -> Any | None:
        return self._gtk_presenter._gtk_primary_monitor()

    def _configure_gtk_video_window(self, window: Any, *, transparent: bool = True) -> None:
        self._gtk_presenter._configure_gtk_video_window(window, transparent=transparent)

    def _gtk_video_host_uses_transparency(self) -> bool:
        return self._gtk_presenter._gtk_video_host_uses_transparency()

    @staticmethod
    def _find_labwc_pid() -> int | None:
        return GtkVideoPresenter._find_labwc_pid()

    def _configure_gtk_video_host_background(
        self,
        window: Any,
        *,
        transparent: bool,
        host_background: list[float] | tuple[float, ...] | None = None,
    ) -> None:
        self._gtk_presenter._configure_gtk_video_host_background(
            window,
            transparent=transparent,
            host_background=host_background,
        )

    def _set_gtk_video_host_background(
        self,
        widget: Any,
        *,
        transparent: bool,
        host_background: list[float] | tuple[float, ...] | None = None,
    ) -> None:
        self._gtk_presenter._set_gtk_video_host_background(
            widget,
            transparent=transparent,
            host_background=host_background,
        )

    @staticmethod
    def _gtk_opaque_host_background_css(
        host_background: list[float] | tuple[float, ...] | None,
    ) -> str:
        return GtkVideoPresenter._gtk_opaque_host_background_css(host_background)

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
        host_backdrop_path: str | None = None,
        host_backdrop_rect: tuple[int, int, int, int] | list[int] | None = None,
    ) -> Any:
        return self._gtk_presenter._create_gtk_fixed_video_host(
            Gtk,
            window,
            widget,
            x,
            y,
            w,
            h,
            transparent=transparent,
            host_background=host_background,
            host_backdrop_path=host_backdrop_path,
            host_backdrop_rect=host_backdrop_rect,
        )

    def _apply_gtk_eos_opacity_probe(self) -> None:
        self._gtk_presenter.apply_eos_opacity_probe(self.pipeline)

    def _gtk_video_host_geometry(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
    ) -> tuple[int, int, int, int]:
        return self._gtk_presenter._gtk_video_host_geometry(x, y, w, h)

    def _gtk_video_widget_geometry(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
    ) -> tuple[int, int, int, int]:
        return self._gtk_presenter.video_widget_geometry(x, y, w, h)

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
        return self._gtk_presenter._gtk_fixed_host_child_rect(
            x,
            y,
            w,
            h,
            fullscreen=fullscreen,
            transparent=transparent,
        )

    def _apply_gtk_host_window_geometry(
        self,
        window: Any,
        x: int,
        y: int,
        w: int,
        h: int,
    ) -> None:
        self._gtk_presenter._apply_gtk_host_window_geometry(window, x, y, w, h)

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
        GtkVideoPresenter._apply_gtk_window_geometry(
            window,
            x,
            y,
            w,
            h,
            fullscreen=fullscreen,
            widget=widget,
        )

    def _present_gtk_video_window(
        self,
        window: Any,
        *,
        fullscreen: bool,
        opacity: float = 1.0,
    ) -> None:
        self._gtk_presenter._present_gtk_video_window(
            window,
            fullscreen=fullscreen,
            opacity=opacity,
        )

    def _reveal_gtk_video_window(self) -> None:
        self._gtk_presenter.reveal()

    @staticmethod
    def _focus_gtk_video_window(window: Any) -> None:
        GtkVideoPresenter._focus_gtk_video_window(window)

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
        self._gtk_presenter._log_gtk_window_diagnostics(
            window,
            widget,
            x,
            y,
            w,
            h,
            fullscreen,
            fixed_host=fixed_host,
            host_transparent=host_transparent,
        )

    def _hide_gtk_cursor(self, window: Any, widget: Any) -> None:
        self._gtk_presenter._hide_gtk_cursor(window, widget)

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
        return self._gtk_presenter._gtk_window_matches_geometry(
            window,
            x,
            y,
            w,
            h,
            fullscreen=fullscreen,
            widget=widget,
            fixed_host=fixed_host,
            host_transparent=host_transparent,
        )

    def _start_gtk_pump(self) -> None:
        self._gtk_presenter._start_gtk_pump()

    def _stop_gtk_pump(self) -> None:
        self._gtk_presenter._stop_gtk_pump()

    def _pump_gtk_events_tick(self) -> bool:
        return self._gtk_presenter._pump_gtk_events_tick()

    def _pump_gtk_events(self) -> None:
        self._gtk_presenter._pump_gtk_events()

    def _destroy_gtk_video_window(self) -> None:
        self._gtk_presenter.destroy()

    def _playback_policy(self) -> PlaybackPolicy:
        return PlaybackPolicy(
            self._hardware_model,
            self._hardware_decode_available_for_facts,
        )

    def _select_pipeline_variant(
        self,
        uri: str,
        sink_name: str,
        force_software_decoders: bool,
        stream_facts: VideoStreamFacts | None = None,
        max_software_decode_resolution: str | None = None,
    ) -> str:
        return self._playback_policy().select_pipeline_variant(
            uri,
            sink_name,
            force_software_decoders,
            stream_facts=stream_facts,
            max_software_decode_resolution=max_software_decode_resolution,
        )

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
        return self._playback_policy().select_playback_decision(
            uri,
            sink_name,
            force_software_decoders=force_software_decoders,
            max_software_decode_resolution=max_software_decode_resolution,
            stream_facts=stream_facts,
            fallback_reason=fallback_reason,
        )

    def _hardware_decode_available_for_uri(self, uri: str) -> bool:
        stream_facts, _reason = self._discover_video_stream_facts(uri)
        return self._hardware_decode_available_for_facts(stream_facts)

    def _hardware_decode_available_for_caps(self, caps: Any) -> bool:
        return self._hardware_support.hardware_decode_available_for_caps(caps)

    def _hardware_decode_available_for_facts(
        self,
        stream_facts: VideoStreamFacts | None,
    ) -> bool:
        return self._hardware_support.hardware_decode_available_for_facts(stream_facts)

    def _requires_compatible_hardware_presentation(
        self,
        stream_facts: VideoStreamFacts | None,
    ) -> bool:
        return self._playback_policy().requires_compatible_hardware_presentation(
            stream_facts
        )

    def _requires_pi_hardware_only(
        self,
        stream_facts: VideoStreamFacts | None,
    ) -> bool:
        return self._playback_policy().requires_pi_hardware_only(stream_facts)

    def _uses_playbin_hardware_presentation(
        self,
        stream_facts: VideoStreamFacts | None,
    ) -> bool:
        return self._playback_policy().uses_playbin_hardware_presentation(stream_facts)

    def _unsupported_hardware_presentation_reason(
        self,
        stream_facts: VideoStreamFacts | None,
        sink_name: str,
        uri: str,
    ) -> str | None:
        return self._playback_policy().unsupported_hardware_presentation_reason(
            stream_facts,
            sink_name,
            uri,
        )

    def _known_hardware_decode_limit(
        self,
        stream_facts: VideoStreamFacts | None,
    ) -> DecodeHardwareLimit | None:
        return self._playback_policy().known_hardware_decode_limit(stream_facts)

    @staticmethod
    def _raspberry_pi_model_family(model: str) -> str | None:
        return PlaybackPolicy.raspberry_pi_model_family(model)

    @staticmethod
    def _normalized_codec(codec: str | None) -> str | None:
        return PlaybackPolicy.normalized_codec(codec)

    def _software_decode_limit(
        self,
        value: str | None,
    ) -> DecodeResolutionLimit | None:
        return self._playback_policy().software_decode_limit(value)

    @staticmethod
    def _parse_resolution_limit(value: str | None) -> DecodeResolutionLimit | None:
        return PlaybackPolicy.parse_resolution_limit(value)

    @staticmethod
    def _format_resolution_limit(limit: DecodeResolutionLimit | None) -> str | None:
        return PlaybackPolicy.format_resolution_limit(limit)

    @staticmethod
    def _format_hardware_limit(limit: DecodeHardwareLimit | None) -> str | None:
        return PlaybackPolicy.format_hardware_limit(limit)

    @staticmethod
    def _within_resolution_limit(
        stream_facts: VideoStreamFacts | None,
        limit: DecodeResolutionLimit | DecodeHardwareLimit | None,
        *,
        allow_rotation: bool,
    ) -> bool:
        return PlaybackPolicy.within_resolution_limit(
            stream_facts,
            limit,
            allow_rotation=allow_rotation,
        )

    def _hardware_limit_rejection_reason(
        self,
        stream_facts: VideoStreamFacts | None,
        limit: DecodeHardwareLimit | None,
    ) -> str | None:
        return self._playback_policy().hardware_limit_rejection_reason(
            stream_facts,
            limit,
        )

    @staticmethod
    def _within_hardware_framerate_limit(
        stream_facts: VideoStreamFacts | None,
        limit: DecodeHardwareLimit | None,
    ) -> bool:
        return PlaybackPolicy.within_hardware_framerate_limit(stream_facts, limit)

    def _skip_decision(
        self,
        stream_facts: VideoStreamFacts | None,
        hardware_limit: str | None,
        software_limit: str | None,
        fallback_reason: str,
    ) -> PlaybackDecision:
        return self._playback_policy().skip_decision(
            stream_facts,
            hardware_limit,
            software_limit,
            fallback_reason,
        )

    @staticmethod
    def _format_stream_dimensions(stream_facts: VideoStreamFacts | None) -> str:
        return PlaybackPolicy.format_stream_dimensions(stream_facts)

    @staticmethod
    def _format_stream_framerate(stream_facts: VideoStreamFacts | None) -> str:
        return PlaybackPolicy.format_stream_framerate(stream_facts)

    @staticmethod
    def _codec_from_caps_string(caps_string: str | None) -> str | None:
        return PlaybackPolicy.codec_from_caps_string(caps_string)

    @staticmethod
    def _container_hint_from_uri(uri: str) -> str | None:
        return PlaybackPolicy.container_hint_from_uri(uri)

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
        self._pause_requested = True
        if self.pipeline:
            self.pipeline.set_state(Gst.State.PAUSED)

    def _handle_resume(self) -> None:
        self._pause_requested = False
        if self.pipeline:
            self.pipeline.set_state(Gst.State.PLAYING)

    def _handle_pause_overlay(self, visible: bool, text: str = "") -> None:
        self._gtk_presenter.set_pause_overlay(visible, text)

    def _handle_stop(self) -> None:
        self._pause_requested = False
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
            host_backdrop_path=request.host_backdrop_path,
            host_backdrop_rect=request.host_backdrop_rect,
            content_fit=request.content_fit,
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
            host_backdrop_path=request.host_backdrop_path,
            host_backdrop_rect=request.host_backdrop_rect,
            content_fit=request.content_fit,
        )

    def _on_async_done(self, bus: Any, msg: Any) -> None:
        # Startup async-done should keep playback moving, but PAUSED transitions can
        # also emit async-done. Respect an explicit pause request.
        if self.pipeline and not self._pause_requested:
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
