"""
GStreamer Video Renderer implementation.
"""
from __future__ import annotations
import logging
from pathlib import Path
from typing import Any, TYPE_CHECKING

from picframe.core.events.dto import PlaybackCompletedEvent, SystemErrorEvent
from picframe.core.events.interfaces import IEventPublisher
from picframe.core.models.media import MediaItem
from picframe.core.renderers.interfaces import IVideoPlayer

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    class Gst:
        Element = Any
        Bus = Any
        Bin = Any
        Pad = Any
        Caps = Any
        ElementFactory = Any
        Message = Any
        Pipeline = Any
        State = Any
        MessageType = Any
        GhostPad = Any
        ELEMENT_METADATA_KLASS = Any

try:
    import gi  # type: ignore
    gi.require_version('Gst', '1.0')  # type: ignore
    from gi.repository import Gst  # type: ignore
    Gst.init(None)
    GST_AVAILABLE = True
except ImportError:
    Gst = Any  # type: ignore
    logger.warning("GStreamer not available. Video playback will be disabled.")
    GST_AVAILABLE = False


from picframe.core.renderers.gst_utils import ffprobe_codec_to_gst_caps, is_hardware_supported

class GstVideoRenderer(IVideoPlayer):
    """
    Video player implementation using GStreamer.
    """

    def __init__(self, event_publisher: IEventPublisher, max_software_decode_resolution: str = "1280x720"):
        self._publisher = event_publisher
        self._max_software_decode_resolution = max_software_decode_resolution
        self._pipeline: Gst.Element | None = None
        self._bus: Gst.Bus | None = None
        self._current_media: MediaItem | None = None
        self._volume: float = 1.0

    def play(self, media_item: MediaItem) -> None:
        """Start playing the specified video media item."""
        if not GST_AVAILABLE:
            logger.error("Cannot play video: GStreamer is not installed.")
            self._publisher.publish(PlaybackCompletedEvent())
            return

        self.stop()
        self._current_media = media_item

        uri = Path(media_item.filepath).absolute().as_uri()

        # 1. Threshold-Based Rejection
        media_caps_str = ffprobe_codec_to_gst_caps(
            media_item.codec,
            media_item.width,
            media_item.height,
            media_item.framerate
        )
        
        hw_supported = is_hardware_supported(media_caps_str) if media_caps_str else False
        
        if not hw_supported:
            # Check if it exceeds software limits
            try:
                max_w, max_h = map(int, self._max_software_decode_resolution.split('x'))
                if media_item.width and media_item.height:
                    if media_item.width > max_w or media_item.height > max_h:
                        msg = f"Media resolution ({media_item.width}x{media_item.height}) exceeds hardware decoder limits and is too large for software fallback (max {self._max_software_decode_resolution}). Skipping file."
                        logger.warning(msg)
                        self._publisher.publish(SystemErrorEvent(message=msg, component="GstVideoRenderer"))
                        self._publisher.publish(PlaybackCompletedEvent())
                        return
            except ValueError:
                logger.error(f"Invalid max_software_decode_resolution format: {self._max_software_decode_resolution}")

        # 2. Construct Pipeline using uridecodebin
        try:
            self._pipeline = Gst.Pipeline.new("video-player")
            
            # Create elements
            uridecodebin = Gst.ElementFactory.make("uridecodebin", "decoder")
            uridecodebin.set_property("uri", uri)
            
            # Connect to autoplug-select for observability
            uridecodebin.connect("autoplug-select", self._on_autoplug_select)
            
            # Create custom sink bin
            sink_bin = self._create_sink_bin()
            
            if self._pipeline:
                self._pipeline.add(uridecodebin)
                self._pipeline.add(sink_bin)
                
                # Link dynamically when pads are added
                uridecodebin.connect("pad-added", self._on_pad_added, sink_bin)
            
        except Exception as e:
            logger.error(f"Failed to construct GStreamer pipeline: {e}")
            self._publisher.publish(SystemErrorEvent(message=str(e), component="GstVideoRenderer"))
            self._publisher.publish(PlaybackCompletedEvent())
            return

        if self._pipeline:
            try:
                self._pipeline.set_property("volume", self._volume)
            except TypeError:
                pass # Custom pipeline doesn't have volume property
            self._bus = self._pipeline.get_bus()
            
            import threading
            self._stop_event = threading.Event()
            self._poll_thread = threading.Thread(target=self._poll_bus, daemon=True)
            self._poll_thread.start()

            self._pipeline.set_state(Gst.State.PLAYING)
            logger.info(f"Started video playback: {media_item.filepath}")

    def _create_sink_bin(self) -> Gst.Bin:
        """Creates a custom bin for format conversion and hardware-accelerated rendering."""
        bin = Gst.Bin.new("sink_bin")
        
        from picframe.core.renderers.gst_utils import find_best_element
        hw_converter = find_best_element(["v4l2convert"])
        
        elements = []
        if hw_converter:
            logger.debug(f"Using hardware converter/scaler: {hw_converter}")
            conv = Gst.ElementFactory.make(hw_converter, "conv")
            elements.append(conv)
            sink_pad_element = conv
        else:
            logger.debug("Using software fallback scaler and converter")
            conv1 = Gst.ElementFactory.make("videoconvert", "conv1")
            scale = Gst.ElementFactory.make("videoscale", "scale")
            scale.set_property("add-borders", False)
            conv2 = Gst.ElementFactory.make("videoconvert", "conv2")
            elements.extend([conv1, scale, conv2])
            sink_pad_element = conv1
            
        # Force an alpha-enabled pixel format (RGBA).
        # This is the critical Wayland synchronization fix:
        # By presenting a surface with an alpha channel, the Wayland compositor disables
        # occlusion culling for the underlying pi3d window, allowing it to pre-render
        # the next image in the background.
        capsfilter = Gst.ElementFactory.make("capsfilter", "capsfilter")
        caps = Gst.Caps.from_string("video/x-raw,format=RGBA")
        capsfilter.set_property("caps", caps)
        elements.append(capsfilter)
        
        # Use the software alpha element to force 99% opacity.
        # This ensures compatibility across both native hardware and VMs,
        # as waylandsink's native alpha property is often unsupported or buggy in VMs.
        alpha = Gst.ElementFactory.make("alpha", "alpha")
        alpha.set_property("alpha", 0.99)
        elements.append(alpha)
            
        # Prioritize waylandsink for native hardware and fullscreen support, then fallback to glimagesink for VMs
        sink_name = find_best_element(["waylandsink", "glimagesink", "ximagesink", "autovideosink"])
        if not sink_name:
            sink_name = "autovideosink"
            
        sink = Gst.ElementFactory.make(sink_name, "sink")
        
        # Set fullscreen property if supported by the sink
        try:
            # glimagesink doesn't have a fullscreen property, it relies on the window manager
            # waylandsink does have a fullscreen property
            if hasattr(sink.props, 'fullscreen'):
                sink.set_property("fullscreen", True)
        except Exception as e:
            logger.debug(f"Could not set fullscreen property on {sink_name}: {e}")

        # Only set waylandsink specific properties if it's actually a waylandsink
        if sink_name == "waylandsink":
            sink.set_property("rotate-method", 8) # GST_VIDEO_ORIENTATION_AUTO
            
        elements.append(sink)
        
        for elem in elements:
            bin.add(elem)
            
        # Link elements sequentially
        for i in range(len(elements) - 1):
            elements[i].link(elements[i+1])
            
        # Add ghost pad to the bin
        pad = sink_pad_element.get_static_pad("sink")
        ghost_pad = Gst.GhostPad.new("sink", pad)
        bin.add_pad(ghost_pad)
        
        return bin

    def _on_pad_added(self, element: Gst.Element, pad: Gst.Pad, sink_bin: Gst.Bin) -> None:
        """Dynamically links uridecodebin to the sink bin."""
        caps = pad.get_current_caps()
        if not caps:
            caps = pad.query_caps()
            
        if caps:
            struct = caps.get_structure(0)
            name = struct.get_name()
            logger.debug(f"uridecodebin added pad with caps: {name}")
            if name.startswith("video/"):
                sink_pad = sink_bin.get_static_pad("sink")
                if not sink_pad.is_linked():
                    ret = pad.link(sink_pad)
                    logger.debug(f"Linked video pad to sink_bin: {ret}")
                    
                    # Force state change on the sink bin to ensure it plays
                    sink_bin.sync_state_with_parent()
                else:
                    logger.debug("sink_bin is already linked")

    def _on_autoplug_select(self, bin: Gst.Element, pad: Gst.Pad, caps: Gst.Caps, factory: Gst.ElementFactory) -> int:
        """Observes element selection to detect software fallbacks."""
        klass = factory.get_metadata(Gst.ELEMENT_METADATA_KLASS)
        if klass and "Decoder" in klass and "Video" in klass and "Hardware" not in klass:
            logger.warning(f"Hardware GPU decoding unavailable for this stream. Autoplugger selected software fallback: {factory.get_name()}")
            # We could emit a PerformanceWarningEvent here if desired
        return 0 # GST_AUTOPLUG_SELECT_TRY

    def _poll_bus(self) -> None:
        """Poll the GStreamer bus for messages in a background thread."""
        while not self._stop_event.is_set() and self._bus:
            # Poll for 100ms
            msg = self._bus.poll(Gst.MessageType.EOS | Gst.MessageType.ERROR, 100000000)
            if msg:
                if msg.type == Gst.MessageType.EOS:
                    self._on_eos(self._bus, msg)
                    break
                elif msg.type == Gst.MessageType.ERROR:
                    self._on_error(self._bus, msg)
                    break

    def stop(self) -> None:
        """Stop video playback."""
        if self._pipeline:
            if hasattr(self, '_stop_event'):
                self._stop_event.set()
            
            import threading
            if hasattr(self, '_poll_thread') and self._poll_thread.is_alive():
                if threading.current_thread() != self._poll_thread:
                    self._poll_thread.join(timeout=0.5)

            self._pipeline.set_state(Gst.State.NULL)
            
            # Force GStreamer to process the state change and destroy the window
            if self._bus:
                while self._bus.poll(Gst.MessageType.ANY, 10000000): # type: ignore # pylint: disable=no-member
                    pass
                
            self._pipeline = None
            self._bus = None
            self._current_media = None
            logger.debug("Stopped video playback.")

    def pause(self) -> None:
        """Pause video playback."""
        if self._pipeline:
            self._pipeline.set_state(Gst.State.PAUSED)
            logger.debug("Paused video playback.")

    def resume(self) -> None:
        """Resume paused video playback."""
        if self._pipeline:
            self._pipeline.set_state(Gst.State.PLAYING)
            logger.debug("Resumed video playback.")

    def set_volume(self, level: float) -> None:
        """Set the audio volume level (0.0 to 1.0)."""
        self._volume = max(0.0, min(1.0, level))
        if self._pipeline:
            try:
                self._pipeline.set_property("volume", self._volume)
            except TypeError:
                pass
            logger.debug(f"Set video volume to {self._volume}")

    def _on_eos(self, bus: Gst.Bus, msg: Gst.Message) -> None:
        """Callback triggered when the video finishes playing."""
        logger.info("GStreamer: End of Stream (EOS) received.")
        self.stop()
        self._publisher.publish(PlaybackCompletedEvent())

    def _on_error(self, bus: Gst.Bus, msg: Gst.Message) -> None:
        """Callback triggered on GStreamer error."""
        err, debug = msg.parse_error()
        logger.error(f"GStreamer Error: {err.message}")
        logger.error(f"Debug info: {debug}")
        self.stop()
        self._publisher.publish(SystemErrorEvent(message=err.message, component="GstVideoRenderer"))
        self._publisher.publish(PlaybackCompletedEvent())
