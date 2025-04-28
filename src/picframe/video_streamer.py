"""
video_streamer.py

This module provides classes for video processing and playback.

Classes:
--------
1. VideoFrameExtractor:
    - Extracts the first and last frames of a video.
    - Processes video frames to fit display dimensions.

2. VideoStreamer:
    - Streams video using VLC and SDL2.
    - Provides functionality for video playback, including play, stop, and kill operations.

Dependencies:
-------------
- VLC (vlc): For video playback.
- SDL2 (sdl2): For creating a video playback window.
- NumPy (np): For handling video frame data.
- PIL (Pillow): For image processing.
- subprocess: For running external commands (FFmpeg and FFprobe).
"""
import sys
from typing import Optional, Tuple
from datetime import datetime
import json
import logging
import subprocess
import os
import time
import numpy as np
import vlc  # type: ignore
import sdl2  # type: ignore
from PIL import Image

from .video_metadata import VideoMetadata

VIDEO_EXTENSIONS = ['.mp4', '.mkv', '.flv', '.mov', '.avi', '.webm', '.hevc']


def get_video_info(video_path: str) -> VideoMetadata:
    """Retrieves metadata about the video file using FFprobe."""
    logger = logging.getLogger("get_video_info")
    logger.setLevel(logging.DEBUG)  # Set logging level to DEBUG
    start_time = time.time()
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,duration",
            "-show_entries", "stream_side_data=rotation",
            "-show_entries", "format_tags=title,description,comment,caption,creation_time,location",
            "-show_entries", "format_tags=location-eng,com.apple.quicktime.location.ISO6709",
            "-show_entries", "format_tags=com.apple.quicktime.make,com.apple.quicktime.model",
            "-show_entries", "format_tags=com.android.version",
            # Add more show_entries if needed for extra fields
            "-show_entries", "stream_tags=make,model,lens,iso_speed,exposure_time,f_number,focal_length,rating",
            "-of", "json",
            video_path
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, check=True)
        info = json.loads(result.stdout)

        stream = info["streams"][0]
        width = stream.get("width", 0)
        height = stream.get("height", 0)
        duration = float(stream.get("duration", 0))

        # Get rotation
        rotation = 0
        for item in stream.get("side_data_list", []):
            if "rotation" in item:
                rotation = int(item["rotation"])
                break

        # Get metadata from format tags
        tags = info.get("format", {}).get("tags", {})
        stream_tags = stream.get("tags", {})

        # Extract metadata fields
        title = tags.get("title")
        caption = (
            tags.get("caption") or
            tags.get("description") or
            tags.get("comment") or
            tags.get("com.apple.quicktime.description")
        )

        # Extract creation date
        creation_date = None
        date_str = tags.get("creation_time")
        if date_str:
            try:
                creation_date = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S.%fZ")
            except ValueError:
                try:
                    creation_date = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    logger.warning("Could not parse creation date: %s", date_str)

        # Fall back to file creation time if no metadata date available
        if creation_date is None:
            try:
                file_ctime = os.path.getctime(video_path)
                creation_date = datetime.fromtimestamp(file_ctime)
                logger.debug("Using file creation time: %s", creation_date)
            except OSError as e:
                logger.warning("Could not get file creation time: %s", e)

        # Extract GPS coordinates
        gps_coords = None
        loc_str = (
            tags.get("location") or
            tags.get("location-eng") or
            tags.get("com.apple.quicktime.location.ISO6709")
        )
        if loc_str:
            try:
                # Parse ISO6709 format: ±DD.DDDD±DDD.DDDD+HHH.HHH/
                if '/' in loc_str:
                    # Split at each sign and remove trailing slash
                    parts = loc_str.strip('/').replace('+', ' +').replace('-', ' -').split()
                    if len(parts) >= 2:  # At least latitude and longitude
                        lat = float(parts[0])
                        lon = float(parts[1])
                        gps_coords = (lat, lon)
            except ValueError:
                logger.warning("Could not parse GPS coordinates: %s", loc_str)

        # --- Additional fields extraction ---
        # Try to extract from stream_tags, fallback to None if not present
        f_number = stream_tags.get("f_number")
        make = (
            stream_tags.get("make") or
            tags.get("com.apple.quicktime.make")
        )
        model = (
            stream_tags.get("model") or
            tags.get("com.apple.quicktime.model")
        )
        lens = stream_tags.get("lens")
        iso = stream_tags.get("iso_speed")
        exposure_time = stream_tags.get("exposure_time")
        focal_length = stream_tags.get("focal_length")
        rating = stream_tags.get("rating")
        # tags field (IPTC) is not standard in video, but try to get from format tags
        iptc_tags = tags.get("keywords") or tags.get("tags")

        metadata = VideoMetadata(
            width=width,
            height=height,
            duration=duration,
            rotation=rotation,
            title=title,
            caption=caption,
            creation_date=creation_date,
            gps_coords=gps_coords,
            f_number=f_number,
            make=make,
            model=model,
            exposure_time=exposure_time,
            iso=iso,
            focal_length=focal_length,
            rating=rating,
            lens=lens,
            tags=iptc_tags,
        )

        elapsed = time.time() - start_time
        logger.debug("Video metadata extraction for %s took %.3f seconds", video_path, elapsed)
        logger.debug("Video metadata: %s", {
            'dimensions': f"{metadata.width}x{metadata.height}",
            'duration': f"{metadata.duration:.1f}s",
            'rotation': metadata.rotation,
            'title': metadata.title,
            'caption': metadata.caption,
            'creation_date': metadata.creation_date,
            'gps': metadata.gps_coords,
            'f_number': metadata.f_number,
            'make': metadata.make,
            'model': metadata.model,
            'lens': metadata.lens,
            'iso': metadata.iso,
            'exposure_time': metadata.exposure_time,
            'focal_length': metadata.focal_length,
            'rating': metadata.rating,
            'tags': metadata.tags,
        })
        return metadata
    except (subprocess.CalledProcessError, KeyError, ValueError, IndexError, TypeError) as e:
        elapsed = time.time() - start_time
        logger.warning("Failed to retrieve video metadata in %.3f seconds: %s", elapsed, e)
        return VideoMetadata(0, 0, 0.0, 0)


