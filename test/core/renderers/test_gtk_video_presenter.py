from types import SimpleNamespace
from unittest.mock import MagicMock

from picframe.core.renderers.gtk_video_presenter import (
    EOS_GTK_WINDOW_OPACITY,
    STARTUP_GTK_WINDOW_OPACITY,
    GtkVideoPresenter,
)


def make_presenter(hardware_model: str = "Ubuntu VM") -> GtkVideoPresenter:
    context = MagicMock()
    context.pending.return_value = False
    glib = SimpleNamespace(
        MainContext=SimpleNamespace(default=MagicMock(return_value=context)),
        timeout_add=MagicMock(return_value=123),
        source_remove=MagicMock(),
    )
    gst = SimpleNamespace(State=SimpleNamespace(PAUSED="paused"))
    gi_module = SimpleNamespace(require_version=MagicMock())
    return GtkVideoPresenter(
        hardware_model,
        gst,
        glib,
        gi_module,
        gst_available=True,
    )


def test_ensure_gtk_retries_after_transient_init_failure(monkeypatch) -> None:
    presenter = make_presenter()
    fake_gtk = SimpleNamespace()
    fake_gdk = SimpleNamespace()
    init_gtk4 = MagicMock(
        side_effect=[
            RuntimeError("display not ready"),
            (fake_gtk, fake_gdk),
        ]
    )
    monkeypatch.setattr(presenter, "_init_gtk4", init_gtk4)

    assert presenter._ensure_gtk() is None
    assert "display not ready" in presenter.last_failure

    assert presenter._ensure_gtk() is fake_gtk
    assert presenter.gdk is fake_gdk
    assert init_gtk4.call_count == 2


def test_initialize_gtk_falls_back_to_legacy_init_check_argument() -> None:
    fake_gtk = SimpleNamespace(
        init_check=MagicMock(side_effect=[TypeError("old signature"), True])
    )

    GtkVideoPresenter._initialize_gtk(fake_gtk)

    assert fake_gtk.init_check.call_count == 2
    assert fake_gtk.init_check.call_args_list[0].args == ()
    assert fake_gtk.init_check.call_args_list[1].args == ([],)


def test_gtk_geometry_is_fullscreen_for_origin_unset_or_monitor_size(
    monkeypatch,
) -> None:
    presenter = make_presenter()
    monkeypatch.setattr(
        presenter,
        "_gtk_primary_monitor_geometry",
        lambda: (0, 0, 2560, 1440),
    )

    assert presenter._gtk_geometry_is_fullscreen(0, 0, 0, 0)
    assert presenter._gtk_geometry_is_fullscreen(0, 0, 2560, 1440)
    assert not presenter._gtk_geometry_is_fullscreen(0, 0, 300, 400)
    assert not presenter._gtk_geometry_is_fullscreen(10, 0, 2560, 1440)


def test_gtk_window_geometry_sets_expected_fullscreen_and_custom_hints() -> None:
    fullscreen_window = MagicMock()
    custom_window = MagicMock()
    widget = MagicMock()

    GtkVideoPresenter._apply_gtk_window_geometry(
        fullscreen_window,
        0,
        0,
        2560,
        1440,
        fullscreen=True,
        widget=widget,
    )
    GtkVideoPresenter._apply_gtk_window_geometry(
        custom_window,
        10,
        20,
        300,
        400,
        fullscreen=False,
        widget=widget,
    )

    fullscreen_window.set_default_size.assert_called_once_with(2560, 1440)
    fullscreen_window.set_fullscreened.assert_called_once_with(True)
    fullscreen_window.fullscreen.assert_called_once_with()
    widget.set_size_request.assert_any_call(2560, 1440)
    widget.set_size_request.assert_any_call(300, 400)
    custom_window.set_default_size.assert_called_once_with(300, 400)
    custom_window.fullscreen.assert_not_called()


def test_present_gtk_video_window_sets_opacity_and_presents() -> None:
    presenter = make_presenter()
    presenter._pump_gtk_events = MagicMock()
    window = MagicMock()

    presenter._present_gtk_video_window(window, fullscreen=True)

    window.set_opacity.assert_called_once_with(1.0)
    assert window.fullscreen.call_count == 2
    assert window.present.call_count >= 2
    window.grab_focus.assert_called()
    assert presenter._pump_gtk_events.call_count == 2


