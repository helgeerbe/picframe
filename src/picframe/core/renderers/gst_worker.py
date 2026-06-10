"""
GStreamer Subprocess Worker.

This script runs in an isolated subprocess to handle GStreamer video playback.
It communicates with the main application process via an IPC socket using JSON messages.
"""

import argparse
import logging
import os
import sys
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
PIPELINE_SKIPPED = "skipped"
DEFAULT_SOFTWARE_DECODE_LIMIT = "1280x720"
UNSUPPORTED_MEDIA_CODE = "unsupported_media"


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
        self._current_play_request: tuple[str, int, int, int, int] | None = None
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
    ) -> None:
        try:
            stream_facts, reason = self._discover_video_stream_facts(uri)
            if stream_facts is None:
                details = reason or "No playable video stream found."
                logger.error(f"Skipping {uri}: {details}")
                self._send_event(ErrorEvent(details=details, code=UNSUPPORTED_MEDIA_CODE))
                return

            self._current_play_request = (uri, x, y, w, h)
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

            self._reset_pipeline_telemetry(
                pipeline_variant,
                sink_name,
                decision=decision.decision,
                hardware_limit=decision.hardware_limit,
                software_limit=decision.software_limit,
            )

            if decision.skip_reason is not None:
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
            self._send_video_diagnostics(
                stage="decision",
                fallback_reason=fallback_reason,
            )
            pipeline_description = self._build_pipeline_description(
                uri,
                x,
                y,
                w,
                h,
                force_software_decoders=force_software_decoders,
                pipeline_variant=pipeline_variant,
                sink_name=sink_name,
            )
            self.pipeline = Gst.parse_launch(pipeline_description)
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

    def _build_pipeline_description(
        self,
        uri: str,
        x: int,
        y: int,
        w: int,
        h: int,
        *,
        force_software_decoders: bool,
        pipeline_variant: str = PIPELINE_COMPATIBLE,
        sink_name: str | None = None,
    ) -> str:
        force_sw = " force-sw-decoders=true" if force_software_decoders else ""
        sink_name = sink_name or self._select_sink_name()
        sink_props_str = self._build_sink_props(
            sink_name,
            x,
            y,
            w,
            h,
            pipeline_variant=pipeline_variant,
        )

        if pipeline_variant == PIPELINE_HARDWARE_PLAYBIN:
            return (
                f'playbin name=player uri="{uri}" flags=0x00000001 '
                f'video-sink="{sink_name} name=sink {sink_props_str}" '
                'audio-sink="fakesink sync=false"'
            )

        if pipeline_variant == PIPELINE_HARDWARE_DIRECT:
            return (
                f'uridecodebin name=decoder uri="{uri}"{force_sw} '
                "decoder. ! "
                "queue name=video_queue ! "
                f"{sink_name} name=sink {sink_props_str}"
            )

        return (
            f'uridecodebin name=decoder uri="{uri}"{force_sw} '
            "decoder. ! "
            "videoconvert ! "
            "videoscale add-borders=false ! "
            "videoconvert ! "
            "video/x-raw,format=RGBA ! "
            "alpha alpha=0.99 ! "
            f"{sink_name} name=sink {sink_props_str}"
        )

    def _select_sink_name(self) -> str:
        sink_name = find_best_element(
            ["waylandsink", "glimagesink", "ximagesink", "autovideosink"]
        )
        return sink_name or "autovideosink"

    def _build_sink_props(
        self,
        sink_name: str,
        x: int,
        y: int,
        w: int,
        h: int,
        *,
        pipeline_variant: str = PIPELINE_COMPATIBLE,
    ) -> str:
        has_render_rectangle = w > 0 and h > 0
        sink_props = []
        fullscreen_wayland = (
            sink_name == "waylandsink"
            and x == 0
            and y == 0
            and has_render_rectangle
        )
        if fullscreen_wayland:
            sink_props.append("fullscreen=true")
        elif has_render_rectangle:
            sink_props.append(f'render-rectangle="<{x}, {y}, {w}, {h}>"')
        else:
            sink_props.append("fullscreen=true")
        if sink_name == "waylandsink":
            sink_props.append("rotate-method=8")
        return " ".join(sink_props)

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

    def _create_sink_bin(self, x: int, y: int, w: int, h: int) -> Any:
        bin = Gst.Bin.new("sink_bin")
        elements, sink_pad_element = self._build_sink_elements(x, y, w, h)

        for elem in elements:
            bin.add(elem)

        self._link_elements(elements)

        pad = sink_pad_element.get_static_pad("sink")
        ghost_pad = Gst.GhostPad.new("sink", pad)
        bin.add_pad(ghost_pad)

        return bin

    def _build_sink_elements(self, x: int, y: int, w: int, h: int) -> tuple[list[Any], Any]:
        hw_converter = find_best_element(["v4l2convert"])
        
        elements = []
        queue = Gst.ElementFactory.make("queue", "video_queue")
        elements.append(queue)
        if hw_converter:
            conv = Gst.ElementFactory.make(hw_converter, "conv")
            elements.append(conv)
        else:
            conv1 = Gst.ElementFactory.make("videoconvert", "conv1")
            scale = Gst.ElementFactory.make("videoscale", "scale")
            scale.set_property("add-borders", False)
            conv2 = Gst.ElementFactory.make("videoconvert", "conv2")
            elements.extend([conv1, scale, conv2])
        sink_pad_element = queue
            
        capsfilter = Gst.ElementFactory.make("capsfilter", "capsfilter")
        caps = Gst.Caps.from_string("video/x-raw,format=RGBA")
        capsfilter.set_property("caps", caps)
        elements.append(capsfilter)
        
        alpha = Gst.ElementFactory.make("alpha", "alpha")
        alpha.set_property("alpha", 0.99)
        elements.append(alpha)
            
        sink_name = find_best_element(["waylandsink", "glimagesink", "ximagesink", "autovideosink"])
        if not sink_name:
            sink_name = "autovideosink"
            
        sink = Gst.ElementFactory.make(sink_name, "sink")
        has_render_rectangle = w > 0 and h > 0
        fullscreen_wayland = (
            sink_name == "waylandsink"
            and x == 0
            and y == 0
            and has_render_rectangle
        )

        if not has_render_rectangle or fullscreen_wayland:
            try:
                if hasattr(sink.props, 'fullscreen'):
                    sink.set_property("fullscreen", True)
            except Exception:
                pass

        if has_render_rectangle and not fullscreen_wayland:
            try:
                Gst.util_set_object_arg(sink, "render-rectangle", f"<{x}, {y}, {w}, {h}>")
            except Exception as e:
                logger.warning(f"Sink {sink_name} does not support render-rectangle property: {e}")

        if sink_name == "waylandsink":
            sink.set_property("rotate-method", 8)
            
        elements.append(sink)
        return elements, sink_pad_element

    def _link_elements(self, elements: list[Any]) -> None:
        for i in range(len(elements) - 1):
            elements[i].link(elements[i + 1])

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
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
            if self.bus:
                self.bus.remove_signal_watch()
            self.pipeline = None
            self.bus = None

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

    def _on_eos(self, bus: Any, msg: Any) -> None:
        self._send_event(EosEvent())
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
            and self._current_pipeline_variant == PIPELINE_HARDWARE_DIRECT
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
            "Hardware direct video path failed; retrying compatible pipeline. "
            "Message=%s Debug=%s",
            message,
            debug,
        )
        uri, x, y, w, h = request
        self._start_pipeline(
            uri,
            x,
            y,
            w,
            h,
            force_software_decoders=False,
            pipeline_variant=PIPELINE_COMPATIBLE,
            fallback_reason="hardware_direct_failed",
            max_software_decode_resolution=self._current_max_software_decode_resolution,
            stream_facts=self._current_stream_facts,
        )

    def _should_retry_with_software_decode(self, message: str, debug: str) -> bool:
        if self._software_decode_retry_attempted or self._current_play_request is None:
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
        uri, x, y, w, h = request
        self._start_pipeline(
            uri,
            x,
            y,
            w,
            h,
            force_software_decoders=True,
            fallback_reason="software_fallback",
            max_software_decode_resolution=self._current_max_software_decode_resolution,
            stream_facts=self._current_stream_facts,
        )

    def _on_async_done(self, bus: Any, msg: Any) -> None:
        self._send_event(FirstFrameRenderedEvent())
        # Ensure pipeline is playing after async-done
        if self.pipeline:
            self.pipeline.set_state(Gst.State.PLAYING)

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
