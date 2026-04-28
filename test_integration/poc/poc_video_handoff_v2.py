#!/usr/bin/env python3
"""
Proof of Concept: Video Handoff (Phase 0)
This script tests the seamless EGL/OpenGL context handoff between pi3d (images)
and GStreamer (video) across different platforms (macOS, Raspberry Pi).

Usage:
    python3 poc_video_handoff_v2.py <image_path_1> <video_path> <image_path_2>
"""

import sys
import time
import platform
import argparse
import logging
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
    from picframe.video_streamer import VideoFrameExtractor
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
    def __init__(self, image_path: str, video_path: str, image2_path: str = "", blend_time: float = 5.0):
        self.image_path = image_path
        self.video_path = video_path
        self.image2_path = image2_path or image_path
        self.blend_time = blend_time
        self.first_frame_texture = None
        self.last_frame_texture = None
        self.video_duration = self._get_video_duration(video_path)
        self.os_name = platform.system()
        # State variables
        self.video_finished = False
        self.pipeline = None
        self.bus = None

        logger.info("Detected OS: %s", self.os_name)

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
            self.SHADER = pi3d.Shader("src/picframe/data/shaders/blend_new")

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

    def _extract_video_frames(self):
        """Extract the first and last frames from the video using VideoFrameExtractor."""
        logger.info("Extracting video frames...")
        extractor = VideoFrameExtractor(
            video_path=self.video_path,
            display_width=self.DISPLAY.width,
            display_height=self.DISPLAY.height,
            fit_display=False
        )
        frames = extractor.get_first_and_last_frames()
        if frames:
            frame_first, frame_last = frames
            self.first_frame_texture = pi3d.Texture(frame_first, blend=True, mipmap=True)
            self.last_frame_texture = pi3d.Texture(frame_last, blend=True, mipmap=True)
            logger.info("Frames extracted: %s, %s", frame_first.size, frame_last.size)
        else:
            logger.error("Failed to extract frames from video.")
            sys.exit(1)

    def _setup_gstreamer(self):
        """Initialize GStreamer pipeline for video playback."""
        logger.info("Setting up GStreamer pipeline...")

        # Convert video path to URI format for GStreamer
        uri = Path(self.video_path).absolute().as_uri()

        # Hardware acceleration is essential on the Pi.
        # 'playbin' usually auto-detects hardware decoders (v4l2).
        # We use videoscale and videoconvert to ensure compatibility with waylandsink.
        # 'add-borders=false' prevents letterboxing by scaling to fill.
        # coloralpha is used, to ensure pi3d can blend the video frames with the images correctly.
        video_sink_str = (
            "videoscale add-borders=false ! "
            "videoconvert ! "
            "coloralpha alpha=0.99 ! "
            "waylandsink fullscreen=true"
        )

        pipeline_str = f"playbin uri={uri} video-sink=\"{video_sink_str}\""
        logger.info("Pipeline: %s", pipeline_str)

        try:
            self.pipeline = Gst.parse_launch(pipeline_str)
        except Exception as e:
            logger.error("Failed to parse GStreamer pipeline: %s", e)
            sys.exit(1)

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

    def _on_eos(self, bus, msg):
        """Callback triggered when the video finishes playing."""
        logger.info("GStreamer: End of Stream (EOS) received.")
        self.video_finished = True

    def _on_error(self, bus, msg):
        """Callback triggered on GStreamer error."""
        err, debug = msg.parse_error()
        logger.error("GStreamer Error: %s", err.message)
        logger.error("Debug info: %s", debug)
        self.video_finished = True

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

        # Phase 2: Blend to first frame
        logger.info("Phase 2: Blending to first video frame")
        self._do_blend(self.texture1, self.first_frame_texture, self.blend_time)

        # 3. Start Video (GStreamer) behind the image
        logger.info("Phase 3: Starting Video (GStreamer) in background")
        logger.info("Video duration: %.2f seconds", self.video_duration)

        # Now start playing
        self.pipeline.set_state(Gst.State.PLAYING)
        video_start = time.time()

        # 4. Wait for Video to Finish
        logger.info("Phase 4: Waiting for video to finish...")
        time.sleep(0.5)  # Short delay to ensure video starts before we swap textures

        logger.info("Phase 5: Swap to last video frame texture before video stops")
        # Swap the texture to the second image while the video is playing
        # so it's ready when the video stops
        self.sprite.set_textures([self.last_frame_texture, self.last_frame_texture])

        # Flush the swap chain for 100ms (guarantees ~6 frames at 60Hz)
        flush_start = time.time()
        while self.DISPLAY.loop_running() and (time.time() - flush_start) < 0.1:
            self.sprite.draw()

        while not self.video_finished:
            # Poll GStreamer bus for EOS
            msg = self.bus.poll(Gst.MessageType.ANY, 10000000)  # 10ms timeout
            if msg:
                if msg.type == Gst.MessageType.EOS:
                    self._on_eos(self.bus, msg)
                elif msg.type == Gst.MessageType.ERROR:
                    self._on_error(self.bus, msg)

            # Add a small sleep to prevent CPU spinning if poll returns immediately
            time.sleep(0.01)

            # Failsafe timeout to prevent hanging forever if EOS is missed
            if time.time() - video_start > 10.0:  # 10 seconds max
                logger.warning("Phase 4: Failsafe timeout reached. Forcing video finish.")
                self.video_finished = True

        # Stop Video first so it disappears immediately
        video_actual = time.time() - video_start
        self.pipeline.set_state(Gst.State.NULL)

        # Force GStreamer to process the state change and destroy the window
        while self.bus.poll(Gst.MessageType.ANY, 10000000): # 10ms
            pass

        # Phase 6: Blend to Image2
        logger.info("Phase 6: Blending to final image")
        self._do_blend(self.last_frame_texture, self.texture2, self.blend_time)

        # Phase 7: Show Image2
        logger.info("Phase 7: Displaying Image 2 (final)")
        start_time = time.time()
        while self.DISPLAY.loop_running() and (time.time() - start_time) < 3.0:
            self.sprite.draw()

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
    args = parser.parse_args()
    
    if not Path(args.image).exists():
        sys.exit(1)
    if not Path(args.video).exists():
        sys.exit(1)
        
    VideoHandoffPoC(args.image, args.video, args.image2, args.blend_time).run()