def test_present_gtk_video_window_can_start_hidden() -> None:
    presenter = make_presenter()
    presenter._pump_gtk_events = MagicMock()
    window = MagicMock()

    presenter._present_gtk_video_window(
        window,
        fullscreen=True,
        opacity=STARTUP_GTK_WINDOW_OPACITY,
    )

    window.set_opacity.assert_called_once_with(STARTUP_GTK_WINDOW_OPACITY)
    window.fullscreen.assert_called()
    window.present.assert_called()


def test_gtk_video_host_transparency_paths(monkeypatch) -> None:
    presenter = make_presenter("Raspberry Pi 4 Model B Rev 1.2")
    monkeypatch.setattr(presenter, "_find_labwc_pid", MagicMock(return_value=None))
    assert presenter._gtk_video_host_uses_transparency()
    presenter._find_labwc_pid.assert_not_called()

    presenter = make_presenter("Ubuntu VM")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "labwc")
    monkeypatch.setattr(presenter, "_find_labwc_pid", MagicMock(return_value=None))
    assert presenter._gtk_video_host_uses_transparency()
    presenter._find_labwc_pid.assert_not_called()

    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "GNOME")
    monkeypatch.setenv("DESKTOP_SESSION", "ubuntu")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    assert not presenter._gtk_video_host_uses_transparency()
    presenter._find_labwc_pid.assert_called_once_with()


def test_set_gtk_video_host_background_uses_configured_opaque_color() -> None:
    presenter = make_presenter()
    display = object()
    css_provider = MagicMock()
    widget = MagicMock()

    class FakeGdk:
        Display = SimpleNamespace(get_default=MagicMock(return_value=display))

    class FakeGtk:
        CssProvider = MagicMock(return_value=css_provider)
        StyleContext = SimpleNamespace(add_provider_for_display=MagicMock())
        STYLE_PROVIDER_PRIORITY_APPLICATION = 600

    presenter.gdk = FakeGdk
    presenter.gtk = FakeGtk

    presenter._set_gtk_video_host_background(
        widget,
        transparent=False,
        host_background=(0.2, 0.2, 0.3, 1.0),
    )

    css = css_provider.load_from_data.call_args.args[0].decode("utf-8")
    assert ".picframe-transparent-video-host" in css
    assert ".picframe-opaque-video-host" in css
    assert "rgba(51, 51, 76, 1)" in css
    widget.add_css_class.assert_called_once_with("picframe-opaque-video-host")


def test_gtk_opaque_host_background_css_clamps_and_defaults() -> None:
    assert GtkVideoPresenter._gtk_opaque_host_background_css(None) == "rgba(0, 0, 0, 1)"
    assert GtkVideoPresenter._gtk_opaque_host_background_css(object()) == "rgba(0, 0, 0, 1)"
    assert GtkVideoPresenter._gtk_opaque_host_background_css((-1.0, 0.5, 2.0, 0.0)) == (
        "rgba(0, 128, 255, 1)"
    )


def test_create_gtk_fixed_video_host_places_widget_in_fullscreen_host(
    monkeypatch,
) -> None:
    presenter = make_presenter()
    monkeypatch.setattr(
        presenter,
        "_gtk_primary_monitor_geometry",
        lambda: (0, 0, 2560, 1440),
    )
    presenter._set_gtk_video_host_background = MagicMock()

    class FakeGtk:
        Fixed = MagicMock(return_value=MagicMock())

    window = MagicMock()
    widget = MagicMock()

    host = presenter._create_gtk_fixed_video_host(
        FakeGtk,
        window,
        widget,
        100,
        80,
        1800,
        1000,
    )

    FakeGtk.Fixed.assert_called_once_with()
    presenter._set_gtk_video_host_background.assert_called_once_with(
        host,
        transparent=True,
        host_background=None,
    )
    widget.set_size_request.assert_called_once_with(1800, 1000)
    host.put.assert_called_once_with(widget, 100, 80)
    window.set_default_size.assert_called_once_with(2560, 1440)
    host.set_size_request.assert_called_once_with(2560, 1440)


