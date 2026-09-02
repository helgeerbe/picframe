#!/usr/bin/env python3
"""Standalone GStreamer MOV playback probe for Raspberry Pi Wayland."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import gi

gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst  # noqa: E402


def _uri_for(path_or_uri: str) -> str:
    if path_or_uri.startswith("file://"):
        return path_or_uri
    return Path(path_or_uri).expanduser().resolve().as_uri()


def _pipeline_description(uri: str, *, mode: str) -> str:
    sink = "waylandsink name=sink rotate-method=8"
    nosync_sink = "waylandsink name=sink rotate-method=8 sync=false qos=false max-lateness=-1"
    gl_sink = "glimagesink name=sink sync=false qos=false max-lateness=-1"
    fps_sink = (
        'fpsdisplaysink name=fps text-overlay=false signal-fps-measurements=true '
        'video-sink="waylandsink name=sink rotate-method=8"'
    )
    force_sw = " force-sw-decoders=true" if mode == "software" else ""
    compatible_chain = (
        f'uridecodebin name=decoder uri="{uri}"{force_sw} '
        "decoder. ! queue ! "
        "videoconvert n-threads=4 qos=false ! "
        "videoscale add-borders=false ! "
        "videoconvert n-threads=4 qos=false ! "
        "video/x-raw,format=RGBA ! "
    )
    p010_chain = (
        f'uridecodebin name=decoder uri="{uri}" '
        "decoder. ! queue ! "
        "videoconvert n-threads=4 qos=false ! "
        "video/x-raw,format=P010_10LE ! "
    )
    nv12_chain = (
        f'uridecodebin name=decoder uri="{uri}" '
        "decoder. ! queue ! "
        "videoconvert n-threads=4 qos=false ! "
        "video/x-raw,format=NV12 ! "
    )
    if mode == "playbin":
        return f'playbin uri="{uri}" video-sink="{sink}"'
    if mode == "direct":
        return (
            f'uridecodebin name=decoder uri="{uri}" '
            "decoder. ! queue ! "
            f"{sink}"
        )
    if mode == "gl":
        return (
            f'uridecodebin name=decoder uri="{uri}" '
            "decoder. ! queue ! "
            f"{gl_sink}"
        )
    if mode == "glconvert":
        return (
            f'uridecodebin name=decoder uri="{uri}" '
            "decoder. ! queue ! "
            "glupload ! glcolorconvert ! "
            f"{gl_sink}"
        )
    if mode == "p010":
        return p010_chain + nosync_sink
    if mode == "nv12":
        return nv12_chain + nosync_sink
    if mode == "nosync":
        return compatible_chain + nosync_sink
    if mode == "fps":
        return compatible_chain + fps_sink
    return compatible_chain + sink


def _on_autoplug_select(_bin, _pad, _caps, factory) -> int:
    klass = factory.get_metadata(Gst.ELEMENT_METADATA_KLASS)
    if klass and "Decoder" in klass and "Video" in klass:
        print(f"decoder={factory.get_name()} klass={klass}", flush=True)
    return 0


def _on_pad_added(_element, pad) -> None:
    caps = pad.get_current_caps() or pad.query_caps()
    if not caps:
        return
    structure = caps.get_structure(0)
    if structure.get_name().startswith("video/"):
        print(f"decoded_caps={caps.to_string()}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "video",
        nargs="?",
        default="/home/pi/Pictures/testfiles/IMG_0103.MOV",
        help="MOV/MP4 file to play",
    )
    parser.add_argument(
        "--mode",
        choices=(
            "compatible",
            "nosync",
            "fps",
            "gl",
            "glconvert",
            "p010",
            "nv12",
            "software",
            "playbin",
            "direct",
        ),
        default="compatible",
        help="Pipeline mode to test",
    )
    args = parser.parse_args()

    Gst.init(None)
    loop = GLib.MainLoop()
    uri = _uri_for(args.video)
    description = _pipeline_description(uri, mode=args.mode)
    print(description, flush=True)

    pipeline = Gst.parse_launch(description)
    decoder = pipeline.get_by_name("decoder")
    if decoder:
        decoder.connect("autoplug-select", _on_autoplug_select)
        decoder.connect("pad-added", _on_pad_added)
    fps = pipeline.get_by_name("fps")
    if fps:
        fps.connect(
            "fps-measurements",
            lambda _fps, fps_value, drop_rate, avg_fps:
                print(
                    "fps="
                    f"{fps_value:.2f} drop_rate={drop_rate:.2f} avg={avg_fps:.2f}",
                    flush=True,
                ),
        )

    bus = pipeline.get_bus()
    bus.add_signal_watch()
    started_at = time.monotonic()

    def on_eos(_bus, _msg):
        elapsed = time.monotonic() - started_at
        sink_element = pipeline.get_by_name("sink")
        stats = sink_element.get_property("stats") if sink_element else None
        stats_text = stats.to_string() if stats else None
        print(f"EOS elapsed={elapsed:.2f}s stats={stats_text}", flush=True)
        loop.quit()

    def on_error(_bus, msg):
        err, debug = msg.parse_error()
        print(f"ERROR: {err.message}", flush=True)
        if debug:
            print(f"DEBUG: {debug}", flush=True)
        loop.quit()

    bus.connect("message::eos", on_eos)
    bus.connect("message::error", on_error)

    pipeline.set_state(Gst.State.PLAYING)
    try:
        loop.run()
    finally:
        pipeline.set_state(Gst.State.NULL)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
