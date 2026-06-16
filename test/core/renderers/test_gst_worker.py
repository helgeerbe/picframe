import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from picframe.core.renderers import gst_worker
from picframe.core.renderers.gst_worker import (
    GTK_PRESENTATION_UNAVAILABLE_CODE,
    PIPELINE_COMPATIBLE,
    PIPELINE_GTK_COMPATIBLE,
    PIPELINE_GTK_PLAYBIN,
    PIPELINE_HARDWARE_DIRECT,
    PIPELINE_HARDWARE_PLAYBIN,
    PIPELINE_SKIPPED,
    GstWorker,
    PlayRequest,
    PlaybackDecision,
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


class FakeCapsWithStructure(FakeCaps):
    def __init__(self, caps_string: str, structure) -> None:
        super().__init__(caps_string)
        self._structure = structure

    def get_structure(self, index: int):
        assert index == 0
        return self._structure


class FakeStringStructure:
    def __init__(self, text: str) -> None:
        self._text = text

    def __str__(self) -> str:
        return self._text


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


def test_caps_structure_name_supports_gi_structure_variants() -> None:
    assert GstWorker._caps_structure_name(
        FakeCapsWithStructure(
            "video/x-raw(memory:DMABuf), format=(string)DMA_DRM",
            SimpleNamespace(get_name=lambda: "video/x-raw"),
        )
    ) == "video/x-raw"

    assert GstWorker._caps_structure_name(
        FakeCapsWithStructure(
            "video/x-raw(memory:DMABuf), format=(string)DMA_DRM",
            SimpleNamespace(name="video/x-raw(memory:DMABuf)"),
        )
    ) == "video/x-raw(memory:DMABuf)"

    assert GstWorker._caps_structure_name(
        FakeCapsWithStructure(
            "video/x-raw(memory:DMABuf), format=(string)DMA_DRM",
            FakeStringStructure("video/x-raw(memory:DMABuf), format=(string)DMA_DRM"),
        )
    ) == "video/x-raw(memory:DMABuf)"

    assert GstWorker._caps_structure_name(
        FakeCapsWithStructure(
            "video/x-raw(memory:DMABuf), format=(string)DMA_DRM",
            FakeStringStructure("<StructureWrapper object>"),
        )
    ) == "video/x-raw(memory:DMABuf)"


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


def test_gtk_compatible_pipeline_keeps_natural_video_by_default() -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")

    description = worker._build_gtk_compatible_pipeline_description(
        "file:///movie.mov",
        300,
        400,
        force_software_decoders=True,
    )

    assert 'uridecodebin name=decoder uri="file:///movie.mov" force-sw-decoders=true' in description
    assert "queue name=video_queue" in description
    assert "videoconvert" in description
    assert "video/x-raw,format=RGBA,pixel-aspect-ratio=1/1" in description
    assert "gtk4paintablesink name=sink" in description
    assert "videoscale" not in description
    assert "video/x-raw,width=300,height=400" not in description
    assert "render-rectangle" not in description


def test_gtk_compatible_pipeline_leaves_fit_to_gtk_picture() -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")

    description = worker._build_gtk_compatible_pipeline_description(
        "file:///movie.mov",
        300,
        400,
        force_software_decoders=False,
        fit_display=True,
    )

    assert "force-sw-decoders=true" not in description
    assert "video/x-raw,format=RGBA,pixel-aspect-ratio=1/1" in description
    assert "videoscale" not in description
    assert "video/x-raw,width=300,height=400" not in description
    assert "gtk4paintablesink name=sink" in description


def test_create_gtk_compatible_pipeline_sizes_gtk_widget_for_fullscreen(
    monkeypatch,
) -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker._ensure_gtk = MagicMock(return_value=MagicMock())
    worker._gtk_primary_monitor_geometry = MagicMock(return_value=(0, 0, 2560, 1440))
    worker._configure_gtk_paintable = MagicMock()
    worker._present_gtk_paintable_sink = MagicMock(return_value=True)
    sink = MagicMock()
    paintable = MagicMock()
    sink.get_property.return_value = paintable
    pipeline = MagicMock()
    pipeline.get_by_name.return_value = sink
    parse_launch = MagicMock(return_value=pipeline)
    monkeypatch.setattr(gst_worker.Gst, "parse_launch", parse_launch)

    result = worker._create_gtk_compatible_pipeline(
        "file:///movie.mov",
        0,
        0,
        0,
        0,
        force_software_decoders=True,
    )

    assert result is pipeline
    assert "videoscale" not in parse_launch.call_args.args[0]
    assert "video/x-raw,format=RGBA,pixel-aspect-ratio=1/1" in parse_launch.call_args.args[0]
    assert "video/x-raw,width=2560,height=1440" not in parse_launch.call_args.args[0]
    assert worker._present_gtk_paintable_sink.call_args.kwargs["set_sink_window_size"] is True
    assert worker._present_gtk_paintable_sink.call_args.kwargs["content_fit"] == "contain"


def test_create_gtk_compatible_pipeline_fills_fit_display_video(
    monkeypatch,
) -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker._ensure_gtk = MagicMock(return_value=MagicMock())
    worker._gtk_primary_monitor_geometry = MagicMock(return_value=(0, 0, 2560, 1440))
    worker._configure_gtk_paintable = MagicMock()
    worker._present_gtk_paintable_sink = MagicMock(return_value=True)
    sink = MagicMock()
    paintable = MagicMock()
    sink.get_property.return_value = paintable
    pipeline = MagicMock()
    pipeline.get_by_name.return_value = sink
    monkeypatch.setattr(gst_worker.Gst, "parse_launch", MagicMock(return_value=pipeline))

    result = worker._create_gtk_compatible_pipeline(
        "file:///movie.mov",
        0,
        0,
        2560,
        1440,
        force_software_decoders=True,
        fit_display=True,
    )

    assert result is pipeline
    assert "videoscale" not in gst_worker.Gst.parse_launch.call_args.args[0]
    assert (
        "video/x-raw,format=RGBA,pixel-aspect-ratio=1/1"
        in gst_worker.Gst.parse_launch.call_args.args[0]
    )
    assert worker._present_gtk_paintable_sink.call_args.kwargs["set_sink_window_size"] is True
    assert worker._present_gtk_paintable_sink.call_args.kwargs["content_fit"] == "fill"


def test_gtk_playbin_attempt_uses_only_pi_hardware_path() -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker._hardware_model = "Raspberry Pi 4 Model B Rev 1.2"

    assert worker._should_attempt_gtk_playbin(
        "waylandsink",
        0,
        0,
        2560,
        1440,
        force_software_decoders=False,
        pipeline_variant=PIPELINE_HARDWARE_DIRECT,
    )
    assert worker._should_attempt_gtk_playbin(
        "waylandsink",
        0,
        0,
        0,
        1440,
        force_software_decoders=False,
        pipeline_variant=PIPELINE_HARDWARE_DIRECT,
    )
    assert worker._should_attempt_gtk_playbin(
        "glimagesink",
        0,
        0,
        2560,
        1440,
        force_software_decoders=False,
        pipeline_variant=PIPELINE_HARDWARE_DIRECT,
    )
    assert not worker._should_attempt_gtk_playbin(
        "waylandsink",
        0,
        0,
        2560,
        1440,
        force_software_decoders=True,
        pipeline_variant=PIPELINE_HARDWARE_DIRECT,
    )
    worker._hardware_model = "Ubuntu VM"
    assert not worker._should_attempt_gtk_playbin(
        "waylandsink",
        0,
        0,
        2560,
        1440,
        force_software_decoders=False,
        pipeline_variant=PIPELINE_HARDWARE_DIRECT,
    )
    assert not worker._should_attempt_gtk_playbin(
        "waylandsink",
        0,
        0,
        2560,
        1440,
        force_software_decoders=True,
        pipeline_variant=PIPELINE_COMPATIBLE,
    )
    assert not worker._should_attempt_gtk_playbin(
        "waylandsink",
        0,
        0,
        2560,
        1440,
        force_software_decoders=True,
        pipeline_variant=PIPELINE_COMPATIBLE,
    )


def test_gtk_compatible_attempt_allows_ubuntu_vm_software_path() -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker._hardware_model = "Ubuntu VM"

    assert worker._should_attempt_gtk_compatible(
        "waylandsink",
        0,
        0,
        1920,
        1080,
        pipeline_variant=PIPELINE_COMPATIBLE,
    )
    assert not worker._should_attempt_gtk_compatible(
        "waylandsink",
        0,
        0,
        1920,
        1080,
        pipeline_variant=PIPELINE_HARDWARE_DIRECT,
    )
    assert worker._should_attempt_gtk_compatible(
        "glimagesink",
        0,
        0,
        1920,
        1080,
        pipeline_variant=PIPELINE_COMPATIBLE,
    )


def test_ensure_gtk_retries_after_transient_init_failure(monkeypatch) -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    fake_gtk = SimpleNamespace()
    fake_gdk = SimpleNamespace()
    init_gtk4 = MagicMock(
        side_effect=[
            RuntimeError("display not ready"),
            (fake_gtk, fake_gdk),
        ]
    )
    monkeypatch.setattr(worker, "_init_gtk4", init_gtk4)

    assert worker._ensure_gtk() is None
    assert "display not ready" in worker._gtk_presentation_failure

    assert worker._ensure_gtk() is fake_gtk
    assert worker._gdk is fake_gdk
    assert init_gtk4.call_count == 2


def test_initialize_gtk_supports_no_arg_init_check() -> None:
    fake_gtk = SimpleNamespace(init_check=MagicMock(return_value=True))

    GstWorker._initialize_gtk(fake_gtk)

    fake_gtk.init_check.assert_called_once_with()


def test_initialize_gtk_falls_back_to_legacy_init_check_argument() -> None:
    fake_gtk = SimpleNamespace(
        init_check=MagicMock(side_effect=[TypeError("old signature"), True])
    )

    GstWorker._initialize_gtk(fake_gtk)

    assert fake_gtk.init_check.call_count == 2
    assert fake_gtk.init_check.call_args_list[0].args == ()
    assert fake_gtk.init_check.call_args_list[1].args == ([],)


def test_gtk_geometry_is_fullscreen_for_origin_unset_or_monitor_size(
    monkeypatch,
) -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    monkeypatch.setattr(
        worker,
        "_gtk_primary_monitor_geometry",
        lambda: (0, 0, 2560, 1440),
    )

    assert worker._gtk_geometry_is_fullscreen(0, 0, 0, 0)
    assert worker._gtk_geometry_is_fullscreen(0, 0, 2560, 1440)
    assert not worker._gtk_geometry_is_fullscreen(0, 0, 300, 400)
    assert not worker._gtk_geometry_is_fullscreen(10, 0, 2560, 1440)


def test_gtk_window_geometry_uses_fullscreen_for_fullscreen_path() -> None:
    window = MagicMock()

    GstWorker._apply_gtk_window_geometry(
        window,
        0,
        0,
        2560,
        1440,
        fullscreen=True,
    )

    window.set_default_size.assert_called_once_with(2560, 1440)
    window.set_fullscreened.assert_called_once_with(True)
    window.fullscreen.assert_called_once_with()
    window.move.assert_not_called()
    window.resize.assert_not_called()


def test_gtk_window_geometry_sets_widget_size_for_fullscreen_path() -> None:
    window = MagicMock()
    widget = MagicMock()

    GstWorker._apply_gtk_window_geometry(
        window,
        0,
        0,
        2560,
        1440,
        fullscreen=True,
        widget=widget,
    )

    window.set_default_size.assert_called_once_with(2560, 1440)
    widget.set_size_request.assert_called_once_with(2560, 1440)
    window.set_fullscreened.assert_called_once_with(True)
    window.fullscreen.assert_called_once_with()


def test_gtk_window_geometry_sets_default_size_for_custom_path() -> None:
    window = MagicMock()

    GstWorker._apply_gtk_window_geometry(
        window,
        10,
        20,
        300,
        400,
        fullscreen=False,
    )

    window.set_default_size.assert_called_once_with(300, 400)
    window.resize.assert_not_called()
    window.move.assert_not_called()
    window.fullscreen.assert_not_called()


def test_gtk_window_geometry_sets_widget_size_for_custom_path() -> None:
    window = MagicMock()
    widget = MagicMock()

    GstWorker._apply_gtk_window_geometry(
        window,
        10,
        20,
        300,
        400,
        fullscreen=False,
        widget=widget,
    )

    widget.set_size_request.assert_called_once_with(300, 400)
    window.set_default_size.assert_called_once_with(300, 400)
    window.resize.assert_not_called()
    window.move.assert_not_called()
    window.fullscreen.assert_not_called()


def test_gtk_host_window_geometry_uses_fullscreen_monitor_host_for_custom_geometry(
    monkeypatch,
) -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    monkeypatch.setattr(
        worker,
        "_gtk_primary_monitor_geometry",
        lambda: (0, 0, 2560, 1440),
    )
    window = MagicMock()

    worker._apply_gtk_host_window_geometry(window, 100, 80, 1800, 1000)

    window.set_default_size.assert_called_once_with(2560, 1440)
    window.resize.assert_not_called()
    window.move.assert_not_called()
    window.set_fullscreened.assert_called_once_with(True)
    window.fullscreen.assert_called_once_with()


def test_configure_gtk_video_window_matches_poc_hints() -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    window = MagicMock()

    worker._configure_gtk_video_window(window)

    window.set_decorated.assert_called_once_with(False)
    window.set_titlebar.assert_not_called()
    window.set_app_paintable.assert_called_once_with(True)
    window.set_deletable.assert_called_once_with(False)
    window.set_resizable.assert_called_once_with(False)
    window.set_hide_on_close.assert_called_once_with(True)
    window.set_skip_taskbar_hint.assert_called_once_with(True)
    window.set_skip_pager_hint.assert_called_once_with(True)
    window.set_focusable.assert_called_once_with(True)
    window.set_can_focus.assert_called_once_with(True)
    window.set_focus_on_map.assert_called_once_with(True)
    window.set_accept_focus.assert_not_called()
    window.set_type_hint.assert_not_called()


def test_configure_gtk_video_window_disables_app_paintable_for_opaque_host() -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    window = MagicMock()

    worker._configure_gtk_video_window(window, transparent=False)

    window.set_decorated.assert_called_once_with(False)
    window.set_app_paintable.assert_called_once_with(False)


def test_present_gtk_video_window_sets_opacity_fullscreen_and_presents() -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker._pump_gtk_events = MagicMock()
    window = MagicMock()

    worker._present_gtk_video_window(window, fullscreen=True)

    window.set_opacity.assert_called_once_with(1.0)
    assert window.fullscreen.call_count == 2
    assert window.present.call_count >= 2
    window.grab_focus.assert_called()
    assert worker._pump_gtk_events.call_count == 2


def test_present_gtk_video_window_keeps_custom_geometry_unfullscreened() -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker._pump_gtk_events = MagicMock()
    window = MagicMock()

    worker._present_gtk_video_window(window, fullscreen=False)

    window.set_opacity.assert_called_once_with(1.0)
    window.fullscreen.assert_not_called()
    assert window.present.call_count >= 1
    window.grab_focus.assert_called()
    worker._pump_gtk_events.assert_called_once_with()


def test_present_gtk_video_window_can_start_hidden() -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker._pump_gtk_events = MagicMock()
    window = MagicMock()

    worker._present_gtk_video_window(
        window,
        fullscreen=True,
        opacity=gst_worker.STARTUP_GTK_WINDOW_OPACITY,
    )

    window.set_opacity.assert_called_once_with(gst_worker.STARTUP_GTK_WINDOW_OPACITY)
    window.fullscreen.assert_called()
    window.present.assert_called()


def test_gtk_video_host_uses_transparency_on_raspberry_pi(monkeypatch) -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker._hardware_model = "Raspberry Pi 4 Model B Rev 1.2"
    monkeypatch.setattr(worker, "_find_labwc_pid", MagicMock(return_value=None))

    assert worker._gtk_video_host_uses_transparency()
    worker._find_labwc_pid.assert_not_called()


def test_gtk_video_host_uses_transparency_on_labwc_env(monkeypatch) -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker._hardware_model = "Ubuntu VM"
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "labwc")
    monkeypatch.setattr(worker, "_find_labwc_pid", MagicMock(return_value=None))

    assert worker._gtk_video_host_uses_transparency()
    worker._find_labwc_pid.assert_not_called()


