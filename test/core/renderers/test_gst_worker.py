import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from picframe.core.renderers import gst_worker
from picframe.core.renderers.gst_worker import GstWorker


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
