import mpv
import time


class VideoStreamer:
    def __init__(self, video_path):
        self.duration = None
        self.video_path = video_path
        player = mpv.MPV(ytdl=True, input_default_bindings=True, input_vo_keyboard=True, osc=True)

        player.fullscreen = True
        player.play(video_path)
        self.player = player
        for _ in range(10):
            if self.player.duration is not None:
                self.duration = self.player.duration
                break
            time.sleep(0.5)

    def kill(self):
        self.player.terminate()

    #TODO communicate with video player, overlay info