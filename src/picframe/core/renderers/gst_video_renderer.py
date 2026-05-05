"""
GStreamer Video Renderer implementation.
"""
import logging
from pathlib import Path

from picframe.core.events.dto import PlaybackCompletedEvent, SystemErrorEvent
from picframe.core.events.interfaces import IEventPublisher
from picframe.core.models.media import MediaItem
from picframe.core.renderers.interfaces import IVideoPlayer

logger = logging.getLogger(__name__)

try:
    import gi
    gi.require_version('Gst', '1.0')
    from gi.repository import Gst
    Gst.init(None)
    GST_AVAILABLE = True
except ImportError:
    logger.warning("GStreamer not available. Video playback will be disabled.")
    GST_AVAILABLE = False


class GstVideoRenderer(IVideoPlayer):
    """
    Video player implementation using GStreamer.
    """

    def __init__(self, event_publisher: IEventPublisher):
        self._publisher = event_publisher
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
        
        # Attempt direct hardware playback first
        hw_pipeline_str = f"playbin uri={uri} video-sink=\"waylandsink fullscreen=true\""
        
        # Fallback software conversion pipeline
        sw_sink_str = (
            "videoconvert ! "
            "videoscale add-borders=false ! "
            "videoconvert ! "
            "video/x-raw,format=RGBA ! "
            "coloralpha alpha=0.99 ! "
            "waylandsink fullscreen=true"
        )
        sw_pipeline_str = f"playbin uri={uri} video-sink=\"{sw_sink_str}\""

        try:
            logger.debug(f"Attempting hardware GStreamer Pipeline: {hw_pipeline_str}")
            self._pipeline = Gst.parse_launch(hw_pipeline_str)
            
            # Test if the pipeline can reach PAUSED state (negotiation succeeds)
            ret = self._pipeline.set_state(Gst.State.PAUSED)
            if ret == Gst.StateChangeReturn.ASYNC:
                # Wait up to 5 seconds for state change to complete
                # get_state returns a tuple: (Gst.StateChangeReturn, state, pending)
                ret, state, pending = self._pipeline.get_state(5 * Gst.SECOND)
                
            if ret == Gst.StateChangeReturn.FAILURE:
                logger.warning(
                    "Hardware GPU decoding unsupported or failed. "
                    "Falling back to software format conversion. "
                    "For optimal performance, convert videos externally."
                )
                self._pipeline.set_state(Gst.State.NULL)
                logger.debug(f"Using fallback software GStreamer Pipeline: {sw_pipeline_str}")
                self._pipeline = Gst.parse_launch(sw_pipeline_str)
                
        except Exception as e:
            logger.error(f"Failed to parse GStreamer pipeline: {e}")
            self._publisher.publish(SystemErrorEvent(message=str(e), component="GstVideoRenderer"))
            self._publisher.publish(PlaybackCompletedEvent())
            return

        self._pipeline.set_property("volume", self._volume)

        self._bus = self._pipeline.get_bus()
        
        import threading
        self._stop_event = threading.Event()
        self._poll_thread = threading.Thread(target=self._poll_bus, daemon=True)
        self._poll_thread.start()

        self._pipeline.set_state(Gst.State.PLAYING)
        logger.info(f"Started video playback: {media_item.filepath}")

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
                while self._bus.poll(Gst.MessageType.ANY, 10000000): # 10ms
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
            self._pipeline.set_property("volume", self._volume)
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
