import sys
import argparse
import vlc
import os
import sdl2
import ctypes
import time
import logging
import select


def main():
    # Set up logging
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger("video_player")
    logger.debug("Starting video player")

    # Parse command line arguments
    parser = argparse.ArgumentParser()
    parser.add_argument("--x", type=int, default=0)
    parser.add_argument("--y", type=int, default=0)
    parser.add_argument("--w", type=int, default=640)
    parser.add_argument("--h", type=int, default=480)
    parser.add_argument("--fit_display", action="store_true")
    args = parser.parse_args()

    # Initialize SDL2 and create window
    sdl2.SDL_Init(sdl2.SDL_INIT_VIDEO)
    window = sdl2.SDL_CreateWindow(
        b"",
        args.x, args.y,
        args.w, args.h,
        sdl2.SDL_WINDOW_HIDDEN | sdl2.SDL_WINDOW_BORDERLESS 
    )
    if not window:
        logger.error("Error creating window: %s",sdl2.SDL_GetError().decode('utf-8'))
        return
    
    # Set window properties
    sdl2.SDL_ShowCursor(sdl2.SDL_DISABLE)

    # Get the ACTUAL window info from SDL
    wm_info = sdl2.SDL_SysWMinfo()
    sdl2.SDL_VERSION(wm_info.version)
    if not sdl2.SDL_GetWindowWMInfo(window, ctypes.byref(wm_info)):
        logger.error("Error: Could not get window information!")
        sdl2.SDL_DestroyWindow(window)
        return

    # Initialize VLC
    vlc_args = ['--no-audio']
    instance = vlc.Instance(vlc_args)
    player = instance.media_player_new()
    # player.set_fullscreen(True)

    # Set the VLC player to use the SDL2 window
    if sys.platform == "darwin":
        try:
            if sdl2.SDL_GetWindowWMInfo(window, ctypes.byref(wm_info)):
                # Use PyObjC to get the NSView from the NSWindow pointer
                from rubicon.objc import ObjCInstance
                nswindow_ptr = wm_info.info.cocoa.window
                nswindow = ObjCInstance(ctypes.c_void_p(nswindow_ptr))
                nsview = nswindow.contentView
                player.set_nsobject(nsview.ptr.value)
                logger.debug("Set NSView: %s", nsview)
            else:
                logger.error("Error: Could not get window information!")
                player.set_nsobject(None)
        except Exception as e:
            logger.error("Could not set NSView: %s", e)
            player.set_nsobject(None)
    elif sys.platform.startswith("linux"):
        if wm_info.subsystem == sdl2.SDL_SYSWM_X11:
            xid = wm_info.info.x11.window
            logger.debug("X11 window ID: %s", xid)
            player.set_xwindow(xid)
        else:
            logger.error("VLC embedding not supported on: %s", wm_info.subsystem)
    elif sys.platform == "win32":
        player.set_hwnd(sdl2.SDL_GetWindowID(window))

    # Set aspect ratio if fit_display is requested
    if args.fit_display:
        aspect_ratio = f"{args.w}:{args.h}"
        player.video_set_aspect_ratio(aspect_ratio)

    event = sdl2.SDL_Event()

    def poll_events():
        while sdl2.SDL_PollEvent(ctypes.byref(event)):
            if event.type == sdl2.SDL_QUIT:
                return False
        return True

    last_state = None  # Track the last state sent

    def send_state(state):
        nonlocal last_state
        if state != last_state:
            logger.info(f"State changed to: {state}")
            print(f"STATE:{state}", flush=True)
            last_state = state


    # media_path = "test/videos/SampleVideo_720x480_1mb.mp4"
    # media = instance.media_new_path(media_path)
    # player.set_media(media)
    # sdl2.SDL_ShowWindow(window)
    # player.play()

    # while True:
    #     poll_events()
    #     if player.get_state() == vlc.State.Ended:
    #         send_state("ENDED")
    #         break
    # return

    while True:
        poll_events()
        # Also check player state
        state = player.get_state()
        if state == vlc.State.Ended:
            sdl2.SDL_HideWindow(window)
            player.stop()
            player.set_media(None) 
            send_state("ENDED")
        if state in [vlc.State.Opening, vlc.State.Playing,
                     vlc.State.Paused, vlc.State.Buffering]:
            sdl2.SDL_ShowWindow(window)
            send_state("PLAYING")
        # Wait for up to 0.1s for input, but keep polling events
        rlist, _, _ = select.select([sys.stdin], [], [], 0.1)
        if rlist:
            line = sys.stdin.readline()
            if not line:
                break
            cmd = line.strip().split()
            if not cmd:
                continue
            if cmd[0] == "load" and len(cmd) > 1:
                media_path = " ".join(cmd[1:])
                if os.path.exists(media_path):
                    player.stop()
                    player.set_media(None) 
                    media = instance.media_new_path(media_path)
                    player.set_media(media)
                    sdl2.SDL_ShowWindow(window)
                    player.play()
            elif cmd[0] == "pause":
                player.pause()
            elif cmd[0] == "resume":
                if player.get_state() == vlc.State.Paused:
                    player.pause() 
            elif cmd[0] == "stop":
                sdl2.SDL_HideWindow(window)
                player.stop()
                player.set_media(None) 
                send_state("ENDED")
            elif cmd[0] == "quit":
                sdl2.SDL_HideWindow(window)
                player.stop()
                player.set_media(None) 
                send_state("QUIT")
                break
            # Optionally, add more commands as needed
    # Cleanup SDL2
    sdl2.SDL_DestroyWindow(window)
    sdl2.SDL_Quit()


if __name__ == "__main__":
    main()
