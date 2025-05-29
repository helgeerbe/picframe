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
        vlc_args = ['--no-audio']
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

        return True

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

    def run(self) -> None:
        """Main event loop: handle commands and playback state."""
        if not self.player:
            self.logger.error("Player not initialized, cannot run.")
            return
        self.stdin_thread.start()
        try:
            while True:
                self._poll_events()
                # Check player state ignore opening and buffering
                # to avoid flickering
                state = self.player.get_state()
                if state in [vlc.State.Ended, vlc.State.Stopped,
                             vlc.State.Error]:
                    if sdl2.SDL_GetWindowFlags(self.window) & sdl2.SDL_WINDOW_SHOWN:
                        sdl2.SDL_HideWindow(self.window)
                    self.player.stop()
                    self.player.set_media(None)
                    self._send_state("ENDED")
                elif state in [vlc.State.Playing, vlc.State.Paused]:
                    self._send_state("PLAYING")
                    # Show window only if not already visible
                    if not sdl2.SDL_GetWindowFlags(self.window) & sdl2.SDL_WINDOW_SHOWN:
                        sdl2.SDL_ShowWindow(self.window)
                        # Wait until the window is actually shown
                        shown = False
                        start_time = time.time()
                        timeout = 4  # seconds
                        window_id = sdl2.SDL_GetWindowID(self.window)  # Get window ID once
                        while not shown and (time.time() - start_time) < timeout:
                            while sdl2.SDL_PollEvent(ctypes.byref(self.event)) != 0:
                                if (self.event.type == sdl2.SDL_WINDOWEVENT and
                                        self.event.window.event == sdl2.SDL_WINDOWEVENT_SHOWN and
                                        self.event.window.windowID == window_id):
                                    shown = True
                                    break
                            if shown:  # If event found, break outer loop
                                break
                            time.sleep(0.01)

                        if not shown:  # If timeout occurred
                            self.logger.warning(
                                "Player window not shown within %d seconds.", timeout
                                )
                        else:
                            # Wait a bit longer to ensure compositor has mapped the window
                            time.sleep(0.3)
                            sdl2.SDL_ShowCursor(sdl2.SDL_DISABLE)
                            sdl2.SDL_WarpMouseInWindow(self.window, self.w - 1, self.h - 1)
                elif state in [vlc.State.Opening,
                               vlc.State.Buffering,
                               vlc.State.NothingSpecial]:
                    if sdl2.SDL_GetWindowFlags(self.window) & sdl2.SDL_WINDOW_SHOWN:
                        sdl2.SDL_HideWindow(self.window)
                    self._send_state("ENDED")
                # check for commands in the queue
                try:
                    line = self.cmd_queue.get_nowait()
                except queue.Empty:
                    line = None
                if line:
                    cmd = line.strip().split()
                    if not cmd:
                        continue
                    self._handle_command(cmd)
        finally:
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
                self.player.set_media(None)
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
            self.player.set_media(None)


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
    return parser.parse_args()


def main() -> None:
    """
    Entry point for the video player application.
    Initializes logging, parses arguments, sets up the video player, and starts the event loop.
    """
    logging.basicConfig(level=logging.DEBUG)
    args = parse_args()
    player = VideoPlayer(args.x, args.y, args.w, args.h, args.fit_display)
    if player.setup():
        player.run()


if __name__ == "__main__":
    main()
