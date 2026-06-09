import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from picframe.core.renderers import gst_worker
from picframe.core.renderers.gst_worker import GstWorker


class FakeGstError:
    def __init__(self, message: str) -> None:
        self.message = message


class FakeGstErrorMessage:
    def __init__(self, message: str, debug: str) -> None:
        self._message = message
        self._debug = debug

    def parse_error(self):
        return FakeGstError(self._message), self._debug


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


def test_wayland_sink_uses_render_rectangle_for_origin_rectangle(monkeypatch) -> None:
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
    assert ("fullscreen", True) not in sink.set_property_calls
    util_set_object_arg.assert_called_once_with(
        sink, "render-rectangle", "<0, 0, 2560, 1440>"
    )


def test_pipeline_description_forces_software_decoders_and_uses_origin_rectangle(
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
    assert 'render-rectangle="<0, 0, 2560, 1440>"' in description
    assert "rotate-method=8" in description
    assert "fullscreen=true" not in description


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
    )
    sent_event = json.loads(worker.conn.send.call_args[0][0])
    assert sent_event["type"] == "warning"
    assert sent_event["warning_type"] == "software_fallback"
    assert sent_event["decoder"] == "force-sw-decoders"


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