def test_gtk_fixed_host_child_rect_removes_offset_for_opaque_fullscreen(
    monkeypatch,
) -> None:
    presenter = make_presenter()
    monkeypatch.setattr(
        presenter,
        "_gtk_video_host_geometry",
        lambda *args: (0, 0, 2560, 1440),
    )

    assert presenter._gtk_fixed_host_child_rect(
        100,
        80,
        1800,
        1000,
        fullscreen=True,
        transparent=False,
    ) == (0, 0, 2560, 1440)
    assert presenter._gtk_fixed_host_child_rect(
        100,
        80,
        1800,
        1000,
        fullscreen=True,
        transparent=True,
    ) == (100, 80, 1800, 1000)


def test_present_gtk_paintable_uses_fixed_host_for_custom_geometry(
    monkeypatch,
) -> None:
    presenter = make_presenter()
    window = MagicMock()
    widget = MagicMock()
    host = MagicMock()
    video_sink = MagicMock()

    class FakeGtk:
        Window = MagicMock(return_value=window)

    monkeypatch.setattr(presenter, "_gtk_geometry_is_fullscreen", lambda *args: False)
    monkeypatch.setattr(presenter, "_gtk_video_host_uses_transparency", lambda: False)
    monkeypatch.setattr(presenter, "_create_gtk_video_picture", MagicMock(return_value=widget))
    fixed_host = MagicMock(return_value=host)
    monkeypatch.setattr(presenter, "_create_gtk_fixed_video_host", fixed_host)
    apply_host_geometry = MagicMock()
    monkeypatch.setattr(presenter, "_apply_gtk_host_window_geometry", apply_host_geometry)
    monkeypatch.setattr(presenter, "_configure_gtk_video_window", MagicMock())
    configure_background = MagicMock()
    monkeypatch.setattr(presenter, "_configure_gtk_video_host_background", configure_background)
    present_window = MagicMock()
    monkeypatch.setattr(presenter, "_present_gtk_video_window", present_window)
    monkeypatch.setattr(presenter, "_log_gtk_window_diagnostics", MagicMock())
    monkeypatch.setattr(presenter, "_hide_gtk_cursor", MagicMock())
    monkeypatch.setattr(presenter, "_gtk_window_matches_geometry", lambda *args, **kwargs: True)
    monkeypatch.setattr(presenter, "_start_gtk_pump", MagicMock())

    result = presenter.present_paintable(
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
        host_backdrop_path=None,
        host_backdrop_rect=None,
    )
    window.set_child.assert_called_once_with(host)
    apply_host_geometry.assert_called_once_with(window, 10, 20, 300, 400)
    present_window.assert_called_once_with(
        window,
        fullscreen=True,
        opacity=STARTUP_GTK_WINDOW_OPACITY,
    )
    assert presenter.window is window
    assert presenter.host is host
    assert presenter.video_sink is video_sink


def test_present_gtk_paintable_keeps_transparent_fullscreen_without_backdrop(
    monkeypatch,
) -> None:
    presenter = make_presenter("Raspberry Pi 4 Model B Rev 1.2")
    window = MagicMock()
    widget = MagicMock()
    video_sink = MagicMock()

    class FakeGtk:
        Window = MagicMock(return_value=window)

    monkeypatch.setattr(presenter, "_gtk_geometry_is_fullscreen", lambda *args: True)
    monkeypatch.setattr(presenter, "_gtk_video_host_uses_transparency", lambda: True)
    monkeypatch.setattr(presenter, "_create_gtk_video_picture", MagicMock(return_value=widget))
    fixed_host = MagicMock()
    monkeypatch.setattr(presenter, "_create_gtk_fixed_video_host", fixed_host)
    apply_window_geometry = MagicMock()
    monkeypatch.setattr(presenter, "_apply_gtk_window_geometry", apply_window_geometry)
    monkeypatch.setattr(presenter, "_configure_gtk_video_window", MagicMock())
    configure_background = MagicMock()
    monkeypatch.setattr(presenter, "_configure_gtk_video_host_background", configure_background)
    monkeypatch.setattr(presenter, "_present_gtk_video_window", MagicMock())
    monkeypatch.setattr(presenter, "_log_gtk_window_diagnostics", MagicMock())
    monkeypatch.setattr(presenter, "_hide_gtk_cursor", MagicMock())
    monkeypatch.setattr(presenter, "_gtk_window_matches_geometry", lambda *args, **kwargs: True)
    monkeypatch.setattr(presenter, "_start_gtk_pump", MagicMock())

    result = presenter.present_paintable(
        FakeGtk,
        video_sink,
        MagicMock(),
        0,
        0,
        800,
        600,
        set_sink_window_size=False,
        content_fit="contain",
        host_background=(0.2, 0.2, 0.3, 1.0),
    )

    assert result is True
    presenter._configure_gtk_video_window.assert_called_once_with(
        window,
        transparent=True,
    )
    configure_background.assert_called_once_with(
        window,
        transparent=True,
        host_background=(0.2, 0.2, 0.3, 1.0),
    )
    fixed_host.assert_not_called()
    window.set_child.assert_called_once_with(widget)
    apply_window_geometry.assert_called_once_with(
        window,
        0,
        0,
        800,
        600,
        fullscreen=True,
        widget=widget,
    )


