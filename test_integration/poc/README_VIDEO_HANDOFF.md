# Video Handoff Proof of Concept

This document describes how to run the `poc_video_handoff.py` script, which demonstrates a seamless transition between a `pi3d` image slideshow and a GStreamer video player on a Wayland compositor (Ubuntu/Raspberry Pi).

## Prerequisites

This script is designed to run on a Linux system using a Wayland compositor (e.g., Ubuntu with GNOME Wayland, or Raspberry Pi OS based on Debian Bookworm/Trixie with Wayfire/labwc).

### System Packages

You need to install GStreamer and its Python bindings. Open a terminal and run:

```bash
sudo apt update
sudo apt full-upgrade
sudo apt install labwc 
sudo apt install seatd
sudo systemctl enable --now seatd
sudo groupadd _seatd
sudo usermod -aG _seatd $USER
sudo systemctl restart seatd
sudo apt install vlc-plugin-video-output vlc-bin
sudo apt install ffmpeg

sudo apt install pipewire-audio-client-libraries
sudo apt install gir1.2-gstreamer-1.0 gir1.2-gst-plugins-base-1.0

sudo apt install python3-gi gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly

python -m venv --system-site-packages .venv
source .venv/bin/activate
pip install picframe
```



## System Configuration

To ensure a seamless transition without the window manager animating the appearance and disappearance of the image and video windows, you must disable desktop animations.

### Disabling GNOME Animations

If you are using GNOME (the default on Ubuntu), run the following command in your terminal:

```bash
gsettings set org.gnome.desktop.interface enable-animations false
```

*(Note: To re-enable animations later, run the same command with `true` instead of `false`.)*

## Supported Video Formats

The script uses GStreamer's `playbin` element, which automatically selects the appropriate decoders based on the installed GStreamer plugins. By installing the `gstreamer1.0-plugins-good`, `bad`, and `ugly` packages as instructed above, you should have support for most common video formats, including:

*   **MP4** (H.264, H.265/HEVC)
*   **WebM** (H.265/HEVC)
*   **MKV** (VP8, VP9)
*   **AVI**

Hardware acceleration (e.g., on the Raspberry Pi) depends on the specific GStreamer plugins available for that platform (like `v4l2h264dec`).

## Running the Script

The script requires at least two arguments: the path to the first image and the path to the video. You can optionally provide a third argument for the second image to be displayed after the video finishes.

### Raspberry Pi (labwc)

On Raspberry Pi OS with labwc compositor:

```bash
labwc -s "python3 poc_video_handoff_v2.py <image1> <video> <image2>"
```

Example:
```bash
labwc -s "python3 poc_video_handoff_v2.py /path/to/image1.jpg /path/to/video.webm /path/to/image2.jpg"
```

### EOS Redraw / Alpha Probe

The v2 script can test whether keeping the video frame frozen at EOS and briefly
making it translucent is enough to make the compositor redraw pi3d before the
video window is destroyed.

Fast baseline without conversion:

```bash
labwc -s "python3 poc_video_handoff_v2.py /path/to/image1.jpg /path/to/video.mp4 /path/to/image2.jpg --pipeline-mode direct --eos-redraw-seconds 0.25"
```

Alpha probe:

```bash
labwc -s "python3 poc_video_handoff_v2.py /path/to/image1.jpg /path/to/video.mp4 /path/to/image2.jpg --pipeline-mode alpha-probe --eos-alpha 0.99 --eos-redraw-seconds 0.25"
```

The `alpha-probe` mode keeps alpha at `1.0` while the video plays, then pauses at
EOS, sets alpha to `0.99`, seeks close to the end to preroll one final
transparent frame, forces a short pi3d redraw, and only then closes the video
window. This mode is only a compositor-handoff experiment; it may be less smooth
than the `direct` path because it inserts `videoconvert` and `alpha`.

If the video-to-pi3d handoff no longer flickers but the last frame jumps slightly,
use `--last-frame-offset` to make the PoC extract pi3d's handoff frame and seek
GStreamer to the same timestamp near the end:

