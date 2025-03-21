import vlc
import time
import threading
import pi3d
import sdl2
import sys

class VideoStreamer:
    def __init__(self, video_path=None):
        display = pi3d.Display.Display.INSTANCE
        self._parseReady = False
        self.duration = None
        self.is_playing = False
        self.instance = vlc.Instance('--no-audio')
        self.player = self.instance.media_player_new()
        wminfo = sdl2.SDL_SysWMinfo();
        sdl2.SDL_GetVersion(wminfo.version);
        if(sdl2.SDL_GetWindowWMInfo(display.opengl.window, wminfo) == 0):
            print("can't get SDL WM info");
            sys.exit(1);
        win_id = wminfo.info.x11.window;
        self.player.set_xwindow(win_id)
        self.t = None
        self.kill_thread = False
        if video_path is not None:
            self.play(video_path)

    def  _ParseReceived(self, event):
        self._parseReady = True

    def _get_duration(self, media=None):
        self._parseReady = False
        self.duration = None
        if media is not None:
            events = media.event_manager()
            events.event_attach(vlc.EventType.MediaParsedChanged, self._ParseReceived)
            media.parse_with_options(1, 0)
            while self._parseReady == False:
                time.sleep(0.1)
            self.duration = (media.get_duration() / 1000) # Total duration in seconds


    def play(self, video_path):
        if video_path is not None:
            media = self.instance.media_new_path(video_path)
            self.player.set_media(media)
            self._get_duration(media)
            self.t = threading.Thread(target=self.play_loop)
            self.is_playing = True
            self.t.start()

    def play_loop(self):
        self.kill_thread = False
        self.player.play()
        while self.player.get_state() != vlc.State.Ended and self.kill_thread == False:
            time.sleep(0.25)
        self.player.stop()
        self.player.get_media().release()
        self.is_playing = False

    def stop(self):
        self.kill_thread = True
        if self.t is not None:
            self.t.join()
        self.duration = None
        

    def kill(self):
        self.kill_thread = True
        if self.t is not None:
            self.t.join()
        self.duration = None

    #TODO communicate with video player, overlay info, etc etc
