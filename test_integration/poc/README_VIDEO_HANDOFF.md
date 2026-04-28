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

## What to Expect

1.  **Phase 1:** The script displays the first image fullscreen using `pi3d`.
2.  **Phase 2:** The `pi3d` image blends to the first frame of the video (extracted beforehand).
3.  **Phase 3:** The GStreamer video pipeline starts in the background, rendering on top of the pi3d canvas.
4.  **Phase 4:** The script waits for the video to finish. During this time, it swaps the `pi3d` texture to the last frame of the video invisibly (behind the playing video).
5.  **Phase 5:** When the video finishes, GStreamer releases its window, revealing the last video frame immediately.
6.  **Phase 6:** The script blends to the final image (if provided) and displays it for a few seconds before exiting.