def test_gtk_video_host_uses_opaque_background_on_gnome_vm(monkeypatch) -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker._hardware_model = "Ubuntu VM"
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "GNOME")
    monkeypatch.setenv("DESKTOP_SESSION", "ubuntu")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setattr(worker, "_find_labwc_pid", MagicMock(return_value=None))

    assert not worker._gtk_video_host_uses_transparency()
    worker._find_labwc_pid.assert_called_once_with()


def test_set_gtk_video_host_background_can_make_configured_opaque_color() -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    display = object()
    css_provider = MagicMock()
    widget = MagicMock()

    class FakeGdk:
        Display = SimpleNamespace(get_default=MagicMock(return_value=display))

    class FakeGtk:
        CssProvider = MagicMock(return_value=css_provider)
        StyleContext = SimpleNamespace(add_provider_for_display=MagicMock())
        STYLE_PROVIDER_PRIORITY_APPLICATION = 600

    worker._gdk = FakeGdk
    worker._gtk = FakeGtk

    worker._set_gtk_video_host_background(
        widget,
        transparent=False,
        host_background=(0.2, 0.2, 0.3, 1.0),
    )

    css = css_provider.load_from_data.call_args.args[0].decode("utf-8")
    assert ".picframe-transparent-video-host" in css
    assert ".picframe-opaque-video-host" in css
    assert "rgba(51, 51, 76, 1)" in css
    widget.remove_css_class.assert_any_call("picframe-transparent-video-host")
    widget.remove_css_class.assert_any_call("picframe-opaque-video-host")
    widget.add_css_class.assert_called_once_with("picframe-opaque-video-host")