class VideoFrameExtractor:
    """
    A class to extract the first and last frames of a video and process them.

    Attributes:
    -----------
    video_path : str
        The path to the video file.
    display_width : int
        The width of the display.
    display_height : int
        The height of the display.
    fit_display : bool
        Whether to resize frames to fit the display dimensions.
    logger : logging.Logger
        Logger for debugging and error messages.
    """

    def __init__(self, video_path: str, display_width: int, display_height: int,
                 fit_display: bool = False) -> None:
        """
        Initializes the VideoFrameExtractor.

        Parameters:
        -----------
        video_path : str
            The path to the video file.
        display_width : int
            The width of the display.
        display_height : int
            The height of the display.
        fit_display : bool, optional
            Whether to resize frames to fit the display dimensions. Defaults to False.
        """
        self.video_path = video_path
        self.display_width = display_width
        self.display_height = display_height
        self.fit_display = fit_display
        self.logger = logging.getLogger("VideoFrameExtractor")
        self.logger.setLevel(logging.DEBUG)  # Set logging level to DEBUG

    def _scale_frame(self, frame: Image.Image) -> Image.Image:
        """
        Scale the frame to fit the display without distortion and add black bars if necessary.

        Parameters:
        -----------
        frame : Image.Image
            The video frame as a Pillow Image object.

        Returns:
        --------
        Image.Image
            The scaled frame with black bars added if necessary.
        """
        frame_width, frame_height = frame.size
        aspect_ratio_frame = frame_width / frame_height
        aspect_ratio_display = self.display_width / self.display_height

        if aspect_ratio_frame > aspect_ratio_display:
            # Fit to width
            new_width = self.display_width
            new_height = int(self.display_width / aspect_ratio_frame)
        else:
            # Fit to height
            new_height = self.display_height
            new_width = int(self.display_height * aspect_ratio_frame)

        # Resize the frame
        resized_frame = frame.resize((new_width, new_height), resample=Image.Resampling.BICUBIC)

        # Create a black canvas with display dimensions
        canvas = Image.new("RGB", (self.display_width, self.display_height), "black")

        # Center the resized frame on the canvas
        x_offset = (self.display_width - new_width) // 2
        y_offset = (self.display_height - new_height) // 2
        canvas.paste(resized_frame, (x_offset, y_offset))

        return canvas

    def _process_video_frame(self, frame: Image.Image) -> Image.Image:
        """
        Process a video frame by resizing or scaling it.

        Parameters:
        -----------
        frame : Image.Image
            The video frame as a Pillow Image object.

        Returns:
        --------
        Image.Image
            The processed frame.
        """
        width, height = frame.size
        if self.fit_display:
            if width != self.display_width or height != self.display_height:
                frame = frame.resize((self.display_width, self.display_height),
                                     resample=Image.Resampling.BICUBIC)
        elif width != self.display_width or height != self.display_height:
            frame = self._scale_frame(frame)
        return frame

    def _get_frame_as_numpy(self, dimensions: Tuple[int, int],
                            seek_time: float) -> Optional[np.ndarray]:
        """
        Retrieve a frame from the video at a specific time.

        Parameters:
        -----------
        dimensions : Tuple[int, int]
            The dimensions of the video frame (width, height).
        seek_time : float
            The time in seconds to seek to in the video.

        Returns:
        --------
        Optional[np.ndarray]
            The video frame as a NumPy array, or None if retrieval fails.
        """
        try:
            # Build ffmpeg command
            cmd = [
                "ffmpeg",
                "-ss", str(seek_time) if seek_time else "0",  # seek time if specified
                "-i", self.video_path,
                "-vframes", "1",
                "-f", "image2pipe",
                "-pix_fmt", "rgb24",
                "-vcodec", "rawvideo",
                "-"
            ]

            # Run ffmpeg and capture output
            process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     check=True)

            # Convert raw bytes to numpy array
            width, height = dimensions
            frame = np.frombuffer(process.stdout, dtype=np.uint8).reshape((height, width, 3))

            return frame
        except (subprocess.CalledProcessError, KeyError, ValueError, IndexError, TypeError) as e:
            self.logger.warning("Failed to retrieve video frame: %s", e)
            return None

    def get_first_and_last_frames(self) -> Optional[Tuple[Image.Image, Image.Image]]:
        """Retrieve the first and last frames of the video as Pillow Image objects."""
        start_time = time.time()
        # TODO: to avoid double call we shoud add specific video metadata to db
        metadata = get_video_info(self.video_path) 
        if metadata.width == 0 or metadata.height == 0:
            self.logger.error("Error: Invalid video dimensions.")
            return None
        if metadata.duration == 0:
            self.logger.error("Error: Invalid video duration.")
            return None
        if metadata.rotation not in [0, 90, -90, 180, -180, 270, -270]:
            self.logger.error("Error: Invalid video rotation.")
            return None

        frame_start_time = time.time()
        first_frame = self._get_frame_as_numpy(metadata.dimensions, 0)
        first_frame_time = time.time() - frame_start_time

        frame_start_time = time.time()
        last_frame = self._get_frame_as_numpy(metadata.dimensions, metadata.duration - 0.1)
        last_frame_time = time.time() - frame_start_time

        if first_frame is not None and last_frame is not None:
            total_time = time.time() - start_time
            self.logger.debug("Frame extraction times for %s:", self.video_path)
            self.logger.debug("  First frame: %.3f seconds", first_frame_time)
            self.logger.debug("  Last frame: %.3f seconds", last_frame_time)
            self.logger.debug("  Total processing: %.3f seconds", total_time)

            first_image = Image.fromarray(first_frame)
            last_image = Image.fromarray(last_frame)
            first_image = self._process_video_frame(first_image)
            last_image = self._process_video_frame(last_image)
            return first_image, last_image

        elapsed = time.time() - start_time
        self.logger.error("Failed to retrieve frames in %.3f seconds", elapsed)
        return None

    def get_first_frame_as_image(self) -> Optional[Image.Image]:
        """Retrieve the first frame of the video as unscalled Pillow Image objects."""
        start_time = time.time()
        # TODO: to avoid double call we shoud add specific video metadata to db
        metadata = get_video_info(self.video_path) 
        if metadata.width == 0 or metadata.height == 0:
            self.logger.error("Error: Invalid video dimensions.")
            return None
        if metadata.duration == 0:
            self.logger.error("Error: Invalid video duration.")
            return None
        if metadata.rotation not in [0, 90, -90, 180, -180, 270, -270]:
            self.logger.error("Error: Invalid video rotation.")
            return None

        frame_start_time = time.time()
        first_frame = self._get_frame_as_numpy(metadata.dimensions, 0)
        first_frame_time = time.time() - frame_start_time

        if first_frame is not None:
            self.logger.debug("Frame extraction times for %s:", self.video_path)
            self.logger.debug("  First frame: %.3f seconds", first_frame_time)
            first_image = Image.fromarray(first_frame)
            return first_image

        elapsed = time.time() - start_time
        self.logger.error("Failed to retrieve first frame in %.3f seconds", elapsed)
        return None



