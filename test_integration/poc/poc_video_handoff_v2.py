#!/usr/bin/env python3
"""
Proof of Concept: Video Handoff (Phase 0)
This script tests the seamless EGL/OpenGL context handoff between pi3d (images)
and GStreamer (video) across different platforms (macOS, Raspberry Pi).

Usage:
    python3 poc_video_handoff_v2.py <image_path_1> <video_path> <image_path_2>
"""

import argparse
import logging
import platform
import sys
import time
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Dependency Checks ---
try:
    import pi3d
except ImportError:
    logger.error("pi3d is not installed. Please install it: pip install pi3d")
    sys.exit(1)

try:
    from picframe.core.utils.video_frame_extractor import VideoFrameExtractor
except ImportError:
    logger.error("VideoFrameExtractor not found. Please ensure picframe is installed.")
    sys.exit(1)

try:
    import gi
    gi.require_version('Gst', '1.0')
    from gi.repository import Gst
except ImportError:
    logger.error("GStreamer not installed")
    sys.exit(1)

# Initialize GStreamer
Gst.init(None)


class VideoHandoffPoC:
    def __init__(
        self,
        image_path: str,
        video_path: str,
        image2_path: str = "",
        blend_time: float = 5.0,
        pipeline_mode: str = "direct",
        eos_alpha: float = 0.99,
        eos_redraw_seconds: float = 0.25,
        eos_alpha_seek_offset: float = 0.1,
        max_video_seconds: float = 0.0,
        shader_path: str = "",
        last_frame_swap_after: float = 0.5,
        last_frame_swap_timeout: float = 5.0,
        last_frame_offset: float | None = None,
        alpha_probe_seek_mode: str = "key-unit",
        eos_window_opacity: float = 0.99,
        gpu_eos_seek_mode: str = "none",
        require_gpu: bool = False,
        last_frame_source: str = "cached-offset",
    ):
        self.image_path = image_path
        self.video_path = video_path
        self.image2_path = image2_path or image_path
        self.blend_time = blend_time
        self.pipeline_mode = pipeline_mode
        self.eos_alpha = max(0.0, min(1.0, eos_alpha))
        self.eos_redraw_seconds = max(0.0, eos_redraw_seconds)
        self.eos_alpha_seek_offset = max(0.01, eos_alpha_seek_offset)
        self.max_video_seconds = max(0.0, max_video_seconds)
        self.shader_path = shader_path
        self.last_frame_swap_after = max(0.0, last_frame_swap_after)
        self.last_frame_swap_timeout = max(0.1, last_frame_swap_timeout)
        self.last_frame_offset = (
            max(0.01, last_frame_offset)
            if last_frame_offset is not None
            else self.eos_alpha_seek_offset
        )
        self.alpha_probe_seek_mode = alpha_probe_seek_mode
        self.eos_window_opacity = max(0.0, min(1.0, eos_window_opacity))
        self.gpu_eos_seek_mode = gpu_eos_seek_mode
        self.require_gpu = require_gpu
        self.last_frame_source = last_frame_source
        self.first_frame_texture = None
        self.last_frame_texture = None
        self.video_duration = self._get_video_duration(video_path)
        self.os_name = platform.system()
        # State variables
        self.video_finished = False
        self.pipeline = None
        self.bus = None
        self.eos_alpha_element = None
        self.wayland_sink = None
        self.gtk_video_sink = None
        self.gtk_window = None
        self.gtk_sink_widget = None
        self.Gtk = None
        self._gpu_requirement_failed = False

        logger.info("Detected OS: %s", self.os_name)
        logger.info(
            "PoC options: pipeline_mode=%s eos_alpha=%.3f eos_window_opacity=%.3f "
            "eos_redraw_seconds=%.3f alpha_probe_seek_mode=%s gpu_eos_seek_mode=%s "
            "require_gpu=%s last_frame_source=%s",
            self.pipeline_mode,
            self.eos_alpha,
            self.eos_window_opacity,
            self.eos_redraw_seconds,
            self.alpha_probe_seek_mode,
            self.gpu_eos_seek_mode,
            self.require_gpu,
            self.last_frame_source,
        )

        self._setup_pi3d()
        self._extract_video_frames()
        self._setup_gstreamer()
    
    def _get_video_duration(self, video_path):
        """Get the duration of the video in seconds using ffprobe."""
        import subprocess
        try:
            cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", video_path]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            return float(result.stdout.strip())
        except:
            return 0.0

    def _setup_pi3d(self):
        """Initialize pi3d display based on the platform."""
        logger.info("Initializing pi3d display...")

        try:
            self.DISPLAY = pi3d.Display.create(
                x=0, y=0, frames_per_second=30,
                display_config=(pi3d.DISPLAY_CONFIG_HIDE_CURSOR | pi3d.DISPLAY_CONFIG_NO_FRAME |
                                pi3d.DISPLAY_CONFIG_FULLSCREEN),
                background=(0.0, 0.0, 0.0, 1.0), use_glx=False, use_sdl2=True
            )
            self.CAMERA = pi3d.Camera(is_3d=False)
            shader_path = self._resolve_shader_path()
            logger.info("Using shader: %s", shader_path)
            self.SHADER = pi3d.Shader(shader_path)

            # Load the test images as textures
            logger.info("Loading image 1: %s", self.image_path)
            self.texture1 = pi3d.Texture(self.image_path, blend=True, mipmap=True)
            logger.info("Loading image 2: %s", self.image2_path)
            self.texture2 = pi3d.Texture(self.image2_path, blend=True, mipmap=True)

            # Create a sprite to hold the textures and set shader
            self.sprite = pi3d.Sprite(camera=self.CAMERA, w=self.DISPLAY.width,
                                        h=self.DISPLAY.height, z=5.0)
            self.sprite.set_shader(self.SHADER)
            self.sprite.set_textures([self.texture1, self.texture1])

            # Set uniforms required by blend_new shader
            self.sprite.unif[42] = 1.0  # w_rat_f
            self.sprite.unif[43] = 1.0  # h_rat_f
            self.sprite.unif[44] = 1.0  # alpha
            self.sprite.unif[45] = 1.0  # w_rat_b
            self.sprite.unif[46] = 1.0  # h_rat_b
            self.sprite.unif[47] = 0.5  # edge_alpha
            self.sprite.unif[48] = 0.0  # x_off_f
            self.sprite.unif[49] = 0.0  # y_off_f
            self.sprite.unif[51] = 0.0  # x_off_b
            self.sprite.unif[52] = 0.0  # y_off_b
            self.sprite.unif[54] = 0.0  # blend_type
            self.sprite.unif[55] = 1.0  # brightness

        except (Exception, TypeError) as e:
            logger.error("pi3d initialization failed: %s", e)
            sys.exit(1)

    def _resolve_shader_path(self) -> str:
        """Resolve the blend shader from Picframe runtime data, package data, or repo data."""
        if self.shader_path:
            return str(Path(self.shader_path).expanduser())

        candidates = [
            Path("~/.picframe/data/shaders/blend_new").expanduser(),
        ]

        try:
            import picframe

            candidates.append(Path(picframe.__file__).parent / "data" / "shaders" / "blend_new")
        except Exception:
            pass

        candidates.append(
            Path(__file__).resolve().parents[2] / "src" / "picframe" / "data" / "shaders" / "blend_new"
        )

        for candidate in candidates:
            if candidate.with_suffix(".fs").exists() and candidate.with_suffix(".vs").exists():
                return str(candidate)

        logger.warning(
            "Could not find blend_new shader in ~/.picframe, installed package, or repo; "
            "falling back to pi3d shader lookup."
        )
        return "blend_new"

    def _extract_video_frames(self):
        """Extract the first and last frames from the video using VideoFrameExtractor."""
        logger.info("Extracting video frames...")
        extractor = VideoFrameExtractor(
            video_path=self.video_path,
            display_width=self.DISPLAY.width,
            display_height=self.DISPLAY.height,
            fit_display=False
        )
        frames = self._extract_poc_frames(extractor)
        if frames:
            frame_first, frame_last = frames
            self.first_frame_texture = pi3d.Texture(frame_first, blend=True, mipmap=True)
            self.last_frame_texture = pi3d.Texture(frame_last, blend=True, mipmap=True)
            logger.info("Frames extracted: %s, %s", frame_first.size, frame_last.size)
        else:
            logger.error("Failed to extract frames from video.")
            sys.exit(1)

    def _extract_poc_frames(self, extractor: VideoFrameExtractor):
        """Extract first frame and a PoC-specific handoff frame at a fixed end offset."""
        if self.video_duration <= 0:
            return extractor.get_first_and_last_frames(
                self.video_duration,
                self.DISPLAY.width,
                self.DISPLAY.height,
            )

        first_frame = extractor._get_frame_as_image(0)
        handoff_time = max(0.0, self.video_duration - self.last_frame_offset)
        last_frame = extractor._get_frame_as_image(handoff_time)
        if first_frame is None or last_frame is None:
            logger.warning(
                "PoC fixed-offset frame extraction failed; falling back to cached frame extractor."
            )
            return extractor.get_first_and_last_frames(
                self.video_duration,
                self.DISPLAY.width,
                self.DISPLAY.height,
            )
        logger.info(
            "PoC handoff frame extracted at %.3fs (duration %.3fs, offset %.3fs).",
            handoff_time,
            self.video_duration,
            self.last_frame_offset,
        )
        return (
            extractor._process_video_frame(first_frame),
            extractor._process_video_frame(last_frame),
        )

    def _setup_gstreamer(self):
        """Initialize GStreamer pipeline for video playback."""
        logger.info("Setting up GStreamer pipeline...")

        # Convert video path to URI format for GStreamer
        uri = Path(self.video_path).absolute().as_uri()

        # Hardware acceleration is essential on the Pi.
        # 'playbin' usually auto-detects hardware decoders (v4l2).
        if self.pipeline_mode == "gtk-gpu-opacity":
            self._setup_gtk_gpu_pipeline(uri)
        else:
            if self.pipeline_mode == "direct":
                # Fast path: no conversion while playing. This matches the current Picframe goal.
                video_sink_str = "waylandsink name=wsink fullscreen=true show-preroll-frame=true"
            elif self.pipeline_mode == "compatible":
                # Legacy-style path. It keeps alpha in the stream for the whole video, but is expensive.
                video_sink_str = (
                    "videoscale add-borders=false ! "
                    "videoconvert ! "
                    "alpha name=eos_alpha alpha=0.99 ! "
                    "waylandsink name=wsink fullscreen=true show-preroll-frame=true"
                )
            elif self.pipeline_mode == "alpha-probe":
                # Probe path: keep alpha opaque during playback, then reduce it after EOS.
                # This still inserts conversion, but lets us test whether a 99% video surface
                # wakes the compositor/pi3d handoff before the video window is destroyed.
                video_sink_str = (
                    "videoconvert ! "
                    "alpha name=eos_alpha alpha=1.0 prefer-passthrough=true ! "
                    "waylandsink name=wsink fullscreen=true show-preroll-frame=true"
                )
            else:
                raise ValueError(f"Unsupported pipeline mode: {self.pipeline_mode}")

            pipeline_str = (
                f"playbin uri=\"{uri}\" "
                f"video-sink=\"{video_sink_str}\" "
                "audio-sink=\"fakesink sync=false\""
            )
            logger.info("Pipeline: %s", pipeline_str)

            try:
                self.pipeline = Gst.parse_launch(pipeline_str)
            except Exception as e:
                logger.error("Failed to parse GStreamer pipeline: %s", e)
                sys.exit(1)

        self.eos_alpha_element = self._find_pipeline_element("eos_alpha")
        self.wayland_sink = (
            None if self.pipeline_mode == "gtk-gpu-opacity"
            else self._find_pipeline_element("wsink")
        )
        if self.wayland_sink:
            logger.info("Found waylandsink: %s", self.wayland_sink.get_name())
            self._set_property_if_supported(self.wayland_sink, "show-preroll-frame", True)
        if self.gtk_video_sink:
            logger.info("Found gtkwaylandsink: %s", self.gtk_video_sink.get_name())
            self._set_property_if_supported(self.gtk_video_sink, "show-preroll-frame", True)
        if self.eos_alpha_element:
            logger.info("Found EOS alpha element: %s", self.eos_alpha_element.get_name())
        elif self.pipeline_mode == "alpha-probe":
            logger.warning("alpha-probe requested, but eos_alpha element was not found.")

        # Access the bus to handle messages and synchronization
        self.bus = self.pipeline.get_bus()
        
        # 1. Asynchronous signal watch for logic-level events (EOS/Error)
        self.bus.add_signal_watch()
        self.bus.connect("message::eos", self._on_eos)
        self.bus.connect("message::error", self._on_error)

        # 2. Synchronous message emission for timing-critical window/layer setup
        # This is required for Wayland/KMS to handle the video surface correctly.
        self.bus.enable_sync_message_emission()
        self.bus.connect("sync-message::element", self._on_sync_message)
        self._log_gpu_telemetry("setup")

    def _ensure_gtk(self):
        if self.Gtk is not None:
            return self.Gtk
        try:
            gi.require_version("Gtk", "3.0")
            from gi.repository import Gtk

            Gtk.init([])
        except (ImportError, ValueError, RuntimeError) as exc:
            logger.error(
                "GTK3 is required for --pipeline-mode gtk-gpu-opacity: %s. "
                "Install gir1.2-gtk-3.0 if it is missing.",
                exc,
            )
            sys.exit(1)
        self.Gtk = Gtk
        return Gtk

    def _setup_gtk_gpu_pipeline(self, uri: str) -> None:
        """Build a playbin + gtkwaylandsink pipeline without forced conversion."""
        Gtk = self._ensure_gtk()

        self.pipeline = Gst.ElementFactory.make("playbin", "player")
        self.gtk_video_sink = Gst.ElementFactory.make("gtkwaylandsink", "wsink")
        audio_sink = Gst.ElementFactory.make("fakesink", "audiosink")
        if not self.pipeline or not self.gtk_video_sink or not audio_sink:
            logger.error(
                "gtk-gpu-opacity requires playbin, gtkwaylandsink, and fakesink. "
                "Install gstreamer1.0-plugins-bad if gtkwaylandsink is missing."
            )
            sys.exit(1)

        self._set_property_if_supported(audio_sink, "sync", False)
        self._set_property_if_supported(self.gtk_video_sink, "show-preroll-frame", True)
        self._set_property_if_supported(self.gtk_video_sink, "rotate-method", 8)
        self.pipeline.set_property("uri", uri)
        self.pipeline.set_property("video-sink", self.gtk_video_sink)
        self.pipeline.set_property("audio-sink", audio_sink)

        self.gtk_sink_widget = self.gtk_video_sink.get_property("widget")
        if self.gtk_sink_widget is None:
            logger.error("gtkwaylandsink did not provide a Gtk widget.")
            sys.exit(1)

        self.gtk_sink_widget.set_hexpand(True)
        self.gtk_sink_widget.set_vexpand(True)

        self.gtk_window = Gtk.Window(title="picframe-poc-video")
        self.gtk_window.set_decorated(False)
        self.gtk_window.set_app_paintable(True)
        self.gtk_window.add(self.gtk_sink_widget)
        self.gtk_window.fullscreen()

        logger.info(
            "Pipeline: playbin uri=\"%s\" video-sink=\"gtkwaylandsink name=wsink\" "
            "audio-sink=\"fakesink sync=false\"",
            uri,
        )

    def _pump_gui_events(self) -> None:
        if self.Gtk is None:
            return
        while self.Gtk.events_pending():
            self.Gtk.main_iteration_do(False)

    def _show_gtk_video_window(self) -> None:
        if not self.gtk_window:
            return
        logger.info("Showing GTK video window at full opacity.")
        self.gtk_window.set_opacity(1.0)
        self.gtk_window.fullscreen()
        self.gtk_window.show_all()
        self._pump_gui_events()

    def _close_gtk_video_window(self) -> None:
        if not self.gtk_window:
            return
        logger.info("Closing GTK video window.")
        self.gtk_window.hide()
        self.gtk_window.destroy()
        self._pump_gui_events()
        self.gtk_window = None
        self.gtk_sink_widget = None

    def _on_sync_message(self, bus, msg):
        """Synchronous message handler for window embedding."""
        if msg.get_structure() and msg.get_structure().get_name() == "prepare-window-handle":
            logger.info("GStreamer: prepare-window-handle received.")
            # At this point, the sink is ready to be mapped to a surface/window.
            # For waylandsink with fullscreen=true, we ensure aspect ratio is kept.
            sink = msg.src
            
            # The sink here might be GstPlaySink, which doesn't have these properties directly.
            # We need to find the actual waylandsink inside it.
            wsink = None
            if sink.get_name() == "wsink":
                wsink = sink
            elif hasattr(sink, "get_by_name"):
                wsink = sink.get_by_name("wsink")
                
            if wsink:
                # waylandsink does not have a force-aspect-ratio property,
                # it relies on videoscale for that.
                pass

            # For Wayland, we might need to pass the wl_surface
            # But for now, let's just try to let waylandsink handle it
            # or we can try to get the SDL2 window ID if pi3d exposes it
            pass

    def _find_pipeline_element(self, name):
        """Find an element by name, including elements nested in playbin's sinks."""
        if not self.pipeline:
            return None
        element = self.pipeline.get_by_name(name)
        if element:
            return element
        for property_name in ("video-sink", "audio-sink"):
            if self.pipeline.find_property(property_name) is None:
                continue
            sink = self.pipeline.get_property(property_name)
            element = self._find_element_in_bin(sink, name)
            if element:
                return element
        return self._find_element_in_bin(self.pipeline, name)

    @staticmethod
    def _find_element_in_bin(root, name):
        if not root:
            return None
        if getattr(root, "get_name", lambda: None)() == name:
            return root
        if not hasattr(root, "iterate_recurse"):
            return None

        iterator = root.iterate_recurse()
        while True:
            result, element = iterator.next()
            if result == Gst.IteratorResult.OK:
                if element.get_name() == name:
                    return element
            elif result == Gst.IteratorResult.RESYNC:
                iterator.resync()
            else:
                return None

    def _iter_pipeline_elements(self):
        elements = []
        seen = set()

        def add_element_tree(root):
            if not root:
                return
            marker = id(root)
            if marker not in seen:
                seen.add(marker)
                elements.append(root)
            if not hasattr(root, "iterate_recurse"):
                return

            iterator = root.iterate_recurse()
            while True:
                result, element = iterator.next()
                if result == Gst.IteratorResult.OK:
                    marker = id(element)
                    if marker not in seen:
                        seen.add(marker)
                        elements.append(element)
                elif result == Gst.IteratorResult.RESYNC:
                    iterator.resync()
                else:
                    break

        add_element_tree(self.pipeline)
        if self.pipeline:
            for property_name in ("video-sink", "audio-sink"):
                if self.pipeline.find_property(property_name) is None:
                    continue
                add_element_tree(self.pipeline.get_property(property_name))
        return elements

    @staticmethod
    def _element_factory_details(element):
        factory = element.get_factory() if hasattr(element, "get_factory") else None
        if not factory:
            return None, "", ""
        name = factory.get_name()
        klass = factory.get_metadata(Gst.ELEMENT_METADATA_KLASS) or ""
        return factory, name, klass

    def _log_gpu_telemetry(self, stage: str) -> None:
        if self.pipeline_mode not in {"direct", "gtk-gpu-opacity"}:
            return

        elements = self._iter_pipeline_elements()
        sink = (
            self.gtk_video_sink
            or self.wayland_sink
            or self._find_pipeline_element("wsink")
            or self._find_pipeline_element("sink")
        )
        if sink:
            _factory, sink_factory, sink_klass = self._element_factory_details(sink)
            logger.info(
                "GPU telemetry [%s]: selected sink element=%s factory=%s klass=%s",
                stage,
                sink.get_name(),
                sink_factory or "<unknown>",
                sink_klass or "<unknown>",
            )
            sink_pad = sink.get_static_pad("sink")
            if sink_pad:
                caps = sink_pad.get_current_caps() or sink_pad.query_caps()
                caps_str = caps.to_string() if caps else "<unknown>"
                logger.info(
                    "GPU telemetry [%s]: sink caps dmabuf=%s caps=%s",
                    stage,
                    "memory:DMABuf" in caps_str,
                    caps_str,
                )
        else:
            logger.warning("GPU telemetry [%s]: no video sink found.", stage)

        conversion_factories = {"videoconvert", "videoscale", "alpha"}
        conversion_elements = []
        decoder_infos = []
        hardware_decoder_found = False
        for element in elements:
            _factory, factory_name, klass = self._element_factory_details(element)
            element_name = element.get_name() if hasattr(element, "get_name") else "<unknown>"
            if factory_name in conversion_factories:
                conversion_elements.append(f"{element_name}:{factory_name}")

            is_decoder = (
                ("Decoder" in klass and "Video" in klass)
                or factory_name.endswith("dec")
                or "h264dec" in factory_name
                or "h265dec" in factory_name
            )
            if not is_decoder:
                continue

            hardware_like = (
                factory_name.startswith(("v4l2", "vaapi", "vah", "nv", "omx", "mmal"))
                or "Hardware" in klass
            )
            hardware_decoder_found = hardware_decoder_found or hardware_like
            decoder_infos.append(
                f"{element_name}:{factory_name or '<unknown>'}:"
                f"{klass or '<unknown>'}:hardware_like={hardware_like}"
            )

        if decoder_infos:
            logger.info(
                "GPU telemetry [%s]: decoder elements=%s",
                stage,
                ", ".join(decoder_infos),
            )
        else:
            logger.warning("GPU telemetry [%s]: no decoder elements found yet.", stage)

        if conversion_elements:
            logger.warning(
                "GPU telemetry [%s]: conversion/alpha elements present: %s",
                stage,
                ", ".join(conversion_elements),
            )
        else:
            logger.info(
                "GPU telemetry [%s]: no videoconvert/videoscale/alpha elements found.",
                stage,
            )

        if (
            self.require_gpu
            and stage != "setup"
            and not hardware_decoder_found
            and not self._gpu_requirement_failed
        ):
            self._gpu_requirement_failed = True
            logger.error(
                "--require-gpu requested, but no hardware decoder-like element "
                "was found in the live pipeline."
            )

    def _on_eos(self, bus, msg):
        """Callback triggered when the video finishes playing."""
        if self.video_finished:
            return
        logger.info("GStreamer: End of Stream (EOS) received.")
        self.video_finished = True

    def _on_error(self, bus, msg):
        """Callback triggered on GStreamer error."""
        err, debug = msg.parse_error()
        logger.error("GStreamer Error: %s", err.message)
        logger.error("Debug info: %s", debug)
        self.video_finished = True

    @staticmethod
    def _set_property_if_supported(element, property_name, value) -> bool:
        if not element:
            return False
        if element.find_property(property_name) is None:
            return False
        element.set_property(property_name, value)
        return True

    def _query_position_seconds(self) -> float | None:
        if not self.pipeline:
            return None
        ok, position = self.pipeline.query_position(Gst.Format.TIME)
        if not ok:
            return None
        return float(position) / Gst.SECOND

    def _wait_for_video_progress(self) -> None:
        """Wait until GStreamer reports playback progress before hiding pi3d's first frame."""
        if self.last_frame_swap_after <= 0:
            return

        logger.info(
            "Waiting for video position >= %.3fs before preparing pi3d last frame.",
            self.last_frame_swap_after,
        )
        start = time.time()
        while time.time() - start < self.last_frame_swap_timeout:
            msg = self.bus.poll(Gst.MessageType.ANY, 10000000) if self.bus else None
            if msg:
                if msg.type == Gst.MessageType.EOS:
                    self._on_eos(self.bus, msg)
                    return
                if msg.type == Gst.MessageType.ERROR:
                    self._on_error(self.bus, msg)
                    return

            position = self._query_position_seconds()
            if position is not None and position >= self.last_frame_swap_after:
                logger.info("Video position reached %.3fs; preparing pi3d last frame.", position)
                return
            self._pump_gui_events()
            time.sleep(0.02)

        logger.warning(
            "Timed out waiting for video progress after %.3fs; preparing pi3d last frame anyway.",
            self.last_frame_swap_timeout,
        )

    def _wait_for_pipeline_state(self, state, timeout_seconds=1.0):
        """Wait briefly for a requested GStreamer state to settle."""
        if not self.pipeline:
            return
        result, current, pending = self.pipeline.get_state(
            int(timeout_seconds * Gst.SECOND)
        )
        logger.info(
            "GStreamer state after requesting %s: result=%s current=%s pending=%s",
            state.value_nick,
            result.value_nick,
            current.value_nick,
            pending.value_nick,
        )

    def _query_duration_ns(self) -> int:
        if not self.pipeline:
            return 0
        ok, duration = self.pipeline.query_duration(Gst.Format.TIME)
        return int(duration) if ok else 0

    @staticmethod
    def _valid_gst_time(value) -> bool:
        if value is None:
            return False
        try:
            return int(value) >= 0 and int(value) != int(Gst.CLOCK_TIME_NONE)
        except (TypeError, ValueError, OverflowError):
            return False

    @staticmethod
    def _format_gst_time(value) -> str:
        if not VideoHandoffPoC._valid_gst_time(value):
            return "<invalid>"
        return f"{int(value) / Gst.SECOND:.6f}s"

    def _last_sample_sink(self):
        return (
            self.gtk_video_sink
            or self.wayland_sink
            or self._find_pipeline_element("wsink")
            or self._find_pipeline_element("sink")
        )

    def _get_last_sample_timestamp_seconds(self) -> float | None:
        sink = self._last_sample_sink()
        if sink is None:
            logger.warning("Last-sample PTS skipped: no video sink found.")
            return None
        if sink.find_property("last-sample") is None:
            logger.warning(
                "Last-sample PTS skipped: sink %s has no last-sample property.",
                sink.get_name(),
            )
            return None

        sample = sink.get_property("last-sample")
        if sample is None:
            logger.warning(
                "Last-sample PTS skipped: sink %s has no last sample.",
                sink.get_name(),
            )
            return None

        buffer = sample.get_buffer()
        caps = sample.get_caps()
        if buffer is None:
            logger.warning("Last-sample PTS skipped: sample has no buffer.")
            return None

        pts = buffer.pts
        dts = buffer.dts
        duration = buffer.duration
        caps_str = caps.to_string() if caps else "<unknown>"
        logger.info(
            "Last-sample: sink=%s pts=%s dts=%s duration=%s caps=%s",
            sink.get_name(),
            self._format_gst_time(pts),
            self._format_gst_time(dts),
            self._format_gst_time(duration),
            caps_str,
        )

        timestamp = pts if self._valid_gst_time(pts) else dts
        if not self._valid_gst_time(timestamp):
            logger.warning("Last-sample PTS skipped: sample has no valid PTS or DTS.")
            return None
        return int(timestamp) / Gst.SECOND

    def _get_accurate_frame_as_image(self, seek_time: float):
        """Extract a frame using slow, accurate ffmpeg seeking for EOS matching."""
        import io
        import subprocess

        cmd = [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            self.video_path,
            "-ss",
            f"{seek_time:.6f}",
            "-vframes",
            "1",
            "-f",
            "image2pipe",
            "-vcodec",
            "mjpeg",
            "-",
        ]
        try:
            process = subprocess.run(cmd, capture_output=True, check=True)
            from PIL import Image

            image = Image.open(io.BytesIO(process.stdout))
            image.load()
            return image
        except subprocess.CalledProcessError as exc:
            stderr = (
                exc.stderr.decode(errors="replace")
                if isinstance(exc.stderr, bytes)
                else exc.stderr
            )
            logger.warning(
                "Accurate last-sample frame extraction failed at %.6fs: %s",
                seek_time,
                stderr or exc,
            )
            return None
        except (OSError, ValueError) as exc:
            logger.warning(
                "Accurate last-sample frame extraction failed at %.6fs: %s",
                seek_time,
                exc,
            )
            return None

    def _refresh_last_frame_texture_from_sink_sample(self) -> bool:
        if self.last_frame_source != "gst-last-sample-pts":
            return False

        timestamp = self._get_last_sample_timestamp_seconds()
        if timestamp is None:
            return False

        extractor = VideoFrameExtractor(
            video_path=self.video_path,
            display_width=self.DISPLAY.width,
            display_height=self.DISPLAY.height,
            fit_display=False,
        )
        frame = self._get_accurate_frame_as_image(timestamp)
        if frame is None:
            logger.warning(
                "Falling back to VideoFrameExtractor seek for last-sample timestamp %.6fs.",
                timestamp,
            )
            frame = extractor._get_frame_as_image(timestamp)
        if frame is None:
            logger.warning(
                "Could not refresh pi3d last frame from last-sample timestamp %.6fs.",
                timestamp,
            )
            return False

        processed_frame = extractor._process_video_frame(frame)
        self.last_frame_texture = pi3d.Texture(processed_frame, blend=True, mipmap=True)
        self.sprite.set_textures([self.last_frame_texture, self.last_frame_texture])
        for _ in range(2):
            if not self.DISPLAY.loop_running():
                break
            self.sprite.draw()
            self._pump_gui_events()
        logger.info(
            "Updated pi3d last-frame texture from sink last-sample PTS %.6fs.",
            timestamp,
        )
        return True

    def _seek_to_handoff_frame(self, seek_mode: str, label: str) -> None:
        if seek_mode == "none":
            logger.info("%s: not seeking; keeping the frozen EOS surface.", label)
            return

        duration_ns = self._query_duration_ns()
        if duration_ns <= 0 and self.video_duration > 0:
            duration_ns = int(self.video_duration * Gst.SECOND)
        if duration_ns <= 0:
            logger.warning("%s skipped: video duration is unknown.", label)
            return

        target_ns = max(0, duration_ns - int(self.last_frame_offset * Gst.SECOND))
        seek_flags = Gst.SeekFlags.FLUSH
        if seek_mode == "accurate":
            seek_flags |= Gst.SeekFlags.ACCURATE
        else:
            seek_flags |= Gst.SeekFlags.KEY_UNIT

        logger.info(
            "%s: seeking to %.3fs with %s mode.",
            label,
            target_ns / Gst.SECOND,
            seek_mode,
        )
        self.pipeline.seek_simple(Gst.Format.TIME, seek_flags, target_ns)
        self.pipeline.set_state(Gst.State.PAUSED)
        self._wait_for_pipeline_state(Gst.State.PAUSED)

    def _apply_eos_alpha_probe(self) -> None:
        """Try to repaint the final video frame with a tiny alpha value after EOS."""
        if self.pipeline_mode != "alpha-probe":
            return
        if not self.eos_alpha_element:
            logger.warning("EOS alpha probe skipped: no alpha element in pipeline.")
            return

        logger.info("EOS alpha probe: setting alpha to %.3f", self.eos_alpha)
        self.eos_alpha_element.set_property("alpha", self.eos_alpha)
        self._seek_to_handoff_frame(
            self.alpha_probe_seek_mode,
            "EOS alpha probe",
        )

    def _apply_gtk_gpu_opacity_probe(self) -> None:
        """Try to wake the compositor by changing the GTK window opacity at EOS."""
        if self.pipeline_mode != "gtk-gpu-opacity":
            return
        if not self.gtk_window:
            logger.warning("GTK GPU opacity probe skipped: no GTK video window.")
            return

        self._seek_to_handoff_frame(
            self.gpu_eos_seek_mode,
            "GTK GPU opacity probe",
        )
        self._refresh_last_frame_texture_from_sink_sample()
        logger.info(
            "GTK GPU opacity probe: setting window opacity to %.3f.",
            self.eos_window_opacity,
        )
        self.gtk_window.set_opacity(self.eos_window_opacity)
        self._pump_gui_events()

    def _force_pi3d_last_frame_redraw(self, seconds: float) -> None:
        if seconds <= 0:
            return
        logger.info("Forcing pi3d redraw for %.3fs before closing video.", seconds)
        self.sprite.set_textures([self.last_frame_texture, self.last_frame_texture])
        redraw_start = time.time()
        while self.DISPLAY.loop_running() and (time.time() - redraw_start) < seconds:
            self.sprite.draw()
            self._pump_gui_events()
            time.sleep(0.01)

    def _handle_eos_handoff_probe(self) -> None:
        """Freeze video at EOS, optionally reduce alpha, redraw pi3d, then close video."""
        logger.info("EOS handoff probe: pausing pipeline to keep last video frame visible.")
        self.pipeline.set_state(Gst.State.PAUSED)
        self._wait_for_pipeline_state(Gst.State.PAUSED)
        self._apply_eos_alpha_probe()
        if self.pipeline_mode == "gtk-gpu-opacity":
            self._apply_gtk_gpu_opacity_probe()
        else:
            self._refresh_last_frame_texture_from_sink_sample()
        self._force_pi3d_last_frame_redraw(self.eos_redraw_seconds)

    def _do_blend(self, from_tex, to_tex, duration):
        """Blend from one texture to another over the specified duration."""
        self.sprite.set_textures([from_tex, to_tex])
        self.sprite.unif[44] = 1.0
        self.sprite.draw()
        start = time.time()
        while self.DISPLAY.loop_running():
            progress = min((time.time() - start) / duration, 1.0)
            self.sprite.unif[44] = 1.0 - progress
            self.sprite.draw()
            self._pump_gui_events()
            if progress >= 1.0:
                break
            time.sleep(0.01)

    def run(self):
        """Main execution loop."""
        logger.info("Starting PoC Loop...")

        # Phase 1: Show Image1
        logger.info("Phase 1: Displaying Image (pi3d)")
        self.sprite.set_textures([self.texture1, self.texture1])
        start_time = time.time()
        while self.DISPLAY.loop_running() and (time.time() - start_time) < 3.0:
            self.sprite.draw()
            self._pump_gui_events()

        # Phase 2: Blend to first frame
        logger.info("Phase 2: Blending to first video frame")
        self._do_blend(self.texture1, self.first_frame_texture, self.blend_time)

        # 3. Start Video (GStreamer) behind the image
        logger.info("Phase 3: Starting Video (GStreamer) in background")
        logger.info("Video duration: %.2f seconds", self.video_duration)

        # Now start playing
        self._show_gtk_video_window()
        self.pipeline.set_state(Gst.State.PLAYING)
        video_start = time.time()

        # 4. Wait for Video to Finish
        logger.info("Phase 4: Waiting for video to finish...")
        self._wait_for_video_progress()
        self._log_gpu_telemetry("playing")

        logger.info("Phase 5: Swap to last video frame texture before video stops")
        # Swap the texture to the second image while the video is playing
        # so it's ready when the video stops
        self.sprite.set_textures([self.last_frame_texture, self.last_frame_texture])

        # Flush the swap chain for 100ms (guarantees ~6 frames at 60Hz)
        flush_start = time.time()
        while self.DISPLAY.loop_running() and (time.time() - flush_start) < 0.1:
            self.sprite.draw()
            self._pump_gui_events()

        while not self.video_finished:
            # Poll GStreamer bus for EOS
            msg = self.bus.poll(Gst.MessageType.ANY, 10000000)  # 10ms timeout
            if msg:
                if msg.type == Gst.MessageType.EOS:
                    self._on_eos(self.bus, msg)
                elif msg.type == Gst.MessageType.ERROR:
                    self._on_error(self.bus, msg)

            # Add a small sleep to prevent CPU spinning if poll returns immediately
            self._pump_gui_events()
            time.sleep(0.01)

            # Failsafe timeout to prevent hanging forever if EOS is missed
            timeout = self.max_video_seconds or max(10.0, self.video_duration + 5.0)
            if time.time() - video_start > timeout:
                logger.warning("Phase 4: Failsafe timeout reached. Forcing video finish.")
                self.video_finished = True

        video_actual = time.time() - video_start
        self._handle_eos_handoff_probe()
        self._log_gpu_telemetry("eos")

        # Stop video after the handoff probe.
        self.pipeline.set_state(Gst.State.NULL)
        self._close_gtk_video_window()

        # Force GStreamer to process the state change and destroy the window
        while self.bus.poll(Gst.MessageType.ANY, 10000000): # 10ms
            self._pump_gui_events()
            pass

        # Phase 6: Blend to Image2
        logger.info("Phase 6: Blending to final image")
        self._do_blend(self.last_frame_texture, self.texture2, self.blend_time)

        # Phase 7: Show Image2
        logger.info("Phase 7: Displaying Image 2 (final)")
        start_time = time.time()
        while self.DISPLAY.loop_running() and (time.time() - start_time) < 3.0:
            self.sprite.draw()
            self._pump_gui_events()

        if self.video_duration > 0:
            speed = self.video_duration / video_actual
            logger.info("Video playback: %.2fs (expected) vs %.2fs (actual) = %.2fx speed",
                        self.video_duration, video_actual, speed)
        logger.info("PoC Complete. Cleaning up.")
        self.DISPLAY.destroy()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    parser.add_argument("video")
    parser.add_argument("image2", nargs="?")
    parser.add_argument("--blend-time", type=float, default=5.0)
    parser.add_argument(
        "--pipeline-mode",
        choices=("direct", "compatible", "alpha-probe", "gtk-gpu-opacity"),
        default="direct",
        help=(
            "direct keeps video playback unconverted; compatible uses legacy "
            "scale/convert/alpha; alpha-probe keeps alpha opaque while playing "
            "and changes it near EOS; gtk-gpu-opacity uses gtkwaylandsink without "
            "forced conversion and changes GTK window opacity at EOS."
        ),
    )
    parser.add_argument(
        "--eos-alpha",
        type=float,
        default=0.99,
        help="Alpha used by --pipeline-mode alpha-probe after EOS.",
    )
    parser.add_argument(
        "--eos-redraw-seconds",
        type=float,
        default=0.25,
        help="Seconds to force pi3d redraw after EOS before closing the video window.",
    )
    parser.add_argument(
        "--eos-alpha-seek-offset",
        type=float,
        default=0.1,
        help=(
            "Deprecated alias for --last-frame-offset. Seconds before the end "
            "to seek for the alpha-probe preroll frame."
        ),
    )
    parser.add_argument(
        "--max-video-seconds",
        type=float,
        default=0.0,
        help="Failsafe timeout while waiting for EOS. 0 means video duration + 5s.",
    )
    parser.add_argument(
        "--shader-path",
        default="",
        help=(
            "Optional shader base path without .fs/.vs. Default search order: "
            "~/.picframe/data/shaders/blend_new, installed package data, repo data."
        ),
    )
    parser.add_argument(
        "--last-frame-swap-after",
        type=float,
        default=0.5,
        help=(
            "Wait until GStreamer reports this playback position before swapping pi3d "
            "to the last-frame texture."
        ),
    )
    parser.add_argument(
        "--last-frame-swap-timeout",
        type=float,
        default=5.0,
        help="Maximum seconds to wait for playback progress before swapping anyway.",
    )
    parser.add_argument(
        "--last-frame-offset",
        type=float,
        default=None,
        help=(
            "Seconds before video duration used for both the PoC pi3d handoff frame "
            "and the alpha-probe EOS seek. Defaults to --eos-alpha-seek-offset."
        ),
    )
    parser.add_argument(
        "--alpha-probe-seek-mode",
        choices=("key-unit", "accurate", "none"),
        default="key-unit",
        help=(
            "How alpha-probe refreshes the frozen frame after EOS. key-unit is fast "
            "but may jump backwards, accurate seeks closer to the requested timestamp, "
            "none only changes the alpha property without sending a new frame."
        ),
    )
    parser.add_argument(
        "--eos-window-opacity",
        type=float,
        default=0.99,
        help="GTK video window opacity used by --pipeline-mode gtk-gpu-opacity after EOS.",
    )
    parser.add_argument(
        "--gpu-eos-seek-mode",
        choices=("none", "accurate"),
        default="none",
        help=(
            "How gtk-gpu-opacity handles the frozen frame at EOS. none keeps the "
            "actual EOS surface, accurate seeks close to the requested handoff timestamp."
        ),
    )
    parser.add_argument(
        "--require-gpu",
        action="store_true",
        help="Log an error if no hardware decoder-like element is found in GPU modes.",
    )
    parser.add_argument(
        "--last-frame-source",
        choices=("cached-offset", "gst-last-sample-pts"),
        default="cached-offset",
        help=(
            "Source for the pi3d handoff texture. cached-offset uses the precomputed "
            "duration-offset frame; gst-last-sample-pts extracts from the sink's actual "
            "last-sample timestamp at EOS."
        ),
    )
    args = parser.parse_args()
    
    if not Path(args.image).exists():
        sys.exit(1)
    if not Path(args.video).exists():
        sys.exit(1)
        
    VideoHandoffPoC(
        args.image,
        args.video,
        args.image2,
        args.blend_time,
        args.pipeline_mode,
        args.eos_alpha,
        args.eos_redraw_seconds,
        args.eos_alpha_seek_offset,
        args.max_video_seconds,
        args.shader_path,
        args.last_frame_swap_after,
        args.last_frame_swap_timeout,
        args.last_frame_offset,
        args.alpha_probe_seek_mode,
        args.eos_window_opacity,
        args.gpu_eos_seek_mode,
        args.require_gpu,
        args.last_frame_source,
    ).run()