def test_set_gtk_video_host_background_defaults_invalid_opaque_color_to_black() -> None:
    assert GstWorker._gtk_opaque_host_background_css(None) == "rgba(0, 0, 0, 1)"
    assert GstWorker._gtk_opaque_host_background_css(object()) == "rgba(0, 0, 0, 1)"
    assert GstWorker._gtk_opaque_host_background_css(("bad", 0.2, 0.3)) == (
        "rgba(0, 0, 0, 1)"
    )


def test_gtk_opaque_host_background_css_clamps_channels() -> None:
    assert GstWorker._gtk_opaque_host_background_css((-1.0, 0.5, 2.0, 0.0)) == (
        "rgba(0, 128, 255, 1)"
    )


def test_set_gtk_video_host_background_can_make_transparent() -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    display = object()
    css_provider = MagicMock()
    widget = MagicMock()

    class FakeGdk:
        Display = SimpleNamespace(get_default=MagicMock(return_value=display))

    class FakeGtk:
        CssProvider = MagicMock(return_value=css_provider)
        StyleContext = SimpleNamespace(add_provider_for_display=MagicMock())
        STYLE_PROVIDER_PRIORITY_APPLICATION = 600

    worker._gdk = FakeGdk
    worker._gtk = FakeGtk

    worker._set_gtk_video_host_background(widget, transparent=True)

    css = css_provider.load_from_data.call_args.args[0].decode("utf-8")
    assert "rgba(0, 0, 0, 0)" in css
    widget.add_css_class.assert_called_once_with("picframe-transparent-video-host")


def test_create_gtk_fixed_video_host_places_widget_in_fullscreen_host(
    monkeypatch,
) -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    monkeypatch.setattr(
        worker,
        "_gtk_primary_monitor_geometry",
        lambda: (0, 0, 2560, 1440),
    )
    worker._set_gtk_video_host_background = MagicMock()

    class FakeGtk:
        Fixed = MagicMock(return_value=MagicMock())

    window = MagicMock()
    widget = MagicMock()

    host = worker._create_gtk_fixed_video_host(
        FakeGtk,
        window,
        widget,
        100,
        80,
        1800,
        1000,
    )

    FakeGtk.Fixed.assert_called_once_with()
    worker._set_gtk_video_host_background.assert_called_once_with(
        host,
        transparent=True,
        host_background=None,
    )
    widget.set_hexpand.assert_called_once_with(True)
    widget.set_vexpand.assert_called_once_with(True)
    widget.set_size_request.assert_called_once_with(1800, 1000)
    host.put.assert_called_once_with(widget, 100, 80)
    window.set_default_size.assert_called_once_with(2560, 1440)
    host.set_size_request.assert_called_once_with(2560, 1440)


def test_create_gtk_fixed_video_host_expands_fullscreen_request_to_monitor(
    monkeypatch,
) -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    monkeypatch.setattr(
        worker,
        "_gtk_primary_monitor_geometry",
        lambda: (0, 0, 2560, 1440),
    )
    worker._set_gtk_video_host_background = MagicMock()

    class FakeGtk:
        Fixed = MagicMock(return_value=MagicMock())

    window = MagicMock()
    widget = MagicMock()

    host = worker._create_gtk_fixed_video_host(
        FakeGtk,
        window,
        widget,
        0,
        0,
        0,
        0,
    )

    worker._set_gtk_video_host_background.assert_called_once_with(
        host,
        transparent=True,
        host_background=None,
    )
    widget.set_hexpand.assert_called_once_with(True)
    widget.set_vexpand.assert_called_once_with(True)
    widget.set_size_request.assert_called_once_with(2560, 1440)
    host.put.assert_called_once_with(widget, 0, 0)
    window.set_default_size.assert_called_once_with(2560, 1440)
    host.set_size_request.assert_called_once_with(2560, 1440)


