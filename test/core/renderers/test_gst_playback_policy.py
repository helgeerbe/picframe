from picframe.core.renderers.gst_playback_policy import (
    PIPELINE_COMPATIBLE,
    PIPELINE_HARDWARE_DIRECT,
    PIPELINE_HARDWARE_PLAYBIN,
    PIPELINE_SKIPPED,
    PlaybackPolicy,
    VideoStreamFacts,
)


class FakeCaps:
    def __init__(self, caps_string: str) -> None:
        self._caps_string = caps_string

    def to_string(self) -> str:
        return self._caps_string


def h264_facts(
    width: int,
    height: int,
    *,
    framerate: float | None = None,
    container: str | None = None,
) -> VideoStreamFacts:
    caps = FakeCaps("video/x-h264, stream-format=(string)avc")
    return VideoStreamFacts(
        caps=caps,
        caps_string=caps.to_string(),
        codec="h264",
        width=width,
        height=height,
        framerate=framerate,
        container=container,
    )


def h265_main_facts(
    width: int,
    height: int,
    *,
    framerate: float | None = None,
    container: str | None = None,
) -> VideoStreamFacts:
    caps = FakeCaps(
        "video/x-h265, stream-format=(string)hvc1, alignment=(string)au, "
        "profile=(string)main, bit-depth-luma=(uint)8"
    )
    return VideoStreamFacts(
        caps=caps,
        caps_string=caps.to_string(),
        codec="h265",
        width=width,
        height=height,
        framerate=framerate,
        container=container,
    )


def h265_main10_facts(width: int, height: int) -> VideoStreamFacts:
    caps = FakeCaps(
        "video/x-h265, stream-format=(string)hvc1, alignment=(string)au, "
        "profile=(string)main-10, bit-depth-luma=(uint)10, "
        "colorimetry=(string)bt2100-hlg"
    )
    return VideoStreamFacts(
        caps=caps,
        caps_string=caps.to_string(),
        codec="h265",
        width=width,
        height=height,
    )


def policy(
    model: str,
    *,
    hardware_available: bool = True,
) -> PlaybackPolicy:
    return PlaybackPolicy(model, lambda _facts: hardware_available)


def test_pi4_h264_1080p60_uses_hardware_direct() -> None:
    decision = policy("Raspberry Pi 4 Model B Rev 1.2").select_playback_decision(
        "file:///movie.mp4",
        "waylandsink",
        force_software_decoders=False,
        max_software_decode_resolution="1280x720",
        stream_facts=h264_facts(1920, 1080, framerate=60.0),
    )

    assert decision.pipeline_variant == PIPELINE_HARDWARE_DIRECT
    assert decision.force_software_decoders is False
    assert decision.decision == "hardware_direct"
    assert decision.hardware_limit == "1920x1080@60"


def test_pi5_h265_4k60_uses_hardware_playbin() -> None:
    decision = policy("Raspberry Pi 5 Model B Rev 1.0").select_playback_decision(
        "file:///hevc-4k60.mp4",
        "waylandsink",
        force_software_decoders=False,
        max_software_decode_resolution="1280x720",
        stream_facts=h265_main_facts(3840, 2160, framerate=60.0),
    )

    assert decision.pipeline_variant == PIPELINE_HARDWARE_PLAYBIN
    assert decision.decision == "hardware_playbin"
    assert decision.hardware_limit == "3840x2160@60"


def test_pi_h265_main10_remains_hardware_only_when_decoder_is_unavailable() -> None:
    decision = policy(
        "Raspberry Pi 4 Model B Rev 1.2",
        hardware_available=False,
    ).select_playback_decision(
        "file:///IMG_0103.MOV",
        "waylandsink",
        force_software_decoders=False,
        max_software_decode_resolution="1920x1080",
        stream_facts=h265_main10_facts(1920, 1080),
    )

    assert decision.pipeline_variant == PIPELINE_SKIPPED
    assert decision.decision == "skip"
    assert decision.fallback_reason == "hardware_decoder_unavailable"
    assert decision.error_code == "unsupported_media"


def test_ubuntu_vm_h265_main10_uses_software_when_within_limit() -> None:
    decision = policy("Ubuntu VM", hardware_available=False).select_playback_decision(
        "file:///IMG_0103.MOV",
        "waylandsink",
        force_software_decoders=False,
        max_software_decode_resolution="1920x1080",
        stream_facts=h265_main10_facts(1920, 1080),
    )

    assert decision.pipeline_variant == PIPELINE_COMPATIBLE
    assert decision.force_software_decoders is True
    assert decision.decision == "software_fallback"


def test_pi4_h264_above_limit_respects_software_decode_setting() -> None:
    reject = policy("Raspberry Pi 4 Model B Rev 1.2").select_playback_decision(
        "file:///large.mp4",
        "waylandsink",
        force_software_decoders=False,
        max_software_decode_resolution="1280x720",
        stream_facts=h264_facts(1920, 1200),
    )
    allow = policy("Raspberry Pi 4 Model B Rev 1.2").select_playback_decision(
        "file:///large.mp4",
        "waylandsink",
        force_software_decoders=False,
        max_software_decode_resolution="1920x1200",
        stream_facts=h264_facts(1920, 1200),
    )

    assert reject.pipeline_variant == PIPELINE_SKIPPED
    assert reject.fallback_reason == "hardware_limit_exceeded"
    assert allow.pipeline_variant == PIPELINE_COMPATIBLE
    assert allow.force_software_decoders is True
    assert allow.fallback_reason == "hardware_limit_exceeded"


def test_pi_model_family_detection() -> None:
    assert PlaybackPolicy.raspberry_pi_model_family("Raspberry Pi 5 Model B") == "pi5"
    assert PlaybackPolicy.raspberry_pi_model_family("Raspberry Pi 4 Model B") == "pi4"
    assert PlaybackPolicy.raspberry_pi_model_family("Raspberry Pi 3 Model B") == "pi3"
    assert PlaybackPolicy.raspberry_pi_model_family("Raspberry Pi Zero 2 W") == "zero2"
    assert PlaybackPolicy.raspberry_pi_model_family("Raspberry Pi Zero W") == "zero"
    assert PlaybackPolicy.raspberry_pi_model_family("Ubuntu VM") is None
