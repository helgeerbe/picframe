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
import threading
from typing import Optional, Tuple, cast
from datetime import datetime
import json
import logging
import subprocess
import os
import time
import numpy as np
from PIL import Image

from .video_metadata import VideoMetadata

VIDEO_EXTENSIONS = ['.mp4', '.mkv', '.flv', '.mov', '.avi', '.webm', '.hevc']

_image_file_lock = threading.Lock()


def get_video_info(video_path: str) -> VideoMetadata:
    """Retrieves metadata about the video file using FFprobe."""
    logger = logging.getLogger("get_video_info")
    logger.setLevel(logging.DEBUG)  # Set logging level to DEBUG
    start_time = time.time()
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,duration,sample_aspect_ratio",
            "-show_entries", "stream_side_data=rotation",
            "-show_entries", "format=duration",
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
        sample_aspect_ratio = stream.get("sample_aspect_ratio", "1:1")

        # Get rotation
        rotation = 0
        for item in stream.get("side_data_list", []):
            if "rotation" in item:
                rotation = int(item["rotation"])
                break

        # Get metadata from format
        format_sec = info.get("format", {})

        # Get duration from stream or format
        # Default duration to 0.0 if not found
        duration = 0.0
        duration = (
            float(stream.get("duration", 0)) or
            float(format_sec.get("duration", 0)) or
            duration
        )

        # Get metadata from format tags
        tags = format_sec.get("tags", {})
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
            sample_aspect_ratio=sample_aspect_ratio,
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
        return VideoMetadata(0, 0, "1:1", 0.0, 0)


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

    def _apply_sample_aspect_ratio(self, image: Image.Image, sar: str) -> Image.Image:
        """
        If sample_aspect_ratio is not 1:1, scale the image accordingly.
        """
        if sar and sar != "1:1":
            try:
                num_str, den_str = sar.split(":")
                num = float(num_str)
                den = float(den_str)
                if num > 0 and den > 0 and num != den:
                    width, height = image.size
                    new_width = int(round(width * num / den))
                    image = image.resize((new_width, height), resample=Image.Resampling.BICUBIC)
            except (ValueError, AttributeError, TypeError) as e:
                self.logger.warning("Could not apply sample_aspect_ratio %s: %s", sar, e)
        return image

    def get_first_and_last_frames(self) -> Optional[Tuple[Image.Image, Image.Image]]:
        """Retrieve the first and last frames of the video as Pillow Image objects.
        Save/load them as .1.frame and .2.frame JPEGs next to the video file.
        """
        base, _ = os.path.splitext(self.video_path)
        first_path = base + ".1.frame"
        last_path = base + ".2.frame"

        # Attempt to load the frames from the disk
        if os.path.exists(first_path) and os.path.exists(last_path):
            try:
                with _image_file_lock:
                    first_image = cast(Image.Image, Image.open(first_path))
                    last_image = cast(Image.Image, Image.open(last_path))
                first_image = self._process_video_frame(first_image)
                last_image = self._process_video_frame(last_image)
                return first_image, last_image
            except (OSError, IOError, ValueError) as e:
                self.logger.warning("Could not load cached frames: %s", e)
                # Fallback: recreate them

        # If not available, extract and save them
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

        first_frame = self._get_frame_as_numpy(metadata.dimensions, 0)
        last_frame = self._get_frame_as_numpy(metadata.dimensions, metadata.duration - 0.1)

        sar = getattr(metadata, "sample_aspect_ratio", "1:1")

        if first_frame is not None and last_frame is not None:

            first_image = Image.fromarray(first_frame)
            last_image = Image.fromarray(last_frame)
            # Apply sample_aspect_ratio scaling if needed
            first_image = self._apply_sample_aspect_ratio(first_image, sar)
            last_image = self._apply_sample_aspect_ratio(last_image, sar)
            # save as JPEG
            try:
                with _image_file_lock:
                    first_image.save(first_path, format="JPEG")
                    last_image.save(last_path, format="JPEG")
            except (OSError, IOError, ValueError) as e:
                self.logger.warning("Could not save frames: %s", e)

            first_image = self._process_video_frame(first_image)
            last_image = self._process_video_frame(last_image)
            return first_image, last_image

        self.logger.error("Failed to retrieve frames seconds")
        return None

    @staticmethod
    def get_first_frame_as_image(video_path: str) -> Optional[Image.Image]:
        """
        Retrieve the first frame of a video as an unscaled Pillow Image object.

        This method attempts to load the first frame of the specified video from a
        cached file on disk. If the cached frame exists and can be loaded, it is
        returned as a Pillow Image object. Otherwise, the method returns None.

        Args:
            video_path (str): The file path to the video.

        Returns:
            Optional[Image.Image]: The first frame of the video as a Pillow Image
            object if successful, or None if the frame could not be loaded.
        """
        base, _ = os.path.splitext(video_path)
        path = base + ".1.frame"

        # Attempt to load the frames from the disk
        if os.path.exists(path):
            try:
                with _image_file_lock:
                    image = cast(Image.Image, Image.open(path))
                return image
            except (OSError, IOError, ValueError) as e:
                logging.getLogger("VideoFrameExtractor").warning("Could not load cached frame: %s", e)
        return None


