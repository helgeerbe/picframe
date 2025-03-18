import vlc
import time


class VideoStreamer:
    def __init__(self, video_path=None):
        self._parseReady = False
        self.duration = None
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
        self._instance = vlc.Instance('--no-audio')
        self.player = self._instance.media_player_new()
        if self.player.get_fullscreen() == 0:
            self.player.toggle_fullscreen()
        if video_path is not None:
            media = self._instance.media_new_path(video_path)
            self.player.set_media(media)
            self._get_duration(media)
            self.player.play()


    def stop(self):
        self.player.stop()
        self.player.get_media().release()
        self.duration = None

    def kill(self):
        self.player.stop()
        self.player.get_media.release()

    #TODO communicate with video player, overlay info, etc etc