```bash
labwc -s "python3 poc_video_handoff_v2.py /path/to/image1.jpg /path/to/video.mp4 /path/to/image2.jpg --pipeline-mode alpha-probe --eos-alpha 0.99 --last-frame-offset 0.25"
```

To isolate whether the jump is caused by the EOS seek, try:

```bash
labwc -s "python3 poc_video_handoff_v2.py /path/to/image1.jpg /path/to/video.mp4 /path/to/image2.jpg --pipeline-mode alpha-probe --eos-alpha 0.0 --alpha-probe-seek-mode none"
```

If this removes the jump but also means the video surface does not become
transparent, the alpha value is not reaching the compositor as window opacity.
If `key-unit` jumps backwards, try `--alpha-probe-seek-mode accurate`; it can be
slower, but it seeks closer to the requested handoff timestamp.

Full-GPU opacity probe:

```bash
labwc -s "python3 poc_video_handoff_v2.py /path/to/image1.jpg /path/to/video.mp4 /path/to/image2.jpg --pipeline-mode gtk-gpu-opacity --eos-window-opacity 0.99 --eos-redraw-seconds 0.25 --require-gpu"
```

The `gtk-gpu-opacity` mode uses `playbin` with `gtkwaylandsink` hosted inside a
fullscreen GTK3 window. It does not intentionally add `videoconvert`,
`videoscale`, caps forcing, or GStreamer `alpha` during playback. At EOS it
pauses the pipeline, optionally seeks near the handoff frame, changes GTK window
opacity, redraws pi3d briefly, then closes the video window.

If the handoff still jumps, compare with an accurate EOS seek:

```bash
labwc -s "python3 poc_video_handoff_v2.py /path/to/image1.jpg /path/to/video.mp4 /path/to/image2.jpg --pipeline-mode gtk-gpu-opacity --gpu-eos-seek-mode accurate --last-frame-offset 0.25 --eos-window-opacity 0.99 --eos-redraw-seconds 0.25 --require-gpu"
```

To test whether pi3d can use the exact same frame as the video sink, read the
sink's actual last sample timestamp at EOS and rebuild the pi3d handoff texture
from that PTS:

```bash
labwc -s "python3 poc_video_handoff_v2.py /path/to/image1.jpg /path/to/video.mp4 /path/to/image2.jpg --pipeline-mode gtk-gpu-opacity --last-frame-source gst-last-sample-pts --eos-window-opacity 1.0 --eos-redraw-seconds 0 --gpu-eos-seek-mode none --require-gpu"
```

This mode logs the sink `last-sample` PTS/DTS/duration/caps, uses a slow but
accurate ffmpeg seek to extract that timestamp, draws the updated pi3d texture
behind the video window, then closes the window. It is intended for validation,
not as the final production implementation.

For GPU validation, check the `GPU telemetry` log lines. A good Pi path should
show a hardware-like decoder such as `v4l2...dec`, ideally `memory:DMABuf` sink
caps, and no `videoconvert`, `videoscale`, or `alpha` elements.

The script resolves the `blend_new` shader from `~/.picframe/data/shaders` first,
then from installed Picframe package data, and finally from a local repository
checkout. Override this with `--shader-path /path/to/blend_new` if needed.

Before swapping pi3d to the video's last-frame texture, the script waits until
GStreamer reports playback progress. This avoids showing the last frame if a
slow pipeline has not made the video surface visible yet. Tune this with
`--last-frame-swap-after` and `--last-frame-swap-timeout`.

## What to Expect

1.  **Phase 1:** The script displays the first image fullscreen using `pi3d`.
2.  **Phase 2:** The `pi3d` image blends to the first frame of the video (extracted beforehand).
3.  **Phase 3:** The GStreamer video pipeline starts in the background, rendering on top of the pi3d canvas.
4.  **Phase 4:** The script waits for the video to finish. During this time, it swaps the `pi3d` texture to the last frame of the video invisibly (behind the playing video).
5.  **Phase 5:** When the video finishes, GStreamer releases its window, revealing the last video frame immediately.
6.  **Phase 6:** The script blends to the final image (if provided) and displays it for a few seconds before exiting.
