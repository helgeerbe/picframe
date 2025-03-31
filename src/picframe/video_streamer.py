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
- OpenCV (cv2): For video frame extraction and processing.
- VLC (vlc): For video playback.
- SDL2 (sdl2): For creating a video playback window.
- NumPy (np): For handling video frame data.
"""
import sys
import logging
import os
from typing import Optional, Tuple
import numpy as np
import vlc  # type: ignore
import sdl2  # type: ignore
import cv2

VIDEO_EXTENSIONS = ['.mp4', '.mkv', '.flv', '.mov', '.avi', '.webm', '.hevc']


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
    cap : cv2.VideoCapture
        The OpenCV video capture instance.
    logger : logging.Logger
        Logger for debugging and error messages.
    """

    def __init__(self, video_path: str, display_width: int, display_height:
                 int, fit_display: bool = False):
        self.video_path = video_path
        self.display_width = display_width
        self.display_height = display_height
        self.fit_display = fit_display
        self.cap = cv2.VideoCapture(video_path)
        self.logger = logging.getLogger("VideoFrameExtractor")

        if not self.cap.isOpened():
            self.logger.error("Error: Could not open video '%s'", video_path)
            raise ValueError(f"Could not open video: {video_path}")

    def _scale_frame(self, frame: np.ndarray) -> np.ndarray:
        """
        Scale the frame to fit the display without distortion and add black bars if necessary.
        """
        try:
            frame_height, frame_width = frame.shape[:2]
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

            resized_frame = cv2.resize(frame, (new_width, new_height),
                                       interpolation=cv2.INTER_LINEAR)

            # Create a black canvas with display dimensions
            canvas = np.zeros((self.display_height, self.display_width, 3), dtype=np.uint8)

            # Center the resized frame on the canvas
            y_offset = (self.display_height - new_height) // 2
            x_offset = (self.display_width - new_width) // 2
            canvas[y_offset:y_offset + new_height, x_offset:x_offset + new_width] = resized_frame

            return canvas
        except cv2.error as e:  # pylint: disable=E0712
            self.logger.warning("OpenCV error while scaling frame: %s", e)
            return frame

    def _process_video_frame(self, frame: np.ndarray) -> Optional[np.ndarray]:
        """
        Process a video frame by converting it to RGB and resizing or scaling it.
        """
        try:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            if self.fit_display:
                if frame.shape[1] != self.display_width or frame.shape[0] != self.display_height:
                    try:
                        frame = cv2.resize(frame, (self.display_width,
                                                   self.display_height),
                                           interpolation=cv2.INTER_LINEAR)
                    except cv2.error as e:  # pylint: disable=E0712
                        self.logger.warning("OpenCV error while resizing frame: %s", e)
            elif frame.shape[1] != self.display_width or frame.shape[0] != self.display_height:
                frame = self._scale_frame(frame)
            return frame
        except (cv2.error, ValueError, TypeError) as e:  # pylint: disable=E0712
            self.logger.error("Error processing frame: %s", e)
            return None

    def get_first_and_last_frames(self) -> Optional[Tuple[np.ndarray, np.ndarray]]:
        """
        Retrieve the first and last frames of the video as NumPy arrays.
        """
        try:
            # Retrieve the first frame
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)  # Reset to the first frame
            ret_first, frame_first = self.cap.read()
            if not ret_first or frame_first is None:
                self.logger.error("Error retrieving the first frame.")
                return None

            processed_frame = self._process_video_frame(frame_first)
            if processed_frame is not None:
                frame_first = processed_frame
            else:
                self.logger.error("Error processing the first frame.")
                return None

            # Retrieve the last frame
            total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
            frame_last = None
            for i in range(1, 11):  # Try the last 10 frames
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, total_frames - i)
                ret_last, temp_frame = self.cap.read()
                if ret_last and temp_frame is not None:
                    frame_last = self._process_video_frame(temp_frame)
                    if frame_last is not None:
                        break

            if frame_last is None:
                self.logger.error("Error retrieving the last frame.")
                return None

            return frame_first, frame_last
        finally:
            self.cap.release()


class VideoStreamer:
    """
    A class for streaming video using VLC and SDL2.

    Attributes:
    -----------
    player : vlc.MediaPlayer
        The VLC media player instance.
    __window : Optional[sdl2.SDL_Window]
        The SDL2 window for video playback.
    __instance : Optional[vlc.Instance]
        The VLC instance.
    __logger : logging.Logger
        Logger for debugging and error messages.
    """
    def __init__(self, x: int, y: int, w: int, h: int,
                 video_path: Optional[str] = None, fit_display: bool = False) -> None:
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
        video_path : Optional[str]
            The path to the video file (optional). If provided, playback starts automatically.
        fit_display : bool
            If True, set the aspect ratio of the video to match the display dimensions.
        """
        self.player: Optional[vlc.MediaPlayer] = None
        self.__window: Optional[sdl2.SDL_Window] = None
        self.__instance: Optional[vlc.Instance] = None

        self.__logger = logging.getLogger("video_streamer")
        self.__logger.debug("Initializing VideoStreamer")

        if sys.platform != "darwin":
            # Create SDL2 window
            self.__window = sdl2.SDL_CreateWindow(b"", x, y, w, h, sdl2.SDL_WINDOW_HIDDEN)
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