def test_present_gtk_paintable_uses_opaque_fixed_host_for_backdrop(
    monkeypatch,
) -> None:
    presenter = make_presenter("Raspberry Pi 4 Model B Rev 1.2")
    window = MagicMock()
    widget = MagicMock()
    host = MagicMock()
    video_sink = MagicMock()

    class FakeGtk:
        Window = MagicMock(return_value=window)

    monkeypatch.setattr(presenter, "_gtk_geometry_is_fullscreen", lambda *args: True)
    monkeypatch.setattr(presenter, "_gtk_video_host_uses_transparency", lambda: True)
    monkeypatch.setattr(presenter, "_create_gtk_video_picture", MagicMock(return_value=widget))
    fixed_host = MagicMock(return_value=host)
    monkeypatch.setattr(presenter, "_create_gtk_fixed_video_host", fixed_host)
    apply_host_geometry = MagicMock()
    monkeypatch.setattr(presenter, "_apply_gtk_host_window_geometry", apply_host_geometry)
    monkeypatch.setattr(presenter, "_configure_gtk_video_window", MagicMock())
    configure_background = MagicMock()
    monkeypatch.setattr(presenter, "_configure_gtk_video_host_background", configure_background)
    monkeypatch.setattr(presenter, "_present_gtk_video_window", MagicMock())
    monkeypatch.setattr(presenter, "_log_gtk_window_diagnostics", MagicMock())
    monkeypatch.setattr(presenter, "_hide_gtk_cursor", MagicMock())
    monkeypatch.setattr(presenter, "_gtk_window_matches_geometry", lambda *args, **kwargs: True)
    monkeypatch.setattr(presenter, "_start_gtk_pump", MagicMock())

    result = presenter.present_paintable(
        FakeGtk,
        video_sink,
        MagicMock(),
        0,
        0,
        800,
        600,
        set_sink_window_size=False,
        content_fit="fill",
        host_background=(0.2, 0.2, 0.3, 1.0),
        host_backdrop_path="/cache/video.1.frame",
        host_backdrop_rect=(0, 0, 800, 600),
    )

    assert result is True
    presenter._configure_gtk_video_window.assert_called_once_with(
        window,
        transparent=False,
    )
    configure_background.assert_called_once_with(
        window,
        transparent=False,
        host_background=(0.2, 0.2, 0.3, 1.0),
    )
    fixed_host.assert_called_once_with(
        FakeGtk,
        window,
        widget,
        0,
        0,
        800,
        600,
        transparent=False,
        host_background=(0.2, 0.2, 0.3, 1.0),
        host_backdrop_path="/cache/video.1.frame",
        host_backdrop_rect=(0, 0, 800, 600),
    )
    window.set_child.assert_called_once_with(host)
    apply_host_geometry.assert_called_once_with(window, 0, 0, 800, 600)