class VideoStreamer:
    """
    A class for streaming video using an external player process.
    Communicates with video_player.py via stdin/stdout pipes.
    """

    def __init__(self, x: int, y: int, w: int, h: int, video_path: Optional[str] = None,
                 fit_display: bool = False) -> None:
        self.__logger = logging.getLogger("video_streamer")
        self.__logger.debug("Initializing VideoStreamer")

        self._proc = None
        self._proc_stdin = None
        self._proc_stdout = None
        self._is_playing = False
        self._proc_stderr = None
        self._stderr_thread = None
        self._state_thread = None

        # Start the external player process
        cmd = [
            sys.executable,
            os.path.join(os.path.dirname(__file__), "video_player.py"),
            "--x", str(x), "--y", str(y), "--w", str(w), "--h", str(h)
        ]
        if fit_display:
            cmd.append("--fit_display")
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
            universal_newlines=True
        )
        self._proc_stdin = self._proc.stdin
        self._proc_stdout = self._proc.stdout
        self._proc_stderr = self._proc.stderr

        # Start a thread to listen for state updates from the player
        self._state_thread = threading.Thread(target=self._listen_state, daemon=True)
        self._state_thread.start()

        # Start a thread to listen for stderr output from the player
        self._stderr_thread = threading.Thread(target=self._listen_stderr, daemon=True)
        self._stderr_thread.start()

        if video_path is not None:
            self.play(video_path)

    def player_alive(self) -> bool:
        """
        Check if the external player process is still running.

        Returns:
        --------
        bool
            True if the player process is running, False otherwise.
        """
        if self._proc is None or self._proc.poll() is not None:
            self.__logger.debug("Player process is not alive.")
            self._proc = None
            self._proc_stdin = None
            self._proc_stdout = None
            self._is_playing = False
            return False
        return True

    def _send_command(self, command: str) -> None:
        if self._proc_stdin:
            try:
                self._proc_stdin.write(command + "\n")
                self._proc_stdin.flush()
            except (BrokenPipeError, OSError) as e:
                self.__logger.error("Player process is not alive: %s", e)
                self._proc_stdin = None

    def _listen_state(self):
        if not self._proc_stdout:
            return
        for line in self._proc_stdout:
            line = line.strip()
            if line == "STATE:PLAYING":
                self._is_playing = True
            elif line == "STATE:ENDED":
                self._is_playing = False

    def _listen_stderr(self):
        if not self._proc_stderr:
            return
        for line in self._proc_stderr:
            self.__logger.debug("[player] %s", line.strip())

    def play(self, video_path: Optional[str]) -> None:
        """
        Starts video playback by loading the specified video file.

        Parameters:
        -----------
        video_path : Optional[str]
            The file path to the video to be played. If None or the file does not exist,
            an error is logged and playback does not start.
        """
        if video_path is None:
            self.__logger.error("Error: No video path provided.")
            return
        if not os.path.exists(video_path):
            self.__logger.error("Error: File '%s' not found.", video_path)
            return
        self._send_command(f"load {video_path}")

        timeout = 10  # seconds
        start_time = time.time()
        try:
            while not self.is_playing():
                if time.time() - start_time > timeout:
                    # Raise exception if player fails to start in time
                    raise RuntimeError(f"Video player did not start within {timeout} seconds")
                time.sleep(0.1)
        except RuntimeError as e:
            self.__logger.error("Exception during video player start: %s", e)
            self.kill()
            return
        elapsed = time.time() - start_time
        self.__logger.info("Video player started in %.3f seconds.", elapsed)

    def is_playing(self) -> bool:
        """
        Checks if a video is currently playing.

        Returns:
        --------
        bool
            True if the video is playing, False otherwise.
        """
        if self._is_playing and self.player_alive():
            return True
        return False

    def pause(self, do_pause: bool) -> None:
        """
        Pauses or resumes video playback by sending the appropriate
        command to the external player process.
        """
        if do_pause:
            self._send_command("pause")
        else:
            self._send_command("resume")

    def stop(self) -> None:
        """
        Stops video playback by sending a stop command to the external player process.
        """
        self._send_command("stop")
        timeout = 5  # seconds
        start_time = time.time()
        while self.is_playing():
            if time.time() - start_time > timeout:
                self.__logger.error("Timeout: Video did not stop within %d seconds. Kill player.", timeout)
                self.__logger.debug("Killing player process due to timeout.")
                self.kill()
                break
            time.sleep(0.1)

    def kill(self) -> None:
        """
        Stops video playback and terminates the external player process.
        """
        self.__logger.debug("Killing player process")
        if self._proc:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None
        self._proc_stdin = None
        self._proc_stdout = None
        self._is_playing = False