def test_gtk_fixed_host_child_rect_removes_offset_for_opaque_fullscreen(
    monkeypatch,
) -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    monkeypatch.setattr(
        worker,
        "_gtk_video_host_geometry",
        lambda *args: (0, 0, 2560, 1440),
    )

    assert worker._gtk_fixed_host_child_rect(
        100,
        80,
        1800,
        1000,
        fullscreen=True,
        transparent=False,
    ) == (0, 0, 2560, 1440)
    assert worker._gtk_fixed_host_child_rect(
        100,
        80,
        1800,
        1000,
        fullscreen=True,
        transparent=True,
    ) == (100, 80, 1800, 1000)
    assert worker._gtk_fixed_host_child_rect(
        100,
        80,
        1800,
        1000,
        fullscreen=False,
        transparent=False,
    ) == (100, 80, 1800, 1000)


def test_present_gtk_paintable_uses_fullscreen_host_for_custom_geometry(
    monkeypatch,
) -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    window = MagicMock()
    widget = MagicMock()
    host = MagicMock()
    video_sink = MagicMock()

    class FakeGtk:
        Window = MagicMock(return_value=window)

    monkeypatch.setattr(worker, "_gtk_geometry_is_fullscreen", lambda *args: False)
    monkeypatch.setattr(worker, "_gtk_video_host_uses_transparency", lambda: False)
    monkeypatch.setattr(worker, "_create_gtk_video_picture", MagicMock(return_value=widget))
    fixed_host = MagicMock(return_value=host)
    monkeypatch.setattr(worker, "_create_gtk_fixed_video_host", fixed_host)
    apply_window_geometry = MagicMock()
    monkeypatch.setattr(worker, "_apply_gtk_window_geometry", apply_window_geometry)
    apply_host_geometry = MagicMock()
    monkeypatch.setattr(worker, "_apply_gtk_host_window_geometry", apply_host_geometry)
    monkeypatch.setattr(worker, "_configure_gtk_video_window", MagicMock())
    configure_background = MagicMock()
    monkeypatch.setattr(worker, "_configure_gtk_video_host_background", configure_background)
    monkeypatch.setattr(worker, "_present_gtk_video_window", MagicMock())
    monkeypatch.setattr(worker, "_log_gtk_window_diagnostics", MagicMock())
    monkeypatch.setattr(worker, "_hide_gtk_cursor", MagicMock())
    monkeypatch.setattr(worker, "_gtk_window_matches_geometry", lambda *args, **kwargs: True)
    monkeypatch.setattr(worker, "_start_gtk_pump", MagicMock())

    result = worker._present_gtk_paintable_sink(
        FakeGtk,
        video_sink,
        MagicMock(),
        10,
        20,
        300,
        400,
        set_sink_window_size=False,
        content_fit="fill",
        host_background=(0.2, 0.2, 0.3, 1.0),
    )

    assert result is True
    configure_background.assert_called_once_with(
        window,
        transparent=False,
        host_background=(0.2, 0.2, 0.3, 1.0),
    )
    fixed_host.assert_called_once_with(
        FakeGtk,
        window,
        widget,
        10,
        20,
        300,
        400,
        transparent=False,
        host_background=(0.2, 0.2, 0.3, 1.0),
    )
    window.set_child.assert_called_once_with(host)
    apply_host_geometry.assert_called_once_with(window, 10, 20, 300, 400)
    apply_window_geometry.assert_not_called()
    worker._present_gtk_video_window.assert_called_once_with(
        window,
        fullscreen=True,
        opacity=gst_worker.STARTUP_GTK_WINDOW_OPACITY,
    )


def test_present_gtk_paintable_keeps_window_when_geometry_confirmation_is_late(
    monkeypatch,
) -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    window = MagicMock()
    widget = MagicMock()
    host = MagicMock()
    video_sink = MagicMock()

    class FakeGtk:
        Window = MagicMock(return_value=window)

    monkeypatch.setattr(worker, "_gtk_geometry_is_fullscreen", lambda *args: False)
    monkeypatch.setattr(worker, "_gtk_video_host_uses_transparency", lambda: False)
    monkeypatch.setattr(worker, "_create_gtk_video_picture", MagicMock(return_value=widget))
    monkeypatch.setattr(worker, "_create_gtk_fixed_video_host", MagicMock(return_value=host))
    monkeypatch.setattr(worker, "_apply_gtk_host_window_geometry", MagicMock())
    monkeypatch.setattr(worker, "_configure_gtk_video_window", MagicMock())
    monkeypatch.setattr(worker, "_configure_gtk_video_host_background", MagicMock())
    monkeypatch.setattr(worker, "_present_gtk_video_window", MagicMock())
    monkeypatch.setattr(worker, "_log_gtk_window_diagnostics", MagicMock())
    monkeypatch.setattr(worker, "_hide_gtk_cursor", MagicMock())
    monkeypatch.setattr(worker, "_gtk_window_matches_geometry", lambda *args, **kwargs: False)
    monkeypatch.setattr(worker, "_start_gtk_pump", MagicMock())

    result = worker._present_gtk_paintable_sink(
        FakeGtk,
        video_sink,
        MagicMock(),
        10,
        20,
        300,
        400,
        set_sink_window_size=False,
        content_fit="contain",
    )

    assert result is True
    assert worker._gtk_window is window
    window.destroy.assert_not_called()


def test_present_gtk_paintable_uses_fullscreen_host_for_opaque_fullscreen(
    monkeypatch,
) -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    window = MagicMock()
    widget = MagicMock()
    host = MagicMock()
    video_sink = MagicMock()

    class FakeGtk:
        Window = MagicMock(return_value=window)

    monkeypatch.setattr(worker, "_gtk_geometry_is_fullscreen", lambda *args: True)
    monkeypatch.setattr(worker, "_gtk_video_host_uses_transparency", lambda: False)
    monkeypatch.setattr(worker, "_gtk_video_host_geometry", lambda *args: (0, 0, 1920, 1080))
    monkeypatch.setattr(worker, "_gtk_video_widget_geometry", lambda *args: (0, 0, 1920, 1080))
    monkeypatch.setattr(worker, "_create_gtk_video_picture", MagicMock(return_value=widget))
    fixed_host = MagicMock(return_value=host)
    monkeypatch.setattr(worker, "_create_gtk_fixed_video_host", fixed_host)
    apply_window_geometry = MagicMock()
    monkeypatch.setattr(worker, "_apply_gtk_window_geometry", apply_window_geometry)
    apply_host_geometry = MagicMock()
    monkeypatch.setattr(worker, "_apply_gtk_host_window_geometry", apply_host_geometry)
    configure_window = MagicMock()
    monkeypatch.setattr(worker, "_configure_gtk_video_window", configure_window)
    configure_background = MagicMock()
    monkeypatch.setattr(worker, "_configure_gtk_video_host_background", configure_background)
    monkeypatch.setattr(worker, "_present_gtk_video_window", MagicMock())
    monkeypatch.setattr(worker, "_log_gtk_window_diagnostics", MagicMock())
    monkeypatch.setattr(worker, "_hide_gtk_cursor", MagicMock())
    monkeypatch.setattr(worker, "_gtk_window_matches_geometry", lambda *args, **kwargs: True)
    monkeypatch.setattr(worker, "_start_gtk_pump", MagicMock())

    result = worker._present_gtk_paintable_sink(
        FakeGtk,
        video_sink,
        MagicMock(),
        0,
        0,
        0,
        0,
        set_sink_window_size=True,
        content_fit="fill",
    )

    assert result is True
    configure_window.assert_called_once_with(window, transparent=False)
    configure_background.assert_called_once_with(
        window,
        transparent=False,
        host_background=None,
    )
    fixed_host.assert_called_once_with(
        FakeGtk,
        window,
        widget,
        0,
        0,
        1920,
        1080,
        transparent=False,
        host_background=None,
    )
    window.set_child.assert_called_once_with(host)
    apply_host_geometry.assert_called_once_with(window, 0, 0, 0, 0)
    apply_window_geometry.assert_not_called()
    worker._present_gtk_video_window.assert_called_once_with(
        window,
        fullscreen=True,
        opacity=gst_worker.STARTUP_GTK_WINDOW_OPACITY,
    )


