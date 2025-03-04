import mpv
import time
#TODO at the moment mpv isn't included as a dependency `python -m pip install mpv`
# it depends on having libmpv.so installed, which proabaly needs `sudo apt install libmpv-dev`

class VideoStreamer:
    def __init__(self, video_path=None):
        self.duration = None
        self.video_path = video_path
        self.player = mpv.MPV(ytdl=True, input_default_bindings=True, input_vo_keyboard=True, osc=True)
        self.player.fullscreen = True
        if self.video_path is not None:
            self.play(self.video_path)

    def play(self, video_path):
        self.stop()
        self.player.play(video_path)
        for _ in range(10):
            if self.player.duration is not None:
                self.duration = self.player.duration
                break
            time.sleep(0.5)

    def stop(self):
        self.player.stop()
        self.duration = None
        self.video_path = None

    def kill(self):
        self.player.terminate()

    #TODO communicate with video player, overlay info, etc etc