def test_create_gtk_fixed_video_host_places_backdrop_under_video(
    monkeypatch,
    tmp_path,
) -> None:
    presenter = make_presenter()
    monkeypatch.setattr(
        presenter,
        "_gtk_primary_monitor_geometry",
        lambda: (0, 0, 800, 600),
    )
    presenter._set_gtk_video_host_background = MagicMock()
    backdrop_path = tmp_path / "first.frame"
    backdrop_path.write_bytes(b"image")
    host = MagicMock()
    backdrop = MagicMock()

    class FakeGtk:
        ContentFit = SimpleNamespace(FILL="fill")
        Fixed = MagicMock(return_value=host)
        Picture = SimpleNamespace(new_for_filename=MagicMock(return_value=backdrop))

    window = MagicMock()
    widget = MagicMock()

    result = presenter._create_gtk_fixed_video_host(
        FakeGtk,
        window,
        widget,
        100,
        80,
        320,
        180,
        transparent=False,
        host_background=(0.2, 0.2, 0.3, 1.0),
        host_backdrop_path=str(backdrop_path),
        host_backdrop_rect=(10, 20, 400, 300),
    )

    assert result is host
    FakeGtk.Picture.new_for_filename.assert_called_once_with(str(backdrop_path))
    backdrop.set_size_request.assert_called_with(400, 300)
    backdrop.set_content_fit.assert_called_once_with("fill")
    assert host.put.call_args_list[0].args == (backdrop, 10, 20)
    assert host.put.call_args_list[1].args == (widget, 100, 80)


def test_create_gtk_video_picture_content_fit_modes() -> None:
    presenter = make_presenter()
    picture = MagicMock()

    class FakeGtk:
        ContentFit = SimpleNamespace(CONTAIN="contain", FILL="fill")
        Picture = SimpleNamespace(new_for_paintable=MagicMock(return_value=picture))

    assert presenter._create_gtk_video_picture(FakeGtk, MagicMock()) is picture
    picture.set_content_fit.assert_called_once_with("contain")

    picture.reset_mock()
    assert (
        presenter._create_gtk_video_picture(
            FakeGtk,
            MagicMock(),
            content_fit="fill",
        )
        is picture
    )
    picture.set_content_fit.assert_called_once_with("fill")


def test_gtk_window_matches_geometry_accepts_fullscreen_before_size_settles() -> None:
    presenter = make_presenter()
    presenter._pump_gtk_events = MagicMock()
    window = MagicMock()
    window.get_size.return_value = (640, 480)

    assert presenter._gtk_window_matches_geometry(
        window,
        0,
        0,
        2560,
        1440,
        fullscreen=True,
    )
    presenter._pump_gtk_events.assert_called_once_with()
    window.get_size.assert_not_called()
    window.get_position.assert_not_called()


def test_gtk_window_matches_geometry_checks_fixed_host_child_geometry() -> None:
    presenter = make_presenter()
    presenter._pump_gtk_events = MagicMock()
    window = MagicMock()
    widget = MagicMock()
    allocation = SimpleNamespace(width=300, height=400)
    widget.get_allocation.return_value = allocation
    widget.translate_coordinates.return_value = (10, 20)

    assert presenter._gtk_window_matches_geometry(
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
    assert not presenter._gtk_window_matches_geometry(
        window,
        10,
        20,
        300,
        400,
        fullscreen=False,
        widget=widget,
        fixed_host=True,
    )


def test_apply_eos_opacity_probe_pauses_pipeline_before_opacity() -> None:
    presenter = make_presenter()
    presenter.window = MagicMock()
    presenter._pump_gtk_events = MagicMock()
    pipeline = MagicMock()
    order: list[tuple[str, object]] = []
    pipeline.set_state.side_effect = lambda value: order.append(("pause", value))
    presenter.window.set_opacity.side_effect = lambda value: order.append(("opacity", value))

    presenter.apply_eos_opacity_probe(pipeline)

    pipeline.set_state.assert_called_once_with("paused")
    presenter.window.set_opacity.assert_called_once_with(EOS_GTK_WINDOW_OPACITY)
    presenter._pump_gtk_events.assert_called_once_with()
    assert order == [("pause", "paused"), ("opacity", EOS_GTK_WINDOW_OPACITY)]


def test_destroy_clears_gtk_state() -> None:
    presenter = make_presenter()
    presenter.window = MagicMock()
    presenter.host = MagicMock()
    presenter.sink_widget = MagicMock()
    presenter.video_sink = MagicMock()
    presenter._stop_gtk_pump = MagicMock()
    presenter._pump_gtk_events = MagicMock()

    presenter.destroy()

    presenter._stop_gtk_pump.assert_called_once_with()
    assert presenter.window is None
    assert presenter.host is None
    assert presenter.sink_widget is None
    assert presenter.video_sink is None