def test_present_gtk_paintable_keeps_direct_fullscreen_on_transparent_host(
    monkeypatch,
) -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    window = MagicMock()
    widget = MagicMock()
    video_sink = MagicMock()

    class FakeGtk:
        Window = MagicMock(return_value=window)

    monkeypatch.setattr(worker, "_gtk_geometry_is_fullscreen", lambda *args: True)
    monkeypatch.setattr(worker, "_gtk_video_host_uses_transparency", lambda: True)
    monkeypatch.setattr(worker, "_gtk_video_widget_geometry", lambda *args: (0, 0, 1920, 1080))
    monkeypatch.setattr(worker, "_create_gtk_video_picture", MagicMock(return_value=widget))
    fixed_host = MagicMock()
    monkeypatch.setattr(worker, "_create_gtk_fixed_video_host", fixed_host)
    apply_window_geometry = MagicMock()
    monkeypatch.setattr(worker, "_apply_gtk_window_geometry", apply_window_geometry)
    apply_host_geometry = MagicMock()
    monkeypatch.setattr(worker, "_apply_gtk_host_window_geometry", apply_host_geometry)
    configure_window = MagicMock()
    monkeypatch.setattr(worker, "_configure_gtk_video_window", configure_window)
    configure_background = MagicMock()
    monkeypatch.setattr(worker, "_configure_gtk_video_host_background", configure_background)
    monkeypatch.setattr(worker, "_present_gtk_video_window", MagicMock())
    monkeypatch.setattr(worker, "_log_gtk_window_diagnostics", MagicMock())
    monkeypatch.setattr(worker, "_hide_gtk_cursor", MagicMock())
    monkeypatch.setattr(worker, "_gtk_window_matches_geometry", lambda *args, **kwargs: True)
    monkeypatch.setattr(worker, "_start_gtk_pump", MagicMock())

    result = worker._present_gtk_paintable_sink(
        FakeGtk,
        video_sink,
        MagicMock(),
        0,
        0,
        0,
        0,
        set_sink_window_size=True,
        content_fit="fill",
    )

    assert result is True
    configure_window.assert_called_once_with(window, transparent=True)
    window.set_child.assert_called_once_with(widget)
    fixed_host.assert_not_called()
    apply_host_geometry.assert_not_called()
    apply_window_geometry.assert_called_once_with(
        window,
        0,
        0,
        0,
        0,
        fullscreen=True,
        widget=widget,
    )


def test_create_gtk_video_picture_uses_contain_by_default() -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    picture = MagicMock()

    class FakeGtk:
        ContentFit = SimpleNamespace(CONTAIN="contain", FILL="fill")
        Picture = SimpleNamespace(new_for_paintable=MagicMock(return_value=picture))

    result = worker._create_gtk_video_picture(FakeGtk, MagicMock())

    assert result is picture
    picture.set_content_fit.assert_called_once_with("contain")


def test_create_gtk_video_picture_can_fill_pre_shaped_frames() -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    picture = MagicMock()

    class FakeGtk:
        ContentFit = SimpleNamespace(CONTAIN="contain", FILL="fill")
        Picture = SimpleNamespace(new_for_paintable=MagicMock(return_value=picture))

    result = worker._create_gtk_video_picture(
        FakeGtk,
        MagicMock(),
        content_fit="fill",
    )

    assert result is picture
    picture.set_content_fit.assert_called_once_with("fill")


def test_create_gtk_video_picture_preserves_aspect_without_content_fit() -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    picture = MagicMock()

    class FakeGtk:
        Picture = SimpleNamespace(new_for_paintable=MagicMock(return_value=picture))

    result = worker._create_gtk_video_picture(FakeGtk, MagicMock())

    assert result is picture
    picture.set_keep_aspect_ratio.assert_called_once_with(True)


def test_create_gtk_playbin_pipeline_contains_non_fit_video(monkeypatch) -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    playbin = MagicMock()
    video_sink = MagicMock()
    audio_sink = MagicMock()
    paintable = MagicMock()
    video_sink.get_property.return_value = paintable

    def make_element(factory_name: str, name: str):
        assert (factory_name, name) in {
            ("playbin", "player"),
            ("gtk4paintablesink", "sink"),
            ("fakesink", "audiosink"),
        }
        return {
            "player": playbin,
            "sink": video_sink,
            "audiosink": audio_sink,
        }[name]

    monkeypatch.setattr(
        gst_worker,
        "Gst",
        SimpleNamespace(ElementFactory=SimpleNamespace(make=make_element)),
    )
    monkeypatch.setattr(worker, "_ensure_gtk", lambda: MagicMock())
    worker._configure_gtk_paintable = MagicMock()
    worker._present_gtk_paintable_sink = MagicMock(return_value=True)

    result = worker._create_gtk_playbin_pipeline(
        "file:///movie.mp4",
        0,
        0,
        960,
        540,
        fit_display=False,
    )

    assert result is playbin
    worker._present_gtk_paintable_sink.assert_called_once()
    assert worker._present_gtk_paintable_sink.call_args.kwargs["set_sink_window_size"] is True
    assert worker._present_gtk_paintable_sink.call_args.kwargs["content_fit"] == "contain"


def test_create_gtk_playbin_pipeline_fills_fit_display_video(monkeypatch) -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    playbin = MagicMock()
    video_sink = MagicMock()
    audio_sink = MagicMock()
    paintable = MagicMock()
    video_sink.get_property.return_value = paintable

    def make_element(factory_name: str, name: str):
        assert (factory_name, name) in {
            ("playbin", "player"),
            ("gtk4paintablesink", "sink"),
            ("fakesink", "audiosink"),
        }
        return {
            "player": playbin,
            "sink": video_sink,
            "audiosink": audio_sink,
        }[name]

    monkeypatch.setattr(
        gst_worker,
        "Gst",
        SimpleNamespace(ElementFactory=SimpleNamespace(make=make_element)),
    )
    monkeypatch.setattr(worker, "_ensure_gtk", lambda: MagicMock())
    worker._configure_gtk_paintable = MagicMock()
    worker._present_gtk_paintable_sink = MagicMock(return_value=True)

    result = worker._create_gtk_playbin_pipeline(
        "file:///movie.mp4",
        0,
        0,
        960,
        540,
        fit_display=True,
    )

    assert result is playbin
    worker._present_gtk_paintable_sink.assert_called_once()
    assert worker._present_gtk_paintable_sink.call_args.kwargs["set_sink_window_size"] is True
    assert worker._present_gtk_paintable_sink.call_args.kwargs["content_fit"] == "fill"


