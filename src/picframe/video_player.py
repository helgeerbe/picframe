"""
This module provides a `VideoPlayer` class that manages video playback
in a dedicated SDL2 window using VLC.
"""
import sys
import time
import argparse
import ctypes
import logging
import threading
import queue
from typing import Optional
import os
import vlc  # type: ignore
import sdl2  # type: ignore


class VideoPlayer:
    """
    VideoPlayer manages video playback in a dedicated SDL2 window using VLC.
    It communicates via stdin/stdout for commands and state, and is designed
    to be controlled by an external process (e.g., VideoStreamer).

    Supported commands (via stdin):
        - load <path>: Load a video file and start playback
        - pause: Pause playback
        - resume: Resume playback
        - stop: Stop playback and hide window

    State changes are sent to stdout as:
        STATE:PLAYING, STATE:ENDED, etc.
    """

    def __init__(self, x: int, y: int, w: int, h: int, fit_display: bool = False) -> None:
        self.logger = logging.getLogger("video_player")
        self.logger.debug("Initializing VideoPlayer")
        self.window: Optional[ctypes.c_void_p] = None
        self.player: Optional[vlc.MediaPlayer] = None
        self.instance: Optional[vlc.Instance] = None
        self.event = sdl2.SDL_Event()
        self.last_state: Optional[str] = None
        self.current_media: Optional[vlc.Media] = None
        self.x = x
        self.y = y
        self.w = w
        self.h = h
        self.fit_display = fit_display
        self.cmd_queue: queue.Queue[str] = queue.Queue()
        self.stdin_thread = threading.Thread(target=self._stdin_reader, daemon=True)
        self._vlc_event_manager: Optional[vlc.EventManager] = None
        self._vlc_event_callbacks_registered: bool = False
        self._show_window_request: bool = False
        self._hide_window_request: bool = False
        self._last_time: int = 0
        self._last_progress_time: float = 0.0
        self._startup: bool = True

    def setup(self) -> bool:
        """Initialize SDL2, create window, and set up VLC player."""
        sdl2.SDL_Init(sdl2.SDL_INIT_VIDEO)
        self.window = sdl2.SDL_CreateWindow(
            b"Video Player",
            self.x, self.y,
            self.w, self.h,
            sdl2.SDL_WINDOW_HIDDEN | sdl2.SDL_WINDOW_BORDERLESS
        )
        if not self.window:
            self.logger.error("Error creating window: %s", sdl2.SDL_GetError().decode('utf-8'))
            return False

        sdl2.SDL_ShowCursor(sdl2.SDL_DISABLE)

        # Get window info for embedding
        wm_info = sdl2.SDL_SysWMinfo()
        sdl2.SDL_VERSION(wm_info.version)
        if not sdl2.SDL_GetWindowWMInfo(self.window, ctypes.byref(wm_info)):
            self.logger.error("Error: Could not get window information! SDL Error: %s",
                              sdl2.SDL_GetError().decode('utf-8'))
            sdl2.SDL_DestroyWindow(self.window)
            return False
        if not hasattr(wm_info, 'info'):
            self.logger.error("Error: wm_info structure does not have 'info' attribute!")
            sdl2.SDL_DestroyWindow(self.window)
            return False

        # Initialize VLC
        vlc_args = ['--no-audio', '--quiet', '--verbose=0']
        try:
            self.instance = vlc.Instance(vlc_args)
            self.player = self.instance.media_player_new()
        except Exception as e:  # pylint: disable=broad-except
            self.logger.error("Failed to initialize VLC instance: %s", e)
            self.instance = None
            self.player = None
            sdl2.SDL_DestroyWindow(self.window)
            return False

        # Set the VLC player to use the SDL2 window
        if sys.platform == "darwin":
            try:
                if sdl2.SDL_GetWindowWMInfo(self.window, ctypes.byref(wm_info)):
                    from rubicon.objc import ObjCInstance  # type: ignore  # pylint: disable=import-outside-toplevel
                    nswindow_ptr = wm_info.info.cocoa.window
                    nswindow = ObjCInstance(ctypes.c_void_p(nswindow_ptr))
                    nsview = nswindow.contentView
                    self.player.set_nsobject(nsview.ptr.value)
                    self.logger.debug("Set NSView: %s", nsview)
                else:
                    self.logger.error("Error: Could not get window information!")
                    self.player.set_nsobject(None)
            except Exception as e:  # pylint: disable=broad-except
                self.logger.error("Could not set NSView: %s", e)
                self.player.set_nsobject(None)
        elif sys.platform.startswith("linux"):
            if wm_info.subsystem == sdl2.SDL_SYSWM_X11:
                xid = wm_info.info.x11.window
                self.logger.debug("X11 window ID: %s", xid)
                self.player.set_xwindow(xid)
            else:
                self.logger.error("VLC embedding not supported on: %s", wm_info.subsystem)
        elif sys.platform == "win32":
            self.player.set_hwnd(sdl2.SDL_GetWindowID(self.window))

        if self.fit_display:
            aspect_ratio = f"{self.w}:{self.h}"
            self.player.video_set_aspect_ratio(aspect_ratio)

        # Register VLC event callbacks
        self._vlc_event_manager = self.player.event_manager()
        self._register_vlc_events()

        return True

    def _register_vlc_events(self):
        """Attach VLC event callbacks for playback state changes."""
        if self._vlc_event_manager and not self._vlc_event_callbacks_registered:
            self._vlc_event_manager.event_attach(vlc.EventType.MediaPlayerPlaying, self._on_vlc_playing)
            self._vlc_event_manager.event_attach(vlc.EventType.MediaPlayerStopped, self._on_vlc_stopped)
            self._vlc_event_manager.event_attach(vlc.EventType.MediaPlayerEndReached, self._on_vlc_ended)
            self._vlc_event_manager.event_attach(vlc.EventType.MediaPlayerEncounteredError, self._on_vlc_error)
            self._vlc_event_callbacks_registered = True

    def _on_vlc_playing(self, event):
        self.logger.debug("VLC event: MediaPlayerPlaying")
        self._show_window_request = True
        self._last_time = 0
        self._last_progress_time = time.time()
        self._startup = True

    def _on_vlc_stopped(self, event: vlc.Event) -> None:
        """
        VLC event handler for MediaPlayerStopped.

        Args:
            event (vlc.Event): VLC event object.
        """
        self.logger.debug("VLC event: MediaPlayerStopped")
        self._hide_window_request = True
        self._send_state("ENDED")

    def _on_vlc_ended(self, event: vlc.Event) -> None:
        """
        VLC event handler for MediaPlayerEndReached.

        Args:
            event (vlc.Event): VLC event object.
        """
        self.logger.debug("VLC event: MediaPlayerEndReached")
        self._hide_window_request = True
        self._send_state("ENDED")

    def _on_vlc_error(self, event: vlc.Event) -> None:
        """
        VLC event handler for MediaPlayerEncounteredError.

        Args:
            event (vlc.Event): VLC event object.
        """
        self.logger.error("VLC event: MediaPlayerEncounteredError")
        self._hide_window_request = True
        if self.player:
            self.player.stop()
        self._send_state("ENDED")

    def _poll_events(self) -> bool:
        """Poll SDL2 events, return False if quit event is received."""
        while sdl2.SDL_PollEvent(ctypes.byref(self.event)):
            if self.event.type == sdl2.SDL_QUIT:
                return False
        return True

    def _send_state(self, state: str) -> None:
        """Send state to stdout only if it changed."""
        if state != self.last_state:
            self.logger.info("State changed to: %s", state)
            print(f"STATE:{state}", flush=True)
            self.last_state = state

    def _stdin_reader(self):
        """
        Continuously reads lines from standard input and places them into the command queue.

        This method runs an infinite loop, reading input from sys.stdin line by line.
        Each line read is put into the cmd_queue for further processing.
        The loop exits when an empty line is encountered (EOF).
        """
        while True:
            line = sys.stdin.readline()
            if not line:
                break
            self.cmd_queue.put(line)

    def check_video_progress(self) -> bool:
        """
        Checks the progress of the currently playing video and determines if the player is stuck.

        This method monitors the playback time of the video player. If the playback time does not advance
        for more than 3 seconds, or if the player reports that no media is loaded, it is considered stuck,
        and playback is stopped.

        Returns:
            bool: True if the video is progressing normally, False if the player is stuck or not initialized.
        """
        if not self.player:
            self.logger.error("Player not initialized, cannot check video progress.")
            return False

        current_time = self.player.get_time()
        now = time.time()

        if not self._startup and current_time == self._last_time:
            # No progress, check if we've been stuck for more than 3 seconds
            if now - self._last_progress_time > 3.0:
                self.logger.error("vlc is stuck while playing for more than 3 seconds. Stopping it!")
                self.logger.debug("vlc current time: %d, last time: %d", current_time, self._last_time)
                self.player.stop()
                return False
        elif current_time == -1:  # VLC returns -1 if no media is loaded
            self.logger.warning("No media loaded or media is invalid.")
            self.player.stop()
            return False
        else:
            # Progress detected, reset timer
            self._last_progress_time = now
            if self._startup and current_time > 0:
                self.logger.debug("Video started playing.")
                self.logger.debug("vlc current time: %d", current_time)
                self._send_state("PLAYING")
                self._startup = False

        self._last_time = current_time
        return True

    def run(self) -> None:
        """Main event loop: handle SDL2 events and commands."""
        if not self.player:
            self.logger.error("Player not initialized, cannot run.")
            return
        self.stdin_thread.start()
        try:
            running = True
            while running:
                running = self._poll_events()

                # Handle window show/hide requests from VLC callbacks
                if self._show_window_request:
                    if not sdl2.SDL_GetWindowFlags(self.window) & sdl2.SDL_WINDOW_SHOWN:
                        sdl2.SDL_ShowWindow(self.window)
                        self._wait_for_window_shown(timeout=4.0)
                        sdl2.SDL_ShowCursor(sdl2.SDL_DISABLE)
                        sdl2.SDL_WarpMouseInWindow(self.window, self.w - 1, self.h - 1)
                    self._show_window_request = False
                
                if sdl2.SDL_ShowCursor(sdl2.SDL_QUERY) == 1:
                    self.logger.debug("Mouse pointer is visible, hiding it.")
                    sdl2.SDL_ShowCursor(sdl2.SDL_DISABLE)

                if self._hide_window_request:
                    if sdl2.SDL_GetWindowFlags(self.window) & sdl2.SDL_WINDOW_SHOWN:
                        sdl2.SDL_HideWindow(self.window)
                    self._hide_window_request = False

                state = self.player.get_state() if self.player else None
                if state == vlc.State.Playing:
                    self.check_video_progress()

                # Only handle commands
                try:
                    line = self.cmd_queue.get(timeout=0.1) 
                except queue.Empty:
                    line = None
                if line:
                    cmd = line.strip().split()
                    if not cmd:
                        continue
                    self._handle_command(cmd)
        finally:
            if self.player:
                self.player.stop()
            sdl2.SDL_DestroyWindow(self.window)
            sdl2.SDL_Quit()

    def _handle_command(self, cmd: list[str]) -> None:
        """Handle a command received from stdin."""
        if not self.instance or not self.player:
            self.logger.error("Player not initialized, cannot handle_command.")
            return
        if cmd[0] == "load" and len(cmd) > 1:
            media_path = " ".join(cmd[1:])
            if os.path.exists(media_path):
                self.player.stop()
                media = self.instance.media_new_path(media_path)
                self.player.set_media(media)
                self.player.play()
        elif cmd[0] == "pause":
            if self.player.get_state() == vlc.State.Playing:
                self.player.pause()
        elif cmd[0] == "resume":
            if self.player.get_state() == vlc.State.Paused:
                self.player.pause()
        elif cmd[0] == "stop":
            if sdl2.SDL_GetWindowFlags(self.window) & sdl2.SDL_WINDOW_SHOWN:
                sdl2.SDL_HideWindow(self.window)
            self.player.stop()

    def _wait_for_window_shown(self, timeout: float = 4.0) -> bool:
        """Wait for the SDL_WINDOWEVENT_SHOWN event for this window."""
        start_time = time.time()
        window_id = sdl2.SDL_GetWindowID(self.window)
        shown = False
        while not shown and (time.time() - start_time) < timeout:
            while sdl2.SDL_PollEvent(ctypes.byref(self.event)) != 0:
                if (
                    self.event.type == sdl2.SDL_WINDOWEVENT and
                    self.event.window.event == sdl2.SDL_WINDOWEVENT_SHOWN and
                    self.event.window.windowID == window_id
                ):
                    shown = True
                    break
            if shown:
                break
            time.sleep(0.01)
        if not shown:  # If timeout occurred
            self.logger.warning(
                "Player window not shown within %d seconds.", timeout
                )
        return shown


def parse_args() -> argparse.Namespace:
    """
    Parse command-line arguments for the video player.

    Returns:
        argparse.Namespace: Parsed arguments including window position,
        size, and display fitting option.
    """
    parser = argparse.ArgumentParser(description="SDL2/VLC Video Player")
    parser.add_argument("--x", type=int, default=0)
    parser.add_argument("--y", type=int, default=0)
    parser.add_argument("--w", type=int, default=640)
    parser.add_argument("--h", type=int, default=480)
    parser.add_argument("--fit_display", action="store_true")
    parser.add_argument("--log_level", type=str, default="info", choices=["debug", "info", "warning", "error", "critical"],
                        help="Set the logging level (default: info)")
    return parser.parse_args()


def main() -> None:
    """
    Entry point for the video player application.
    Initializes logging, parses arguments, sets up the video player, and starts the event loop.
    """
    args = parse_args()
    log_level = getattr(logging, args.log_level.upper(), logging.INFO)
    logging.basicConfig(level=log_level)
    player = VideoPlayer(args.x, args.y, args.w, args.h, args.fit_display)
    if player.setup():
        player.run()


if __name__ == "__main__":
    main()
