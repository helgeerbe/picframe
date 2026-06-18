from types import SimpleNamespace
from unittest.mock import MagicMock

from picframe.core.renderers.gst_pipeline_builder import GstPipelineBuilder


def make_builder():
    presenter = MagicMock()
    presenter._ensure_gtk.return_value = MagicMock()
    presenter.video_widget_geometry.return_value = (0, 0, 1920, 1080)
    presenter.present_paintable.return_value = True
    gst = SimpleNamespace()
    return GstPipelineBuilder(gst, presenter), gst, presenter


def test_gtk_compatible_pipeline_description_forces_rgba_without_size_caps() -> None:
    builder, _gst, _presenter = make_builder()

    description = builder.build_gtk_compatible_pipeline_description(
        "file:///movie.mp4",
        1920,
        1080,
        force_software_decoders=True,
    )

    assert "force-sw-decoders=true" in description
    assert "videoconvert" in description
    assert "video/x-raw,format=RGBA,pixel-aspect-ratio=1/1" in description
    assert "gtk4paintablesink name=sink" in description
    assert "videoscale" not in description
    assert "width=" not in description
    assert "height=" not in description
    assert "render-rectangle" not in description


def test_build_gtk_playbin_pipeline_presents_paintable_with_contain() -> None:
    builder, gst, presenter = make_builder()
    playbin = MagicMock()
    video_sink = MagicMock()
    audio_sink = MagicMock()
    paintable = MagicMock()
    video_sink.get_property.return_value = paintable

    def make_element(factory_name: str, name: str):
        return {
            "player": playbin,
            "sink": video_sink,
            "audiosink": audio_sink,
        }[name]

    gst.ElementFactory = SimpleNamespace(make=make_element)

    result = builder.build_gtk_playbin_pipeline(
        "file:///movie.mp4",
        0,
        0,
        960,
        540,
        fit_display=False,
    )

    assert result is playbin
    presenter._set_property_if_supported.assert_any_call(audio_sink, "sync", False)
    presenter._set_property_if_supported.assert_any_call(
        video_sink,
        "show-preroll-frame",
        True,
    )
    presenter._configure_gtk_paintable.assert_called_once_with(paintable)
    presenter.present_paintable.assert_called_once()
    assert presenter.present_paintable.call_args.kwargs["content_fit"] == "contain"
    assert presenter.present_paintable.call_args.kwargs["set_sink_window_size"] is True


def test_build_gtk_playbin_pipeline_fills_fit_display_video() -> None:
    builder, gst, presenter = make_builder()
    playbin = MagicMock()
    video_sink = MagicMock()
    audio_sink = MagicMock()
    video_sink.get_property.return_value = MagicMock()

    gst.ElementFactory = SimpleNamespace(
        make=lambda _factory_name, name: {
            "player": playbin,
            "sink": video_sink,
            "audiosink": audio_sink,
        }[name]
    )

    assert (
        builder.build_gtk_playbin_pipeline(
            "file:///movie.mp4",
            0,
            0,
            960,
            540,
            fit_display=True,
        )
        is playbin
    )
    assert presenter.present_paintable.call_args.kwargs["content_fit"] == "fill"


def test_build_gtk_playbin_pipeline_keeps_contain_with_host_backdrop() -> None:
    builder, gst, presenter = make_builder()
    playbin = MagicMock()
    video_sink = MagicMock()
    audio_sink = MagicMock()
    video_sink.get_property.return_value = MagicMock()

    gst.ElementFactory = SimpleNamespace(
        make=lambda _factory_name, name: {
            "player": playbin,
            "sink": video_sink,
            "audiosink": audio_sink,
        }[name]
    )

    assert (
        builder.build_gtk_playbin_pipeline(
            "file:///movie.mp4",
            0,
            0,
            960,
            540,
            fit_display=False,
            host_backdrop_path="/cache/video.1.frame",
        )
        is playbin
    )
    assert presenter.present_paintable.call_args.kwargs["content_fit"] == "contain"