def test_configure_gtk_paintable_forces_aspect_ratio() -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    paintable = MagicMock()
    paintable.find_property.return_value = object()
    paintable.get_property.return_value = True

    worker._configure_gtk_paintable(paintable)

    paintable.set_property.assert_called_once_with("force-aspect-ratio", True)
    paintable.get_property.assert_called_once_with("force-aspect-ratio")


def test_gtk_window_matches_geometry_accepts_fullscreen_before_size_settles() -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker._pump_gtk_events = MagicMock()
    window = MagicMock()
    window.get_size.return_value = (640, 480)

    assert worker._gtk_window_matches_geometry(
        window,
        0,
        0,
        2560,
        1440,
        fullscreen=True,
    )
    worker._pump_gtk_events.assert_called_once_with()
    window.get_size.assert_not_called()
    window.get_position.assert_not_called()


def test_gtk_window_matches_geometry_accepts_non_fixed_custom_window() -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker._pump_gtk_events = MagicMock()
    window = MagicMock()
    window.get_size.return_value = (300, 400)
    window.get_position.return_value = (10, 20)

    assert worker._gtk_window_matches_geometry(
        window,
        10,
        20,
        300,
        400,
        fullscreen=False,
    )


def test_gtk_window_matches_geometry_accepts_fixed_host_child_geometry() -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker._pump_gtk_events = MagicMock()
    window = MagicMock()
    widget = MagicMock()
    allocation = SimpleNamespace(width=300, height=400)
    widget.get_allocation.return_value = allocation
    widget.translate_coordinates.return_value = (10, 20)

    assert worker._gtk_window_matches_geometry(
        window,
        10,
        20,
        300,
        400,
        fullscreen=False,
        widget=widget,
        fixed_host=True,
    )

    widget.translate_coordinates.return_value = (0, 0)

    assert not worker._gtk_window_matches_geometry(
        window,
        10,
        20,
        300,
        400,
        fullscreen=False,
        widget=widget,
        fixed_host=True,
    )


def test_gtk_window_matches_geometry_accepts_fixed_host_fullscreen_child(
    monkeypatch,
) -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker._pump_gtk_events = MagicMock()
    monkeypatch.setattr(
        worker,
        "_gtk_primary_monitor_geometry",
        lambda: (0, 0, 2560, 1440),
    )
    window = MagicMock()
    widget = MagicMock()
    allocation = SimpleNamespace(width=2560, height=1440)
    widget.get_allocation.return_value = allocation
    widget.translate_coordinates.return_value = (0, 0)

    assert worker._gtk_window_matches_geometry(
        window,
        0,
        0,
        0,
        0,
        fullscreen=True,
        widget=widget,
        fixed_host=True,
    )


def test_hide_gtk_cursor_uses_gtk4_cursor_name_on_widget_and_window() -> None:
    widget = MagicMock()
    window = MagicMock()

    worker = GstWorker("/tmp/picframe-test-gst.sock")

    worker._hide_gtk_cursor(window, widget)

    widget.set_cursor_from_name.assert_called_once_with("none")
    window.set_cursor_from_name.assert_called_once_with("none")


def test_hide_gtk_cursor_tolerates_missing_cursor_api() -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker._gdk = SimpleNamespace()

    worker._hide_gtk_cursor(MagicMock(), MagicMock())


def test_on_eos_dims_gtk_window_before_sending_event() -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker.conn = MagicMock()
    worker.conn.closed = False
    worker.pipeline = MagicMock()
    worker._gtk_window = MagicMock()
    worker._pump_gtk_events = MagicMock()
    worker._last_sample_diagnostics = MagicMock(
        return_value=(1.25, 0.04, "video/x-raw(memory:DMABuf)")
    )
    eos_order = []
    worker._gtk_window.set_opacity.side_effect = lambda value: eos_order.append(
        ("opacity", value)
    )
    worker.conn.send.side_effect = lambda payload: eos_order.append(
        ("send", json.loads(payload)["type"])
    )

    worker._on_eos(MagicMock(), MagicMock())

    worker.pipeline.set_state.assert_called_once_with(gst_worker.Gst.State.PAUSED)
    worker._gtk_window.set_opacity.assert_called_once_with(gst_worker.EOS_GTK_WINDOW_OPACITY)
    worker._pump_gtk_events.assert_called_once_with()
    assert eos_order == [
        ("opacity", gst_worker.EOS_GTK_WINDOW_OPACITY),
        ("send", "eos"),
    ]
    sent_event = json.loads(worker.conn.send.call_args[0][0])
    assert sent_event["type"] == "eos"
    assert sent_event["last_sample_pts_seconds"] == 1.25
    assert sent_event["last_sample_duration_seconds"] == 0.04
    assert sent_event["last_sample_caps"] == "video/x-raw(memory:DMABuf)"


def test_on_eos_without_gtk_window_sends_event() -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker.conn = MagicMock()
    worker.conn.closed = False
    worker.pipeline = MagicMock()
    worker._gtk_window = None
    worker._pump_gtk_events = MagicMock()
    worker._last_sample_diagnostics = MagicMock(return_value=(None, None, None))

    worker._on_eos(MagicMock(), MagicMock())

    worker.pipeline.set_state.assert_not_called()
    worker._pump_gtk_events.assert_not_called()
    sent_event = json.loads(worker.conn.send.call_args[0][0])
    assert sent_event["type"] == "eos"


def test_handle_stop_still_tears_down_pipeline_and_gtk_window() -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    pipeline = MagicMock()
    bus = MagicMock()
    worker.pipeline = pipeline
    worker.bus = bus
    worker._destroy_gtk_video_window = MagicMock()

    worker._handle_stop()

    pipeline.set_state.assert_called_once_with(gst_worker.Gst.State.NULL)
    bus.remove_signal_watch.assert_called_once_with()
    assert worker.pipeline is None
    assert worker.bus is None
    worker._destroy_gtk_video_window.assert_called_once_with()


class FakePipeline:
    def __init__(self) -> None:
        self.properties = {}
        self.bus = MagicMock()

    def set_property(self, key: str, value) -> None:
        self.properties[key] = value

    def get_bus(self):
        return self.bus

    def set_state(self, state):
        return gst_worker.Gst.StateChangeReturn.SUCCESS


class FakeSinkStats:
    def __init__(self, rendered: int) -> None:
        self.rendered = rendered

    def get_value(self, key: str) -> int:
        assert key == "rendered"
        return self.rendered


