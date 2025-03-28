import vlc
import sdl2
import sys
import logging
import os
import cv2
import numpy as np
from typing import Optional

VIDEO_EXTENSIONS = ['.mp4', '.mkv', '.flv', '.mov', '.avi', '.webm', '.hevc']

def get_frame(video_path: str, frame_position: bool = True) -> Optional[np.ndarray]:
    """
    Retrieve a specific frame (first or last) of a video as a NumPy array with 3 channels (RGB).

    Parameters:
    -----------
    video_path : str
        The path to the video file.
    frame_position : bool
        If True, retrieves the first frame. If False, retrieves the last frame.

    Returns:
    --------
    Optional[np.ndarray]
        The requested frame as a NumPy array, or None if an error occurs.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logging.getLogger("video_streamer").error(f"Error: Could not open video '{video_path}'")
        return None

    if not frame_position:  # If False, set to the last frame
        cap.set(cv2.CAP_PROP_POS_FRAMES, cap.get(cv2.CAP_PROP_FRAME_COUNT) - 1)

    ret, frame = cap.read()
    cap.release()

    if ret:
        # Convert from BGR to RGB
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        return frame

    return None


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
    def __init__(self, x: int, y: int, w: int, h: int, video_path: Optional[str] = None) -> None:
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
                self.__logger.error(f"Error creating window: {sdl2.SDL_GetError().decode('utf-8')}")
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
            self.__logger.error(f"Error: File '{video_path}' not found.")
            return

        if self.__instance is None or self.player is None:
            self.__logger.error("Error: VLC instance or player is not initialized.")
            return
        
        media = self.__instance.media_new_path(video_path)
        self.player.set_media(media)
        self.__logger.debug(f"Playing video: {video_path}")
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
        return state in [vlc.State.Opening, vlc.State.Playing, vlc.State.Paused, vlc.State.Buffering]

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