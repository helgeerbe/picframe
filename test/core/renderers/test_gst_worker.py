import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from picframe.core.renderers import gst_worker
from picframe.core.renderers.gst_worker import (
    PIPELINE_COMPATIBLE,
    PIPELINE_HARDWARE_DIRECT,
    PIPELINE_HARDWARE_PLAYBIN,
    PIPELINE_SKIPPED,
    GstWorker,
    VideoStreamFacts,
)


class FakeGstError:
    def __init__(self, message: str) -> None:
        self.message = message


class FakeGstErrorMessage:
    def __init__(self, message: str, debug: str) -> None:
        self._message = message
        self._debug = debug

    def parse_error(self):
        return FakeGstError(self._message), self._debug


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


def h265_main10_facts(width: int, height: int) -> VideoStreamFacts:
    caps = FakeCaps(
        "video/x-h265, stream-format=(string)hvc1, alignment=(string)au, "
        "profile=(string)main-10, bit-depth-luma=(uint)10, "
        "bit-depth-chroma=(uint)10, colorimetry=(string)bt2100-hlg"
    )
    return VideoStreamFacts(
        caps=caps,
        caps_string=caps.to_string(),
        codec="h265",
        width=width,
        height=height,
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
        "profile=(string)main, bit-depth-luma=(uint)8, "
        "bit-depth-chroma=(uint)8, colorimetry=(string)bt709"
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


def best_element(*available: str):
    return lambda names: next((name for name in names if name in available), None)


def test_raspberry_pi_model_family_detection() -> None:
    cases = {
        "Raspberry Pi 5 Model B Rev 1.0": "pi5",
        "Raspberry Pi 500 Rev 1.0": "pi5",
        "Compute Module 5 Rev 1.0": "pi5",
        "Raspberry Pi 4 Model B Rev 1.2": "pi4",
        "Raspberry Pi 400 Rev 1.0": "pi4",
        "Compute Module 4S Rev 1.0": "pi4",
        "Raspberry Pi 3 Model B Rev 1.2": "pi3",
        "Raspberry Pi 3 Model B Plus Rev 1.3": "pi3",
        "Compute Module 3 Plus Rev 1.0": "pi3",
        "Raspberry Pi Zero 2 W Rev 1.0": "zero2",
        "Raspberry Pi Zero W Rev 1.1": "zero",
        "Ubuntu VM": None,
    }

    for model, expected in cases.items():
        assert GstWorker._raspberry_pi_model_family(model) == expected


def test_known_hardware_decode_limits_by_model() -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")

    worker._hardware_model = "Raspberry Pi 5 Model B Rev 1.0"
    assert worker._format_hardware_limit(
        worker._known_hardware_decode_limit(h265_main_facts(3840, 2160))
    ) == "3840x2160@60"
    assert worker._known_hardware_decode_limit(h264_facts(1920, 1080)) is None

    worker._hardware_model = "Raspberry Pi 4 Model B Rev 1.2"
    assert worker._format_hardware_limit(
        worker._known_hardware_decode_limit(h264_facts(1920, 1080))
    ) == "1920x1080@60"
    assert worker._format_hardware_limit(
        worker._known_hardware_decode_limit(h265_main_facts(3840, 2160))
    ) == "3840x2160@60"

    worker._hardware_model = "Raspberry Pi 3 Model B Rev 1.2"
    assert worker._format_hardware_limit(
        worker._known_hardware_decode_limit(h264_facts(1920, 1080))
    ) == "1920x1080@30"
    assert worker._known_hardware_decode_limit(h265_main_facts(1280, 720)) is None

    worker._hardware_model = "Raspberry Pi Zero 2 W Rev 1.0"
    assert worker._format_hardware_limit(
        worker._known_hardware_decode_limit(h264_facts(1920, 1080))
    ) == "1920x1080@30"

    worker._hardware_model = "Raspberry Pi Zero W Rev 1.1"
    assert worker._format_hardware_limit(
        worker._known_hardware_decode_limit(h264_facts(1920, 1080))
    ) == "1920x1080@30"


def test_handle_play_skips_uri_without_video_stream(monkeypatch) -> None:
    pipeline_new = MagicMock()
    fake_gst = SimpleNamespace(
        SECOND=1,
        Pipeline=SimpleNamespace(new=pipeline_new),
    )
    fake_info = SimpleNamespace(get_video_streams=lambda: [])
    fake_discoverer = SimpleNamespace(discover_uri=MagicMock(return_value=fake_info))
    fake_gst_pbutils = SimpleNamespace(
        Discoverer=SimpleNamespace(new=MagicMock(return_value=fake_discoverer))
    )
    monkeypatch.setattr(gst_worker, "Gst", fake_gst)
    monkeypatch.setattr(gst_worker, "GstPbutils", fake_gst_pbutils)

    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker.conn = MagicMock()
    worker.conn.closed = False

    worker._handle_play("file:///broken.mp4", 0, 0, 100, 100)

    pipeline_new.assert_not_called()
    sent_event = json.loads(worker.conn.send.call_args[0][0])
    assert sent_event["type"] == "error"
    assert sent_event["details"] == "No playable video stream found."


def test_sink_bin_does_not_set_fullscreen_when_render_rectangle_is_supplied(
    monkeypatch,
) -> None:
    created_elements = {}
    util_set_object_arg = MagicMock()

    class FakePad:
        pass

    class FakeElement:
        def __init__(self, name: str) -> None:
            self.name = name
            self.props = SimpleNamespace(fullscreen=False)
            self.set_property_calls = []

        def set_property(self, key: str, value) -> None:
            self.set_property_calls.append((key, value))

        def link(self, other) -> bool:
            return True

        def get_static_pad(self, name: str) -> FakePad:
            return FakePad()

    class FakeBin(FakeElement):
        def __init__(self, name: str) -> None:
            super().__init__(name)
            self.children = []
            self.pads = []

        def add(self, element) -> None:
            self.children.append(element)

        def add_pad(self, pad) -> None:
            self.pads.append(pad)

    def make_element(element_name: str, name: str) -> FakeElement:
        element = FakeElement(name)
        created_elements[name] = element
        return element

    fake_gst = SimpleNamespace(
        Bin=SimpleNamespace(new=lambda name: FakeBin(name)),
        Caps=SimpleNamespace(from_string=lambda value: value),
        ElementFactory=SimpleNamespace(make=make_element),
        GhostPad=SimpleNamespace(new=lambda name, pad: FakePad()),
        util_set_object_arg=util_set_object_arg,
    )
    monkeypatch.setattr(gst_worker, "Gst", fake_gst)
    monkeypatch.setattr(
        gst_worker,
        "find_best_element",
        lambda names: "waylandsink" if "waylandsink" in names else None,
    )

    worker = GstWorker("/tmp/picframe-test-gst.sock")

    worker._create_sink_bin(3, 4, 100, 200)

    sink = created_elements["sink"]
    assert ("fullscreen", True) not in sink.set_property_calls
    util_set_object_arg.assert_called_once_with(
        sink, "render-rectangle", "<3, 4, 100, 200>"
    )


def test_wayland_sink_uses_fullscreen_for_origin_rectangle(monkeypatch) -> None:
    created_elements = {}
    util_set_object_arg = MagicMock()

    class FakePad:
        pass

    class FakeElement:
        def __init__(self, name: str) -> None:
            self.name = name
            self.props = SimpleNamespace(fullscreen=False)
            self.set_property_calls = []

        def set_property(self, key: str, value) -> None:
            self.set_property_calls.append((key, value))

        def link(self, other) -> bool:
            return True

        def get_static_pad(self, name: str) -> FakePad:
            return FakePad()

    class FakeBin(FakeElement):
        def __init__(self, name: str) -> None:
            super().__init__(name)
            self.children = []
            self.pads = []

        def add(self, element) -> None:
            self.children.append(element)

        def add_pad(self, pad) -> None:
            self.pads.append(pad)

    def make_element(element_name: str, name: str) -> FakeElement:
        element = FakeElement(name)
        created_elements[name] = element
        return element

    fake_gst = SimpleNamespace(
        Bin=SimpleNamespace(new=lambda name: FakeBin(name)),
        Caps=SimpleNamespace(from_string=lambda value: value),
        ElementFactory=SimpleNamespace(make=make_element),
        GhostPad=SimpleNamespace(new=lambda name, pad: FakePad()),
        util_set_object_arg=util_set_object_arg,
    )
    monkeypatch.setattr(gst_worker, "Gst", fake_gst)
    monkeypatch.setattr(
        gst_worker,
        "find_best_element",
        lambda names: "waylandsink" if "waylandsink" in names else None,
    )

    worker = GstWorker("/tmp/picframe-test-gst.sock")

    worker._create_sink_bin(0, 0, 2560, 1440)

    sink = created_elements["sink"]
    assert ("fullscreen", True) in sink.set_property_calls
    util_set_object_arg.assert_not_called()


def test_pipeline_description_forces_software_decoders_and_uses_fullscreen_wayland(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        gst_worker,
        "find_best_element",
        lambda names: "waylandsink" if "waylandsink" in names else None,
    )
    worker = GstWorker("/tmp/picframe-test-gst.sock")

    description = worker._build_pipeline_description(
        "file:///movie.mov",
        0,
        0,
        2560,
        1440,
        force_software_decoders=True,
    )

    assert 'uri="file:///movie.mov"' in description
    assert "force-sw-decoders=true" in description
    assert "waylandsink name=sink" in description
    assert "fullscreen=true" in description
    assert "render-rectangle" not in description
    assert "rotate-method=8" in description


def test_pipeline_description_uses_rectangle_for_offset_wayland_video(monkeypatch) -> None:
    monkeypatch.setattr(
        gst_worker,
        "find_best_element",
        lambda names: "waylandsink" if "waylandsink" in names else None,
    )
    worker = GstWorker("/tmp/picframe-test-gst.sock")

    description = worker._build_pipeline_description(
        "file:///movie.mov",
        10,
        20,
        300,
        400,
        force_software_decoders=False,
    )

    assert "force-sw-decoders=true" not in description
    assert 'render-rectangle="<10, 20, 300, 400>"' in description
    assert "fullscreen=true" not in description


def test_hardware_direct_pipeline_preserves_direct_wayland_path(monkeypatch) -> None:
    monkeypatch.setattr(
        gst_worker,
        "find_best_element",
        lambda names: "waylandsink" if "waylandsink" in names else None,
    )
    worker = GstWorker("/tmp/picframe-test-gst.sock")

    description = worker._build_pipeline_description(
        "file:///movie.mp4",
        0,
        0,
        2560,
        1440,
        force_software_decoders=False,
        pipeline_variant=PIPELINE_HARDWARE_DIRECT,
    )

    assert "queue name=video_queue ! waylandsink name=sink" in description
    assert "fullscreen=true" in description
    assert "render-rectangle" not in description
    assert "videoconvert" not in description
    assert "videoscale" not in description
    assert "video/x-raw,format=RGBA" not in description
    assert "alpha alpha=0.99" not in description


def test_hardware_direct_pipeline_uses_rectangle_for_offset_wayland_video(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        gst_worker,
        "find_best_element",
        lambda names: "waylandsink" if "waylandsink" in names else None,
    )
    worker = GstWorker("/tmp/picframe-test-gst.sock")

    description = worker._build_pipeline_description(
        "file:///movie.mp4",
        10,
        20,
        300,
        400,
        force_software_decoders=False,
        pipeline_variant=PIPELINE_HARDWARE_DIRECT,
    )

    assert 'render-rectangle="<10, 20, 300, 400>"' in description
    assert "fullscreen=true" not in description


def test_hardware_playbin_pipeline_uses_video_only_wayland_sink(monkeypatch) -> None:
    monkeypatch.setattr(
        gst_worker,
        "find_best_element",
        lambda names: "waylandsink" if "waylandsink" in names else None,
    )
    worker = GstWorker("/tmp/picframe-test-gst.sock")

    description = worker._build_pipeline_description(
        "file:///movie.mp4",
        0,
        0,
        2560,
        1440,
        force_software_decoders=False,
        pipeline_variant=PIPELINE_HARDWARE_PLAYBIN,
    )

    assert description.startswith('playbin name=player uri="file:///movie.mp4"')
    assert "flags=0x00000001" in description
    assert 'video-sink="waylandsink name=sink fullscreen=true rotate-method=8"' in description
    assert 'audio-sink="fakesink sync=false"' in description
    assert "force-sw-decoders=true" not in description
    assert "videoconvert" not in description


def test_select_pipeline_variant_uses_hardware_direct_for_wayland_hardware(
    monkeypatch,
) -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker._hardware_model = "Raspberry Pi 4 Model B Rev 1.2"
    monkeypatch.setattr(
        gst_worker,
        "find_best_element",
        lambda names: "v4l2h264dec" if "v4l2h264dec" in names else None,
    )

    variant = worker._select_pipeline_variant(
        "file:///movie.mp4",
        "waylandsink",
        force_software_decoders=False,
        stream_facts=h264_facts(1728, 1080),
        max_software_decode_resolution="1280x720",
    )

    assert variant == PIPELINE_HARDWARE_DIRECT


def test_pi4_h264_1080p60_uses_hardware_direct(monkeypatch) -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker._hardware_model = "Raspberry Pi 4 Model B Rev 1.2"
    monkeypatch.setattr(gst_worker, "find_best_element", best_element("v4l2h264dec"))

    decision = worker._select_playback_decision(
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


def test_pi5_h264_720p_uses_forced_software_even_if_decoder_is_exposed(
    monkeypatch,
) -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker._hardware_model = "Raspberry Pi 5 Model B Rev 1.0"
    monkeypatch.setattr(gst_worker, "find_best_element", best_element("v4l2h264dec"))

    decision = worker._select_playback_decision(
        "file:///h264-720p.mp4",
        "waylandsink",
        force_software_decoders=False,
        max_software_decode_resolution="1280x720",
        stream_facts=h264_facts(1280, 720, framerate=30.0),
    )

    assert decision.pipeline_variant == PIPELINE_COMPATIBLE
    assert decision.force_software_decoders is True
    assert decision.decision == "software_fallback"
    assert decision.fallback_reason == "hardware_unsupported_for_model"
    assert decision.hardware_limit is None


def test_pi5_h264_1080p_skips_when_software_limit_is_exceeded(
    monkeypatch,
) -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker._hardware_model = "Raspberry Pi 5 Model B Rev 1.0"
    monkeypatch.setattr(gst_worker, "find_best_element", best_element("v4l2h264dec"))

    decision = worker._select_playback_decision(
        "file:///h264-1080p.mp4",
        "waylandsink",
        force_software_decoders=False,
        max_software_decode_resolution="1280x720",
        stream_facts=h264_facts(1920, 1080, framerate=30.0),
    )

    assert decision.pipeline_variant == PIPELINE_SKIPPED
    assert decision.decision == "skip"
    assert decision.fallback_reason == "hardware_unsupported_for_model"
    assert decision.hardware_limit is None
    assert decision.error_code == "unsupported_media"


def test_pi5_h265_4k60_uses_hardware_playbin(monkeypatch) -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker._hardware_model = "Raspberry Pi 5 Model B Rev 1.0"
    monkeypatch.setattr(gst_worker, "find_best_element", best_element("v4l2slh265dec"))

    decision = worker._select_playback_decision(
        "file:///hevc-4k60.mp4",
        "waylandsink",
        force_software_decoders=False,
        max_software_decode_resolution="1280x720",
        stream_facts=h265_main_facts(3840, 2160, framerate=60.0),
    )

    assert decision.pipeline_variant == PIPELINE_HARDWARE_PLAYBIN
    assert decision.force_software_decoders is False
    assert decision.decision == "hardware_playbin"
    assert decision.hardware_limit == "3840x2160@60"


def test_pi4_h265_main_8bit_uses_hardware_playbin_for_wayland(
    monkeypatch,
) -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker._hardware_model = "Raspberry Pi 4 Model B Rev 1.2"
    monkeypatch.setattr(
        gst_worker,
        "find_best_element",
        lambda names: "v4l2slh265dec" if "v4l2slh265dec" in names else None,
    )

    decision = worker._select_playback_decision(
        "file:///unistudios_4k_h265.mp4",
        "waylandsink",
        force_software_decoders=False,
        max_software_decode_resolution="1280x720",
        stream_facts=h265_main_facts(3840, 2160, framerate=30000 / 1001),
    )

    assert decision.pipeline_variant == PIPELINE_HARDWARE_PLAYBIN
    assert decision.force_software_decoders is False
    assert decision.decision == "hardware_playbin"
    assert decision.hardware_limit == "3840x2160@60"


def test_pi4_h265_main_8bit_mkv_above_30fps_uses_hardware_playbin(
    monkeypatch,
) -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker._hardware_model = "Raspberry Pi 4 Model B Rev 1.2"
    monkeypatch.setattr(
        gst_worker,
        "find_best_element",
        lambda names: "v4l2slh265dec" if "v4l2slh265dec" in names else None,
    )

    decision = worker._select_playback_decision(
        "file:///bbb-3840x2160-cfg02.mkv",
        "waylandsink",
        force_software_decoders=False,
        max_software_decode_resolution="1280x720",
        stream_facts=h265_main_facts(
            3840,
            2160,
            framerate=60.0,
            container="matroska",
        ),
    )

    assert decision.pipeline_variant == PIPELINE_HARDWARE_PLAYBIN
    assert decision.force_software_decoders is False
    assert decision.decision == "hardware_playbin"
    assert decision.hardware_limit == "3840x2160@60"


def test_pi4_h265_main_8bit_mp4_above_30fps_uses_hardware_playbin(
    monkeypatch,
) -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker._hardware_model = "Raspberry Pi 4 Model B Rev 1.2"
    monkeypatch.setattr(
        gst_worker,
        "find_best_element",
        lambda names: "v4l2slh265dec" if "v4l2slh265dec" in names else None,
    )

    decision = worker._select_playback_decision(
        "file:///sample-hevc-60.mp4",
        "waylandsink",
        force_software_decoders=False,
        max_software_decode_resolution="1280x720",
        stream_facts=h265_main_facts(
            1920,
            1080,
            framerate=60.0,
            container="mp4",
        ),
    )

    assert decision.pipeline_variant == PIPELINE_HARDWARE_PLAYBIN
    assert decision.force_software_decoders is False
    assert decision.decision == "hardware_playbin"


def test_pi4_h265_main_8bit_mov_above_30fps_skips_wayland_presentation(
    monkeypatch,
) -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker._hardware_model = "Raspberry Pi 4 Model B Rev 1.2"
    monkeypatch.setattr(
        gst_worker,
        "find_best_element",
        lambda names: "v4l2slh265dec" if "v4l2slh265dec" in names else None,
    )

    decision = worker._select_playback_decision(
        "file:///test_265_8.mov",
        "waylandsink",
        force_software_decoders=False,
        max_software_decode_resolution="1280x720",
        stream_facts=h265_main_facts(1920, 1080, framerate=60.0),
    )

    assert decision.pipeline_variant == PIPELINE_SKIPPED
    assert decision.force_software_decoders is False
    assert decision.decision == "skip"
    assert decision.fallback_reason == "hardware_quicktime_framerate_unsupported"
    assert decision.error_code == "unsupported_media"
    assert "60 fps" in decision.skip_reason
    assert "MOV/QuickTime" in decision.skip_reason


def test_pi4_h265_main10_skips_unsupported_wayland_presentation(
    monkeypatch,
) -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker._hardware_model = "Raspberry Pi 4 Model B Rev 1.2"
    monkeypatch.setattr(
        gst_worker,
        "find_best_element",
        lambda names: "v4l2slh265dec" if "v4l2slh265dec" in names else None,
    )

    decision = worker._select_playback_decision(
        "file:///IMG_0099.MOV",
        "waylandsink",
        force_software_decoders=False,
        max_software_decode_resolution="1280x720",
        stream_facts=h265_main10_facts(1920, 1080),
    )

    assert decision.pipeline_variant == PIPELINE_SKIPPED
    assert decision.force_software_decoders is False
    assert decision.decision == "skip"
    assert decision.fallback_reason == "hardware_presentation_unsupported"
    assert decision.error_code == "unsupported_media"


def test_non_pi_h265_without_known_hardware_uses_software_fallback() -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker._hardware_model = "Ubuntu VM"
    worker._hardware_decode_available_for_facts = lambda stream_facts: False

    decision = worker._select_playback_decision(
        "file:///movie.mp4",
        "waylandsink",
        force_software_decoders=False,
        max_software_decode_resolution="1920x1080",
        stream_facts=h265_main_facts(1280, 720),
    )

    assert decision.pipeline_variant == PIPELINE_COMPATIBLE
    assert decision.force_software_decoders is True
    assert decision.decision == "software_fallback"
    assert decision.fallback_reason == "hardware_unsupported_for_model"


def test_select_pipeline_variant_keeps_compatible_without_wayland(
    monkeypatch,
) -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker._hardware_model = "Raspberry Pi 4 Model B Rev 1.2"
    monkeypatch.setattr(
        gst_worker,
        "find_best_element",
        lambda names: "v4l2h264dec" if "v4l2h264dec" in names else None,
    )

    variant = worker._select_pipeline_variant(
        "file:///movie.mp4",
        "glimagesink",
        force_software_decoders=False,
        stream_facts=h264_facts(1728, 1080),
        max_software_decode_resolution="1280x720",
    )

    assert variant == PIPELINE_COMPATIBLE


def test_select_pipeline_variant_keeps_compatible_when_forcing_software(
    monkeypatch,
) -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker._hardware_model = "Raspberry Pi 4 Model B Rev 1.2"
    monkeypatch.setattr(
        gst_worker,
        "find_best_element",
        lambda names: "v4l2h264dec" if "v4l2h264dec" in names else None,
    )

    variant = worker._select_pipeline_variant(
        "file:///movie.mp4",
        "waylandsink",
        force_software_decoders=True,
        stream_facts=h264_facts(1728, 1080),
        max_software_decode_resolution="1920x1080",
    )

    assert variant == PIPELINE_COMPATIBLE


def test_pi4_h264_above_1080p_skips_when_software_limit_is_exceeded(
    monkeypatch,
) -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker._hardware_model = "Raspberry Pi 4 Model B Rev 1.2"
    monkeypatch.setattr(
        gst_worker,
        "find_best_element",
        lambda names: "v4l2h264dec" if "v4l2h264dec" in names else None,
    )

    decision = worker._select_playback_decision(
        "file:///vietnam.mp4",
        "waylandsink",
        force_software_decoders=False,
        max_software_decode_resolution="1280x720",
        stream_facts=h264_facts(1920, 1200),
    )

    assert decision.pipeline_variant == PIPELINE_SKIPPED
    assert decision.decision == "skip"
    assert decision.fallback_reason == "hardware_limit_exceeded"
    assert decision.hardware_limit == "1920x1080@60"
    assert decision.software_limit == "1280x720"


def test_pi4_h264_above_1080p_uses_software_when_config_allows_it(
    monkeypatch,
) -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker._hardware_model = "Raspberry Pi 4 Model B Rev 1.2"
    monkeypatch.setattr(
        gst_worker,
        "find_best_element",
        lambda names: "v4l2h264dec" if "v4l2h264dec" in names else None,
    )

    decision = worker._select_playback_decision(
        "file:///vietnam.mp4",
        "waylandsink",
        force_software_decoders=False,
        max_software_decode_resolution="1920x1200",
        stream_facts=h264_facts(1920, 1200),
    )

    assert decision.pipeline_variant == PIPELINE_COMPATIBLE
    assert decision.force_software_decoders is True
    assert decision.decision == "software_fallback"
    assert decision.fallback_reason == "hardware_limit_exceeded"


def test_pi3_h264_above_30fps_skips_when_software_limit_is_exceeded(
    monkeypatch,
) -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker._hardware_model = "Raspberry Pi 3 Model B Plus Rev 1.3"
    monkeypatch.setattr(gst_worker, "find_best_element", best_element("v4l2h264dec"))

    decision = worker._select_playback_decision(
        "file:///h264-1080p60.mp4",
        "waylandsink",
        force_software_decoders=False,
        max_software_decode_resolution="1280x720",
        stream_facts=h264_facts(1920, 1080, framerate=60.0),
    )

    assert decision.pipeline_variant == PIPELINE_SKIPPED
    assert decision.decision == "skip"
    assert decision.fallback_reason == "hardware_framerate_exceeded"
    assert decision.hardware_limit == "1920x1080@30"


def test_pi3_h264_above_30fps_uses_software_when_config_allows_it(
    monkeypatch,
) -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker._hardware_model = "Raspberry Pi 3 Model B Plus Rev 1.3"
    monkeypatch.setattr(gst_worker, "find_best_element", best_element("v4l2h264dec"))

    decision = worker._select_playback_decision(
        "file:///h264-1080p60.mp4",
        "waylandsink",
        force_software_decoders=False,
        max_software_decode_resolution="1920x1080",
        stream_facts=h264_facts(1920, 1080, framerate=60.0),
    )

    assert decision.pipeline_variant == PIPELINE_COMPATIBLE
    assert decision.force_software_decoders is True
    assert decision.decision == "software_fallback"
    assert decision.fallback_reason == "hardware_framerate_exceeded"


def test_zero2_h264_above_30fps_skips_when_software_limit_is_exceeded(
    monkeypatch,
) -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker._hardware_model = "Raspberry Pi Zero 2 W Rev 1.0"
    monkeypatch.setattr(gst_worker, "find_best_element", best_element("v4l2h264dec"))

    decision = worker._select_playback_decision(
        "file:///h264-1080p60.mp4",
        "waylandsink",
        force_software_decoders=False,
        max_software_decode_resolution="1280x720",
        stream_facts=h264_facts(1920, 1080, framerate=60.0),
    )

    assert decision.pipeline_variant == PIPELINE_SKIPPED
    assert decision.decision == "skip"
    assert decision.fallback_reason == "hardware_framerate_exceeded"
    assert decision.hardware_limit == "1920x1080@30"


def test_pi3_h265_uses_software_even_if_hevc_decoder_is_exposed(
    monkeypatch,
) -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker._hardware_model = "Raspberry Pi 3 Model B Rev 1.2"
    monkeypatch.setattr(gst_worker, "find_best_element", best_element("v4l2slh265dec"))

    decision = worker._select_playback_decision(
        "file:///hevc-720p.mp4",
        "waylandsink",
        force_software_decoders=False,
        max_software_decode_resolution="1280x720",
        stream_facts=h265_main_facts(1280, 720, framerate=30.0),
    )

    assert decision.pipeline_variant == PIPELINE_COMPATIBLE
    assert decision.force_software_decoders is True
    assert decision.decision == "software_fallback"
    assert decision.fallback_reason == "hardware_unsupported_for_model"


def test_zero_h264_requires_exposed_v4l2_decoder(monkeypatch) -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker._hardware_model = "Raspberry Pi Zero W Rev 1.1"
    monkeypatch.setattr(gst_worker, "find_best_element", best_element())

    decision = worker._select_playback_decision(
        "file:///h264-1080p30.mp4",
        "waylandsink",
        force_software_decoders=False,
        max_software_decode_resolution="1280x720",
        stream_facts=h264_facts(1920, 1080, framerate=30.0),
    )

    assert decision.pipeline_variant == PIPELINE_SKIPPED
    assert decision.decision == "skip"
    assert decision.fallback_reason == "hardware_decoder_unavailable"
    assert decision.hardware_limit == "1920x1080@30"


def test_zero_h264_uses_hardware_when_v4l2_decoder_is_exposed(monkeypatch) -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker._hardware_model = "Raspberry Pi Zero W Rev 1.1"
    monkeypatch.setattr(gst_worker, "find_best_element", best_element("v4l2h264dec"))

    decision = worker._select_playback_decision(
        "file:///h264-1080p30.mp4",
        "waylandsink",
        force_software_decoders=False,
        max_software_decode_resolution="1280x720",
        stream_facts=h264_facts(1920, 1080, framerate=30.0),
    )

    assert decision.pipeline_variant == PIPELINE_HARDWARE_DIRECT
    assert decision.force_software_decoders is False
    assert decision.decision == "hardware_direct"
    assert decision.hardware_limit == "1920x1080@30"


def test_unknown_pi_model_high_resolution_video_skips_without_known_hardware(
    monkeypatch,
) -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker._hardware_model = "Raspberry Pi Experimental Rev 1.0"
    monkeypatch.setattr(gst_worker, "find_best_element", best_element("v4l2h264dec"))

    decision = worker._select_playback_decision(
        "file:///h264-1080p.mp4",
        "waylandsink",
        force_software_decoders=False,
        max_software_decode_resolution="1280x720",
        stream_facts=h264_facts(1920, 1080, framerate=30.0),
    )

    assert decision.pipeline_variant == PIPELINE_SKIPPED
    assert decision.decision == "skip"
    assert decision.fallback_reason == "hardware_unsupported_for_model"


def test_start_pipeline_publishes_skip_error_for_oversized_pi4_h264(
    monkeypatch,
) -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker.conn = MagicMock()
    worker.conn.closed = False
    worker._hardware_model = "Raspberry Pi 4 Model B Rev 1.2"
    monkeypatch.setattr(worker, "_select_sink_name", lambda: "waylandsink")
    monkeypatch.setattr(
        gst_worker,
        "find_best_element",
        lambda names: "v4l2h264dec" if "v4l2h264dec" in names else None,
    )
    parse_launch = MagicMock()
    monkeypatch.setattr(gst_worker.Gst, "parse_launch", parse_launch, raising=False)

    worker._start_pipeline(
        "file:///vietnam.mp4",
        0,
        0,
        2560,
        1440,
        force_software_decoders=False,
        max_software_decode_resolution="1280x720",
        stream_facts=h264_facts(1920, 1200),
    )

    parse_launch.assert_not_called()
    sent_events = [json.loads(call.args[0]) for call in worker.conn.send.call_args_list]
    assert sent_events[0]["type"] == "video_diagnostics"
    assert sent_events[0]["decision"] == "skip"
    assert sent_events[-1]["type"] == "error"
    assert sent_events[-1]["code"] == "unsupported_media"


def test_caps_uses_dmabuf_detects_dmabuf_caps() -> None:
    caps = SimpleNamespace(
        to_string=lambda: (
            "video/x-raw(memory:DMABuf), format=(string)DMA_DRM, "
            "drm-format=(string)YU12"
        )
    )

    assert GstWorker._caps_uses_dmabuf(caps) is True


def test_configure_v4l2_decoder_uses_mmap_for_compatible_pipeline(monkeypatch) -> None:
    util_set_object_arg = MagicMock()
    fake_gst = SimpleNamespace(util_set_object_arg=util_set_object_arg)
    monkeypatch.setattr(gst_worker, "Gst", fake_gst)
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker._current_pipeline_variant = PIPELINE_COMPATIBLE
    factory = SimpleNamespace(get_name=lambda: "v4l2h264dec")
    element = SimpleNamespace(get_factory=lambda: factory)

    worker._configure_added_element(element)

    util_set_object_arg.assert_called_once_with(
        element,
        "capture-io-mode",
        "mmap",
    )


def test_configure_v4l2_decoder_leaves_direct_pipeline_dmabuf(monkeypatch) -> None:
    util_set_object_arg = MagicMock()
    fake_gst = SimpleNamespace(util_set_object_arg=util_set_object_arg)
    monkeypatch.setattr(gst_worker, "Gst", fake_gst)
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker._current_pipeline_variant = PIPELINE_HARDWARE_DIRECT
    factory = SimpleNamespace(get_name=lambda: "v4l2h264dec")
    element = SimpleNamespace(get_factory=lambda: factory)

    worker._configure_added_element(element)

    util_set_object_arg.assert_not_called()


def test_configure_v4l2_decoder_leaves_playbin_pipeline_defaults(monkeypatch) -> None:
    util_set_object_arg = MagicMock()
    fake_gst = SimpleNamespace(util_set_object_arg=util_set_object_arg)
    monkeypatch.setattr(gst_worker, "Gst", fake_gst)
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker._current_pipeline_variant = PIPELINE_HARDWARE_PLAYBIN
    factory = SimpleNamespace(get_name=lambda: "v4l2slh265dec")
    element = SimpleNamespace(get_factory=lambda: factory)

    worker._configure_added_element(element)

    util_set_object_arg.assert_not_called()


def test_not_negotiated_error_retries_once_with_software_decoders() -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker.conn = MagicMock()
    worker.conn.closed = False
    worker._current_play_request = ("file:///movie.mov", 1, 2, 300, 400)
    worker._start_pipeline = MagicMock()

    worker._on_error(
        MagicMock(),
        FakeGstErrorMessage(
            "Internal data stream error.",
            "streaming stopped, reason not-negotiated (-4)",
        ),
    )

    assert worker._software_decode_retry_attempted is True
    worker._start_pipeline.assert_called_once_with(
        "file:///movie.mov",
        1,
        2,
        300,
        400,
        force_software_decoders=True,
        fallback_reason="software_fallback",
        max_software_decode_resolution=None,
        stream_facts=None,
    )
    sent_event = json.loads(worker.conn.send.call_args[0][0])
    assert sent_event["type"] == "warning"
    assert sent_event["warning_type"] == "software_fallback"
    assert sent_event["decoder"] == "force-sw-decoders"


def test_hardware_direct_error_retries_compatible_pipeline_first() -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker.conn = MagicMock()
    worker.conn.closed = False
    worker._current_play_request = ("file:///movie.mov", 1, 2, 300, 400)
    worker._current_pipeline_variant = PIPELINE_HARDWARE_DIRECT
    worker._start_pipeline = MagicMock()

    worker._on_error(
        MagicMock(),
        FakeGstErrorMessage(
            "Internal data stream error.",
            "streaming stopped, reason not-negotiated (-4)",
        ),
    )

    assert worker._compatible_pipeline_retry_attempted is True
    assert worker._software_decode_retry_attempted is False
    worker._start_pipeline.assert_called_once_with(
        "file:///movie.mov",
        1,
        2,
        300,
        400,
        force_software_decoders=False,
        pipeline_variant=PIPELINE_COMPATIBLE,
        fallback_reason="hardware_direct_failed",
        max_software_decode_resolution=None,
        stream_facts=None,
    )


def test_autoplug_select_sends_hardware_decoder_diagnostics() -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker.conn = MagicMock()
    worker.conn.closed = False
    worker._current_pipeline_variant = PIPELINE_HARDWARE_DIRECT
    worker._current_sink_name = "waylandsink"
    factory = SimpleNamespace(
        get_metadata=lambda key: "Codec/Decoder/Video/Hardware",
        get_name=lambda: "v4l2h264dec",
    )

    worker._on_autoplug_select(MagicMock(), MagicMock(), MagicMock(), factory)

    sent_event = json.loads(worker.conn.send.call_args[0][0])
    assert sent_event["type"] == "video_diagnostics"
    assert sent_event["stage"] == "decoder"
    assert sent_event["pipeline_variant"] == PIPELINE_HARDWARE_DIRECT
    assert sent_event["decoder"] == "v4l2h264dec"
    assert sent_event["decoder_is_hardware"] is True
    assert sent_event["sink"] == "waylandsink"


def test_second_not_negotiated_error_is_forwarded() -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker.conn = MagicMock()
    worker.conn.closed = False
    worker._current_play_request = ("file:///movie.mov", 1, 2, 300, 400)
    worker._software_decode_retry_attempted = True
    worker._handle_stop = MagicMock()

    worker._on_error(
        MagicMock(),
        FakeGstErrorMessage(
            "Internal data stream error.",
            "streaming stopped, reason not-negotiated (-4)",
        ),
    )

    sent_event = json.loads(worker.conn.send.call_args[0][0])
    assert sent_event["type"] == "error"
    assert sent_event["details"] == "Internal data stream error."
    worker._handle_stop.assert_called_once()