def test_async_done_waits_for_sink_rendered_stats_before_first_frame_event(
    monkeypatch,
) -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker.conn = MagicMock()
    worker.conn.closed = False
    stats = FakeSinkStats(rendered=0)
    worker._gtk_window = MagicMock()
    worker._pump_gtk_events = MagicMock()
    sink = MagicMock()
    sink.get_property.return_value = stats
    pipeline = MagicMock()
    pipeline.get_by_name.return_value = sink
    worker.pipeline = pipeline
    timeout_add = MagicMock(return_value=123)
    monkeypatch.setattr(gst_worker.GLib, "timeout_add", timeout_add)
    reveal_order = []
    worker._gtk_window.set_opacity.side_effect = lambda value: reveal_order.append(
        ("opacity", value)
    )
    worker.conn.send.side_effect = lambda payload: reveal_order.append(
        ("send", json.loads(payload)["type"])
    )

    worker._on_async_done(MagicMock(), MagicMock())

    pipeline.set_state.assert_called_once_with(gst_worker.Gst.State.PLAYING)
    timeout_add.assert_called_once()
    assert timeout_add.call_args.args[0] == gst_worker.FIRST_FRAME_PROBE_INTERVAL_MS
    assert callable(timeout_add.call_args.args[1])
    worker.conn.send.assert_not_called()
    assert worker._first_frame_probe_source_id == 123

    stats.rendered = 1

    assert worker._first_frame_probe_tick() is False
    sent_event = json.loads(worker.conn.send.call_args.args[0])
    assert sent_event["type"] == "first_frame_rendered"
    assert reveal_order == [
        ("opacity", 1.0),
        ("send", "first_frame_rendered"),
    ]
    assert worker._first_frame_event_sent is True
    assert worker._first_frame_probe_source_id is None


def test_async_done_accepts_first_frame_when_sink_stats_are_unavailable(
    monkeypatch,
) -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker.conn = MagicMock()
    worker.conn.closed = False
    worker._gtk_window = MagicMock()
    worker._pump_gtk_events = MagicMock()
    sink = MagicMock()
    sink.get_property.side_effect = AttributeError("no stats")
    pipeline = MagicMock()
    pipeline.get_by_name.return_value = sink
    worker.pipeline = pipeline
    timeout_add = MagicMock()
    monkeypatch.setattr(gst_worker.GLib, "timeout_add", timeout_add)

    worker._on_async_done(MagicMock(), MagicMock())

    sent_event = json.loads(worker.conn.send.call_args.args[0])
    assert sent_event["type"] == "first_frame_rendered"
    worker._gtk_window.set_opacity.assert_called_once_with(1.0)
    timeout_add.assert_not_called()


def test_start_pipeline_uses_gtk_playbin_when_geometry_is_valid(monkeypatch) -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    fake_pipeline = FakePipeline()
    diagnostics = MagicMock()

    monkeypatch.setattr(worker, "_select_sink_name", lambda: "waylandsink")
    monkeypatch.setattr(worker, "_gtk_paintable_sink_available", lambda: True)
    monkeypatch.setattr(
        worker,
        "_select_playback_decision",
        lambda *args, **kwargs: PlaybackDecision(
            pipeline_variant=PIPELINE_HARDWARE_DIRECT,
            force_software_decoders=False,
            decision="hardware_direct",
        ),
    )
    monkeypatch.setattr(worker, "_should_attempt_gtk_playbin", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        worker,
        "_create_gtk_playbin_pipeline",
        lambda *args, **kwargs: fake_pipeline,
    )
    monkeypatch.setattr(worker, "_connect_pipeline_telemetry_hooks", lambda: None)
    monkeypatch.setattr(worker, "_send_video_diagnostics", diagnostics)

    worker._start_pipeline(
        "file:///movie.mp4",
        10,
        20,
        300,
        400,
        force_software_decoders=False,
        stream_facts=h264_facts(1920, 1080),
    )

    assert worker.pipeline is fake_pipeline
    assert worker._current_pipeline_variant == PIPELINE_GTK_PLAYBIN
    assert worker._current_sink_name == "gtk4paintablesink"
    assert fake_pipeline.properties["volume"] == 1.0
    assert diagnostics.call_count >= 2


def test_start_pipeline_uses_gtk_compatible_for_ubuntu_vm_software(
    monkeypatch,
) -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker._hardware_model = "Ubuntu VM"
    fake_pipeline = FakePipeline()
    diagnostics = MagicMock()
    gtk_playbin = MagicMock(return_value=FakePipeline())
    gtk_compatible = MagicMock(return_value=fake_pipeline)

    monkeypatch.setattr(worker, "_select_sink_name", lambda: "waylandsink")
    monkeypatch.setattr(worker, "_gtk_paintable_sink_available", lambda: True)
    monkeypatch.setattr(
        gst_worker,
        "find_best_element",
        lambda names: "gtk4paintablesink" if "gtk4paintablesink" in names else None,
    )
    monkeypatch.setattr(
        worker,
        "_select_playback_decision",
        lambda *args, **kwargs: PlaybackDecision(
            pipeline_variant=PIPELINE_COMPATIBLE,
            force_software_decoders=True,
            decision="software_fallback",
            fallback_reason="hardware_decoder_unavailable",
        ),
    )
    monkeypatch.setattr(worker, "_create_gtk_playbin_pipeline", gtk_playbin)
    monkeypatch.setattr(
        worker,
        "_create_gtk_compatible_pipeline",
        gtk_compatible,
    )
    monkeypatch.setattr(worker, "_connect_pipeline_telemetry_hooks", lambda: None)
    monkeypatch.setattr(worker, "_send_video_diagnostics", diagnostics)

    worker._start_pipeline(
        "file:///movie.mp4",
        0,
        0,
        1920,
        1080,
        force_software_decoders=False,
        stream_facts=h264_facts(1920, 1080),
    )

    gtk_playbin.assert_not_called()
    gtk_compatible.assert_called_once_with(
        "file:///movie.mp4",
        0,
        0,
        1920,
        1080,
        force_software_decoders=True,
        fit_display=False,
        host_background=None,
    )
    assert worker.pipeline is fake_pipeline
    assert worker._current_pipeline_variant == PIPELINE_GTK_COMPATIBLE
    assert worker._current_sink_name == "gtk4paintablesink"
    assert fake_pipeline.properties["volume"] == 1.0
    assert diagnostics.call_count >= 2


def test_start_pipeline_tries_gtk_compatible_when_gtk_playbin_fails(
    monkeypatch,
) -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    fake_pipeline = FakePipeline()
    gtk_compatible = MagicMock(return_value=fake_pipeline)

    monkeypatch.setattr(worker, "_select_sink_name", lambda: "waylandsink")
    monkeypatch.setattr(worker, "_gtk_paintable_sink_available", lambda: True)
    monkeypatch.setattr(
        worker,
        "_select_playback_decision",
        lambda *args, **kwargs: PlaybackDecision(
            pipeline_variant=PIPELINE_HARDWARE_DIRECT,
            force_software_decoders=False,
            decision="hardware_direct",
        ),
    )
    monkeypatch.setattr(worker, "_should_attempt_gtk_playbin", lambda *args, **kwargs: True)
    monkeypatch.setattr(worker, "_create_gtk_playbin_pipeline", MagicMock(return_value=None))
    monkeypatch.setattr(worker, "_should_attempt_gtk_compatible", lambda *args, **kwargs: True)
    monkeypatch.setattr(worker, "_create_gtk_compatible_pipeline", gtk_compatible)
    monkeypatch.setattr(worker, "_connect_pipeline_telemetry_hooks", lambda: None)
    monkeypatch.setattr(worker, "_send_video_diagnostics", lambda *args, **kwargs: None)

    worker._start_pipeline(
        "file:///movie.mp4",
        10,
        20,
        300,
        400,
        force_software_decoders=False,
        stream_facts=h264_facts(1920, 1080),
    )

    assert worker.pipeline is fake_pipeline
    assert worker._current_pipeline_variant == PIPELINE_GTK_COMPATIBLE
    assert worker._current_sink_name == "gtk4paintablesink"
    gtk_compatible.assert_called_once_with(
        "file:///movie.mp4",
        10,
        20,
        300,
        400,
        force_software_decoders=False,
        fit_display=False,
        host_background=None,
    )