def test_build_gtk_playbin_pipeline_uses_explicit_content_fit() -> None:
    builder, gst, presenter = make_builder()
    playbin = MagicMock()
    video_sink = MagicMock()
    audio_sink = MagicMock()
    video_sink.get_property.return_value = MagicMock()

    gst.ElementFactory = SimpleNamespace(
        make=lambda _factory_name, name: {
            "player": playbin,
            "sink": video_sink,
            "audiosink": audio_sink,
        }[name]
    )

    assert (
        builder.build_gtk_playbin_pipeline(
            "file:///movie.mp4",
            0,
            0,
            960,
            540,
            fit_display=False,
            host_backdrop_path="/cache/video.1.frame",
            content_fit="fill",
        )
        is playbin
    )
    assert presenter.present_paintable.call_args.kwargs["content_fit"] == "fill"


def test_build_gtk_compatible_pipeline_uses_widget_geometry_and_presenter() -> None:
    builder, gst, presenter = make_builder()
    pipeline = MagicMock()
    video_sink = MagicMock()
    paintable = MagicMock()
    video_sink.get_property.return_value = paintable
    pipeline.get_by_name.return_value = video_sink
    gst.parse_launch = MagicMock(return_value=pipeline)

    result = builder.build_gtk_compatible_pipeline(
        "file:///movie.mp4",
        100,
        80,
        1800,
        1000,
        force_software_decoders=True,
        fit_display=True,
        host_background=(0.2, 0.2, 0.3, 1.0),
        host_backdrop_path="/cache/video.1.frame",
        host_backdrop_rect=(10, 20, 1800, 1000),
    )

    assert result is pipeline
    presenter.video_widget_geometry.assert_called_once_with(100, 80, 1800, 1000)
    description = gst.parse_launch.call_args.args[0]
    assert "force-sw-decoders=true" in description
    presenter._set_property_if_supported.assert_called_with(
        video_sink,
        "show-preroll-frame",
        True,
    )
    presenter._configure_gtk_paintable.assert_called_once_with(paintable)
    presenter.present_paintable.assert_called_once()
    assert presenter.present_paintable.call_args.kwargs["content_fit"] == "fill"
    assert presenter.present_paintable.call_args.kwargs["host_background"] == (
        0.2,
        0.2,
        0.3,
        1.0,
    )
    assert presenter.present_paintable.call_args.kwargs["host_backdrop_path"] == (
        "/cache/video.1.frame"
    )
    assert presenter.present_paintable.call_args.kwargs["host_backdrop_rect"] == (
        10,
        20,
        1800,
        1000,
    )


def test_build_gtk_compatible_pipeline_keeps_contain_with_host_backdrop() -> None:
    builder, gst, presenter = make_builder()
    pipeline = MagicMock()
    video_sink = MagicMock()
    video_sink.get_property.return_value = MagicMock()
    pipeline.get_by_name.return_value = video_sink
    gst.parse_launch = MagicMock(return_value=pipeline)

    assert (
        builder.build_gtk_compatible_pipeline(
            "file:///movie.mp4",
            0,
            0,
            960,
            540,
            force_software_decoders=False,
            fit_display=False,
            host_backdrop_path="/cache/video.1.frame",
        )
        is pipeline
    )
    assert presenter.present_paintable.call_args.kwargs["content_fit"] == "contain"


def test_build_gtk_compatible_pipeline_uses_explicit_content_fit() -> None:
    builder, gst, presenter = make_builder()
    pipeline = MagicMock()
    video_sink = MagicMock()
    video_sink.get_property.return_value = MagicMock()
    pipeline.get_by_name.return_value = video_sink
    gst.parse_launch = MagicMock(return_value=pipeline)

    assert (
        builder.build_gtk_compatible_pipeline(
            "file:///movie.mp4",
            0,
            0,
            960,
            540,
            force_software_decoders=False,
            fit_display=False,
            host_backdrop_path="/cache/video.1.frame",
            content_fit="fill",
        )
        is pipeline
    )
    assert presenter.present_paintable.call_args.kwargs["content_fit"] == "fill"


def test_build_gtk_compatible_pipeline_records_paintable_failure() -> None:
    builder, gst, _presenter = make_builder()
    pipeline = MagicMock()
    video_sink = MagicMock()
    video_sink.get_property.return_value = None
    pipeline.get_by_name.return_value = video_sink
    gst.parse_launch = MagicMock(return_value=pipeline)

    result = builder.build_gtk_compatible_pipeline(
        "file:///movie.mp4",
        0,
        0,
        1920,
        1080,
        force_software_decoders=False,
    )

    assert result is None
    assert builder.last_failure == "gtk4paintablesink did not provide a paintable"
