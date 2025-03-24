import vlc
import pi3d
import sdl2
import sys
import logging

class VideoStreamer:
    def __init__(self, video_path=None):
        self.__logger = logging.getLogger("video_streamer")
        self.__logger.setLevel("DEBUG")
        self.__logger.debug("Init")
        display = pi3d.Display.Display.INSTANCE
        self.instance = vlc.Instance('--no-audio')
        self.player = self.instance.media_player_new()
        wminfo = sdl2.SDL_SysWMinfo()
        sdl2.SDL_GetVersion(wminfo.version)
        if(sdl2.SDL_GetWindowWMInfo(display.opengl.window, wminfo) == 0):
            self.__logger.error("Can't get SDL WM info.")
            sys.exit(1)
        win_id = wminfo.info.x11.window

        self.player.set_xwindow(win_id)
        if video_path is not None:
            self.play(video_path)

    def play(self, video_path):
        if video_path is not None:
            self.__logger.debug("Set media: %s", video_path)
            media = self.instance.media_new_path(video_path)
            self.player.set_media(media)
            self.__logger.debug("Play video")
            self.player.play()  

    def is_playing(self):
        state = self.player.get_state()
        # self.__logger.debug("Player state: %d", state.value)
        return state in [vlc.State.Opening, vlc.State.Playing, vlc.State.Paused, vlc.State.Buffering]

    def stop(self):
        self.__logger.debug("Stop video")
        self.player.stop()
        self.__logger.debug("Release media")
        self.player.get_media().release()

    def kill(self):
        self.__logger.debug("Kill video")
        self.player.stop()
        self.player.get_media().release()
        
    #TODO communicate with video player, overlay info, etc etc