def test_start_pipeline_reports_error_when_required_gtk_geometry_is_not_confirmed(
    monkeypatch,
) -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    conn = MagicMock()
    conn.closed = False
    worker.conn = conn
    parse_launch = MagicMock()

    monkeypatch.setattr(worker, "_select_sink_name", lambda: "waylandsink")
    monkeypatch.setattr(worker, "_gtk_paintable_sink_available", lambda: True)
    monkeypatch.setattr(
        worker,
        "_select_playback_decision",
        lambda *args, **kwargs: PlaybackDecision(
            pipeline_variant=PIPELINE_HARDWARE_DIRECT,
            force_software_decoders=False,
            decision="hardware_direct",
        ),
    )
    monkeypatch.setattr(worker, "_should_attempt_gtk_playbin", lambda *args, **kwargs: True)

    def fail_gtk_playbin(*args, **kwargs):
        worker._gtk_presentation_failure = "GTK4 initialization failed: display not ready"
        return None

    monkeypatch.setattr(
        worker,
        "_create_gtk_playbin_pipeline",
        fail_gtk_playbin,
    )
    monkeypatch.setattr(worker, "_should_attempt_gtk_compatible", lambda *args, **kwargs: False)
    monkeypatch.setattr(worker, "_connect_pipeline_telemetry_hooks", lambda: None)
    monkeypatch.setattr(worker, "_send_video_diagnostics", lambda *args, **kwargs: None)
    monkeypatch.setattr(gst_worker.Gst, "parse_launch", parse_launch)

    worker._start_pipeline(
        "file:///movie.mp4",
        10,
        20,
        300,
        400,
        force_software_decoders=False,
        stream_facts=h264_facts(1920, 1080),
    )

    assert worker.pipeline is None
    parse_launch.assert_not_called()
    sent_event = json.loads(conn.send.call_args.args[0])
    assert sent_event["type"] == "error"
    assert sent_event["code"] == GTK_PRESENTATION_UNAVAILABLE_CODE
    assert "GTK4 video presentation is required" in sent_event["details"]
    assert "display not ready" in sent_event["details"]


def test_start_pipeline_reports_error_when_gtk4_sink_is_missing(monkeypatch) -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    conn = MagicMock()
    conn.closed = False
    worker.conn = conn
    parse_launch = MagicMock()

    monkeypatch.setattr(worker, "_select_sink_name", lambda: "waylandsink")
    monkeypatch.setattr(worker, "_gtk_paintable_sink_available", lambda: False)
    monkeypatch.setattr(
        worker,
        "_select_playback_decision",
        lambda *args, **kwargs: PlaybackDecision(
            pipeline_variant=PIPELINE_COMPATIBLE,
            force_software_decoders=True,
            decision="software_fallback",
        ),
    )
    monkeypatch.setattr(gst_worker.Gst, "parse_launch", parse_launch)

    worker._start_pipeline(
        "file:///movie.mp4",
        0,
        0,
        1920,
        1080,
        force_software_decoders=False,
        stream_facts=h264_facts(1920, 1080),
    )

    assert worker.pipeline is None
    parse_launch.assert_not_called()
    sent_event = json.loads(conn.send.call_args.args[0])
    assert sent_event["type"] == "error"
    assert sent_event["code"] == GTK_PRESENTATION_UNAVAILABLE_CODE
    assert "gtk4paintablesink element is not installed" in sent_event["details"]


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


def test_pi_h265_main10_skips_when_hardware_decoder_is_unavailable(
    monkeypatch,
) -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker._hardware_model = "Raspberry Pi 4 Model B Rev 1.2"
    monkeypatch.setattr(gst_worker, "find_best_element", lambda names: None)

    decision = worker._select_playback_decision(
        "file:///IMG_0103.MOV",
        "waylandsink",
        force_software_decoders=False,
        max_software_decode_resolution="1920x1080",
        stream_facts=h265_main10_facts(1920, 1080),
    )

    assert decision.pipeline_variant == PIPELINE_SKIPPED
    assert decision.force_software_decoders is False
    assert decision.decision == "skip"
    assert decision.fallback_reason == "hardware_decoder_unavailable"
    assert decision.error_code == "unsupported_media"


def test_pi_h265_main10_forced_software_decode_is_still_skipped() -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker._hardware_model = "Raspberry Pi 4 Model B Rev 1.2"

    decision = worker._select_playback_decision(
        "file:///IMG_0103.MOV",
        "waylandsink",
        force_software_decoders=True,
        max_software_decode_resolution="1920x1080",
        stream_facts=h265_main10_facts(1920, 1080),
        fallback_reason="software_fallback",
    )

    assert decision.pipeline_variant == PIPELINE_SKIPPED
    assert decision.force_software_decoders is False
    assert decision.decision == "skip"
    assert decision.fallback_reason == "software_fallback"
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


def test_ubuntu_vm_h265_main10_uses_software_fallback_when_within_limit() -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker._hardware_model = "Ubuntu VM"
    worker._hardware_decode_available_for_facts = lambda stream_facts: False

    decision = worker._select_playback_decision(
        "file:///IMG_0103.MOV",
        "waylandsink",
        force_software_decoders=False,
        max_software_decode_resolution="1920x1080",
        stream_facts=h265_main10_facts(1920, 1080),
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
    worker._current_play_request = PlayRequest("file:///movie.mov", 1, 2, 300, 400, False)
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
        fit_display=False,
        host_background=None,
    )
    sent_event = json.loads(worker.conn.send.call_args[0][0])
    assert sent_event["type"] == "warning"
    assert sent_event["warning_type"] == "software_fallback"
    assert sent_event["decoder"] == "force-sw-decoders"


def test_pi_hardware_only_stream_does_not_retry_with_software_decode() -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker._hardware_model = "Raspberry Pi 4 Model B Rev 1.2"
    worker.conn = MagicMock()
    worker.conn.closed = False
    worker._current_play_request = PlayRequest("file:///IMG_0103.MOV", 1, 2, 300, 400, False)
    worker._current_stream_facts = h265_main10_facts(1920, 1080)
    worker._start_pipeline = MagicMock()
    worker._handle_stop = MagicMock()

    worker._on_error(
        MagicMock(),
        FakeGstErrorMessage(
            "Internal data stream error.",
            "streaming stopped, reason not-negotiated (-4)",
        ),
    )

    worker._start_pipeline.assert_not_called()
    sent_event = json.loads(worker.conn.send.call_args[0][0])
    assert sent_event["type"] == "error"
    assert sent_event["details"] == "Internal data stream error."
    worker._handle_stop.assert_called_once()


def test_hardware_direct_error_retries_compatible_pipeline_first() -> None:
    worker = GstWorker("/tmp/picframe-test-gst.sock")
    worker.conn = MagicMock()
    worker.conn.closed = False
    worker._current_play_request = PlayRequest("file:///movie.mov", 1, 2, 300, 400, False)
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
        fit_display=False,
        host_background=None,
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
    worker._current_play_request = PlayRequest("file:///movie.mov", 1, 2, 300, 400, False)
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
