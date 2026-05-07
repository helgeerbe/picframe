import pytest
from picframe.core.renderers.gst_utils import ffprobe_codec_to_gst_caps

def test_ffprobe_codec_to_gst_caps_basic():
    assert ffprobe_codec_to_gst_caps("h264") == "video/x-h264"
    assert ffprobe_codec_to_gst_caps("hevc") == "video/x-h265"
    assert ffprobe_codec_to_gst_caps("vp8") == "video/x-vp8"
    assert ffprobe_codec_to_gst_caps("vp9") == "video/x-vp9"
    assert ffprobe_codec_to_gst_caps("mpeg4") == "video/mpeg, mpegversion=4"
    assert ffprobe_codec_to_gst_caps("mjpeg") == "image/jpeg"
    assert ffprobe_codec_to_gst_caps("av1") == "video/x-av1"

def test_ffprobe_codec_to_gst_caps_with_dimensions():
    assert ffprobe_codec_to_gst_caps("h264", width=1920, height=1080) == "video/x-h264, width=1920, height=1080"
    assert ffprobe_codec_to_gst_caps("hevc", width=3840, height=2160) == "video/x-h265, width=3840, height=2160"

def test_ffprobe_codec_to_gst_caps_unknown_codec():
    assert ffprobe_codec_to_gst_caps("unknown_codec") == "video/x-unknown_codec"

def test_ffprobe_codec_to_gst_caps_none():
    assert ffprobe_codec_to_gst_caps(None) is None
