#!/usr/bin/env python3
"""
Proof of Concept: Video Handoff (Phase 0)
This script tests the seamless EGL/OpenGL context handoff between pi3d (images)
and GStreamer (video) across different platforms (macOS, Raspberry Pi).

Usage:
    python3 poc_video_handoff.py <image_path> <video_path>
"""

import sys
import time
import platform
import argparse
import logging
import os
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
    import gi
    gi.require_version('Gst', '1.0')
    gi.require_version('GstVideo', '1.0')
    from gi.repository import Gst, GLib, GstVideo  # noqa: F401
except ImportError:
    logger.error("PyGObject or GStreamer is not installed.")
    logger.error("macOS: brew install gstreamer pygobject3")
    logger.error("Ubuntu/RPi: sudo apt install python3-gi gstreamer1.0-tools "
                 "gstreamer1.0-plugins-base gstreamer1.0-plugins-good "
                 "gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly")
    sys.exit(1)

# Initialize GStreamer
Gst.init(None)


class VideoHandoffPoC:
    def __init__(self, image_path: str, video_path: str, image2_path: str = None):
        self.image_path = image_path
        self.video_path = video_path
        self.image2_path = image2_path if image2_path else image_path
        self.os_name = platform.system()
        
        logger.info(f"Detected OS: {self.os_name}")
        
        # State
        self.video_finished = False
        self.pipeline = None
        self.bus = None
        
        # Setup pi3d Display
        self._setup_pi3d()
        
        # Setup GStreamer Pipeline
        self._setup_gstreamer()

    def _setup_pi3d(self):
        """Initialize pi3d display based on the platform."""
        logger.info("Initializing pi3d display...")
        self.mock_pi3d = False
        
        try:
            # Raspberry Pi native EGL/DRM or Wayland
            self.DISPLAY = pi3d.Display.create(
                x=0, y=0, frames_per_second=60,
                display_config=pi3d.DISPLAY_CONFIG_HIDE_CURSOR | pi3d.DISPLAY_CONFIG_NO_FRAME | pi3d.DISPLAY_CONFIG_FULLSCREEN,
                background=(0.0, 0.0, 0.0, 1.0), use_glx=False, use_sdl2=True
            )
            
            self.CAMERA = pi3d.Camera(is_3d=False)
            self.SHADER = pi3d.Shader("src/picframe/data/shaders/blend_new")
            
            # Load the test images
            logger.info(f"Loading image 1: {self.image_path}")
            self.texture1 = pi3d.Texture(self.image_path, blend=True, mipmap=True)
            logger.info(f"Loading image 2: {self.image2_path}")
            self.texture2 = pi3d.Texture(self.image2_path, blend=True, mipmap=True)
            
            # Create a sprite to hold the texture
            self.sprite = pi3d.Sprite(camera=self.CAMERA, w=self.DISPLAY.width, h=self.DISPLAY.height, z=5.0)
            self.sprite.set_shader(self.SHADER)
            self.sprite.set_textures([self.texture1, self.texture1])
            
            # Set uniforms required by blend_new shader
            self.sprite.unif[42] = 1.0 # w_rat_f
            self.sprite.unif[43] = 1.0 # h_rat_f
            self.sprite.unif[44] = 1.0 # alpha
            self.sprite.unif[45] = 1.0 # w_rat_b
            self.sprite.unif[46] = 1.0 # h_rat_b
            self.sprite.unif[47] = 0.5 # edge_alpha
            self.sprite.unif[48] = 0.0 # x_off_f
            self.sprite.unif[49] = 0.0 # y_off_f
            self.sprite.unif[51] = 0.0 # x_off_b
            self.sprite.unif[52] = 0.0 # y_off_b
            self.sprite.unif[54] = 0.0 # blend_type
            self.sprite.unif[55] = 1.0 # brightness
            
        except (Exception, TypeError) as e:
            logger.error(f"pi3d initialization failed: {e}")
            sys.exit(1)

    def _setup_gstreamer(self):
        """Construct the GStreamer pipeline based on the platform."""
        logger.info("Constructing GStreamer pipeline...")
        
        # Convert path to URI
        uri = Path(self.video_path).absolute().as_uri()
        
        # Raspberry Pi: Hardware decoding and native sink
        # This is the critical part to test on actual hardware.
        # We need to ensure the video sink sits *behind* the pi3d EGL layer.
        # kmssink or waylandsink depending on the OS version (Bullseye vs Bookworm)
        # For this PoC, we'll try a generic hardware pipeline first.
        # We force waylandsink and set the window size to match pi3d
        # We also use videoscale to ensure the video matches the 800x600 window
        # add-borders=false ensures the video fills the space without letterboxing
        # We add videoconvert to ensure the pixel format is compatible with waylandsink
        # We also set the window-width and window-height properties on waylandsink
        pipeline_str = f"playbin uri={uri} video-sink=\"videoscale add-borders=false ! videoconvert ! waylandsink fullscreen=true\""
        # Note: In a real RPi environment, we might need to explicitly define:
        # uridecodebin ! v4l2h264dec ! kmssink plane-id=...
            
        logger.info(f"Pipeline: {pipeline_str}")
        
        try:
            self.pipeline = Gst.parse_launch(pipeline_str)
        except GLib.Error as e:
            logger.error(f"Failed to create pipeline: {e}")
            sys.exit(1)
            
        # Setup Bus to listen for EOS (End of Stream) and Window embedding
        self.bus = self.pipeline.get_bus()
        self.bus.add_signal_watch()
        self.bus.enable_sync_message_emission()
        self.bus.connect("message::eos", self._on_eos)
        self.bus.connect("message::error", self._on_error)
        self.bus.connect("sync-message::element", self._on_sync_message)

    def _on_sync_message(self, bus, msg):
        """Synchronous message handler for window embedding."""
        if msg.get_structure() and msg.get_structure().get_name() == "prepare-window-handle":
            logger.info("GStreamer: prepare-window-handle received.")
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
        logger.error(f"GStreamer Error: {err.message}")
        logger.error(f"Debug info: {debug}")
        self.video_finished = True

    def run(self):
        """Main execution loop."""
        logger.info("Starting PoC Loop...")
        
        # 1. Show Image (pi3d)
        logger.info("Phase 1: Displaying Image (pi3d)")
        start_time = time.time()
        while self.DISPLAY.loop_running() and (time.time() - start_time) < 3.0:
            self.sprite.draw()
            
        # 2. Start Video (GStreamer) behind the image
        logger.info("Phase 2: Starting Video (GStreamer) in background")
        self.pipeline.set_state(Gst.State.PLAYING)
        
        # Wait a moment for the pipeline to preroll and actually start rendering
        time.sleep(0.5)
        
        # 3. Wait for Video to Finish
        logger.info("Phase 3: Waiting for video to finish...")
        
        # Swap the texture to the second image while the video is playing
        # so it's ready when the video stops
        self.sprite.set_textures([self.texture2, self.texture2])
        
        # We MUST draw the sprite at least once with alpha=0 to commit the texture swap
        # to the GPU before the video stops, otherwise the old texture remains in the buffer
        self.sprite.unif[44] = 0.0
        
        # Draw and swap TWICE to ensure both the front and back buffers contain the new image
        # This prevents the old image from flashing when we start fading in
        if self.DISPLAY.loop_running():
            self.sprite.draw()
            
        if self.DISPLAY.loop_running():
            self.sprite.draw()
            
        if self.DISPLAY.loop_running():
            self.sprite.draw()
            
        # Force Wayland to process the buffer swaps
        time.sleep(0.2)
        
        video_start = time.time()
        while not self.video_finished:
            # Keep pi3d loop alive, but draw nothing (or draw with 0 alpha)
            # self.sprite.draw()
            
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
            if time.time() - video_start > 10.0: # 10 seconds max
                logger.warning("Phase 3: Failsafe timeout reached. Forcing video finish.")
                self.video_finished = True
                
        # Stop Video first so it disappears immediately
        self.pipeline.set_state(Gst.State.NULL)
        
        # Force GStreamer to process the state change and destroy the window
        while self.bus.poll(Gst.MessageType.ANY, 10000000): # 10ms
            pass

        # 4. Show Image again briefly
        logger.info("Phase 4: Displaying Image 2 (pi3d) again")
        start_time = time.time()
        while self.DISPLAY.loop_running() and (time.time() - start_time) < 2.0:
            self.sprite.draw()
            
        logger.info("PoC Complete. Cleaning up.")
        self.DISPLAY.destroy()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Picframe Video Handoff PoC")
    parser.add_argument("image", help="Path to test image")
    parser.add_argument("video", help="Path to test video")
    parser.add_argument("image2", nargs="?", help="Path to second test image (optional)")
    args = parser.parse_args()
    
    if not Path(args.image).exists():
        logger.error(f"Image not found: {args.image}")
        sys.exit(1)
        
    if not Path(args.video).exists():
        logger.error(f"Video not found: {args.video}")
        sys.exit(1)
        
    if args.image2 and not Path(args.image2).exists():
        logger.error(f"Image 2 not found: {args.image2}")
        sys.exit(1)
        
    poc = VideoHandoffPoC(args.image, args.video, args.image2)
    poc.run()