class VideoStreamer:
    """
    A class for streaming video using VLC and SDL2.

    Attributes:
    -----------
    player : Optional[vlc.MediaPlayer]
        The VLC media player instance.
    __window : Optional[sdl2.SDL_Window]
        The SDL2 window for video playback.
    __instance : Optional[vlc.Instance]
        The VLC instance.
    __logger : logging.Logger
        Logger for debugging and error messages.
    """

    def __init__(self, x: int, y: int, w: int, h: int, video_path: Optional[str] = None,
                 fit_display: bool = False) -> None:
        """
        Initializes the video streamer.

        Parameters:
        -----------
        x : int
            The x-coordinate of the SDL window.
        y : int
            The y-coordinate of the SDL window.
        w : int
            The width of the SDL window.
        h : int
            The height of the SDL window.
        video_path : Optional[str], optional
            The path to the video file. If provided, playback starts automatically.
            Defaults to None.
        fit_display : bool, optional
            If True, set the aspect ratio of the video to match the display dimensions.
            Defaults to False.
        """
        self.player: Optional[vlc.MediaPlayer] = None
        self.__window: Optional[sdl2.SDL_Window] = None
        self.__instance: Optional[vlc.Instance] = None

        self.__logger = logging.getLogger("video_streamer")
        self.__logger.debug("Initializing VideoStreamer")

        if sys.platform != "darwin":
            # Create SDL2 window
            self.__window = sdl2.SDL_CreateWindow(
                b"", x, y, w, h,
                sdl2.SDL_WINDOW_HIDDEN | sdl2.SDL_WINDOW_BORDERLESS)
            if not self.__window:
                self.__logger.error("Error creating window: %s",
                                    sdl2.SDL_GetError().decode('utf-8'))
                return
            sdl2.SDL_ShowCursor(sdl2.SDL_DISABLE)

            # Retrieve window manager info
            wminfo = sdl2.SDL_SysWMinfo()
            sdl2.SDL_GetVersion(wminfo.version)
            if sdl2.SDL_GetWindowWMInfo(self.__window, wminfo) == 0:
                self.__logger.error("Can't get SDL WM info.")
                sdl2.SDL_DestroyWindow(self.__window)
                self.__window = None
                return

        # Create VLC instance and player
        self.__instance = vlc.Instance('--no-audio')
        self.player = self.__instance.media_player_new()

        if sys.platform != "darwin":
            self.player.set_xwindow(wminfo.info.x11.window)

        if fit_display:
            aspect_ratio = f"{w}:{h}"
            self.player.video_set_aspect_ratio(aspect_ratio)

        # Start video playback if a path is provided
        if video_path is not None:
            self.play(video_path)

    def play(self, video_path: Optional[str]) -> None:
        """
        Plays a video file.

        Parameters:
        -----------
        video_path : Optional[str]
            The path to the video file. If None or invalid, playback will not start.
        """
        if video_path is None:
            self.__logger.error("Error: No video path provided.")
            return

        if not os.path.exists(video_path):
            self.__logger.error("Error: File '%s' not found.", video_path)
            return

        if self.__instance is None or self.player is None:
            self.__logger.error("Error: VLC instance or player is not initialized.")
            return

        media = self.__instance.media_new_path(video_path)
        self.player.set_media(media)
        self.__logger.debug("Playing video: %s", video_path)
        sdl2.SDL_ShowWindow(self.__window)
        self.player.play()

    def is_playing(self) -> bool:
        """
        Checks if a video is currently playing.

        Returns:
        --------
        bool
            True if the video is playing, False otherwise.
        """
        if self.player is None:
            return False
        state = self.player.get_state()
        return state in [vlc.State.Opening, vlc.State.Playing,
                         vlc.State.Paused, vlc.State.Buffering]

    def stop(self) -> None:
        """
        Stops video playback and hides the SDL window.
        """
        if self.player is None:
            return

        self.__logger.debug("Stopping video")
        self.player.stop()
        if self.__window:
            sdl2.SDL_HideWindow(self.__window)
        self.__logger.debug("Releasing media")
        if self.player.get_media() is not None:
            self.player.get_media().release()

    def kill(self) -> None:
        """
        Stops video playback and destroys the SDL window and VLC instance.
        """
        self.__logger.debug("Killing VideoStreamer")
        self.stop()
        if self.__window:
            sdl2.SDL_DestroyWindow(self.__window)
            self.__window = None
        if self.__instance:
            self.__instance.release()
            self.__instance = None
        self.player = None
