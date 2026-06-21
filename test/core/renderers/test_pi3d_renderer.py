"""Unit tests for the Pi3dRenderer."""
import os
import signal
from collections.abc import Generator
from dataclasses import replace
from unittest.mock import MagicMock, patch

import pytest

from picframe.core.events.dto import (
    RENDER_PARK_VIDEO_REVEAL,
    RENDER_PAUSE_PLAYBACK,
    RENDER_PRELOAD_VIDEO_REVEAL,
    RENDER_PROMOTE_VIDEO_REVEAL,
    RENDER_RESUME_PLAYBACK,
    RENDER_UPDATE_OVERLAY,
    RENDER_VIDEO_FIRST_FRAME,
    RENDER_WAKE_VIDEO_REVEAL,
    CurrentMediaChangedEvent,
    OverlayConfig,
    RenderCommand,
    RendererConfig,
    RendererConfigUpdatedEvent,
    TransitionCompletedEvent,
)
from picframe.core.models.media import DisplayItem, MediaItem, MediaType
from picframe.core.renderers.animation_controller import RenderState
from picframe.core.renderers.pi3d_renderer import (
    PI3D_LABWC_IDENTIFIER,
    RESUME_REDRAW_FRAMES,
    TEXT_CLEAR_REDRAW_FRAMES,
    VIDEO_WINDOW_TITLE,
    Pi3dRenderer,
    PrioritizedRenderTask,
)


@pytest.fixture
def mock_pi3d() -> Generator[MagicMock, None, None]:
    """Mock the pi3d module to avoid requiring a real display."""
    with patch("picframe.core.renderers.pi3d_renderer.pi3d") as mock:
        # Mock Display.create to return a mock display
        mock_display = MagicMock()
        mock_display.width = 1920
        mock_display.height = 1080
        mock_display.loop_running.return_value = True
        mock.Display.create.return_value = mock_display
        
        # Mock Camera
        mock_camera = MagicMock()
        mock.Camera.instance.return_value = mock_camera
        mock.Camera.return_value = mock_camera
        
        # Mock ImageRenderer's pi3d import
        with patch("picframe.core.renderers.components.image_renderer.pi3d", mock):
            yield mock


@pytest.fixture
def mock_image_renderer() -> Generator[MagicMock, None, None]:
    with patch("picframe.core.renderers.pi3d_renderer.ImageRenderer") as mock:
        instance = mock.return_value
        instance.execute.return_value = True
        instance.update_transition.return_value = True
        yield instance


@pytest.fixture
def mock_text_renderer() -> Generator[MagicMock, None, None]:
    with patch("picframe.core.renderers.pi3d_renderer.TextRenderer") as mock:
        yield mock.return_value


@pytest.fixture
def mock_clock_renderer() -> Generator[MagicMock, None, None]:
    with patch("picframe.core.renderers.pi3d_renderer.ClockRenderer") as mock:
        yield mock.return_value


@pytest.fixture
def config() -> RendererConfig:
    """Provide a basic configuration for the renderer."""
    return RendererConfig(
        display_w=1920,
        display_h=1080,
        fps=60,
        background=(0.0, 0.0, 0.0, 1.0),
        blend_type="blend",
        time_delay=200.0,
        time_fade=2.0,
        font_file="/path/to/font.ttf",
    )


def test_renderer_initialization(config: RendererConfig) -> None:
    """Test that the renderer initializes with the correct configuration."""
    renderer = Pi3dRenderer(config)
    assert renderer._display_w == 1920
    assert renderer._display_h == 1080
    assert renderer._fps == 60
    assert renderer._animation_controller._state == RenderState.STATIC


def test_renderer_formats_overlay_date_with_model_locale(config: RendererConfig) -> None:
    """Renderer-side overlay generation uses the configured model locale."""
    renderer = Pi3dRenderer(
        replace(
            config,
            show_text_enabled=True,
            text_overlay_format="date",
            show_text_fm="%B %d, %Y",
            model_locale="de_DE.utf8",
        )
    )
    media_item = MediaItem(
        filepath="/path/to/image.jpg",
        filename="image.jpg",
        directory_id=1,
        media_type=MediaType.IMAGE,
        file_size=1024,
        last_modified=1.0,
        exif_datetime=1_710_000_000.0,
    )

    with patch(
        "picframe.core.renderers.pi3d_renderer.format_datetime_for_locale",
        return_value="März 09, 2024",
    ) as format_datetime:
        assert renderer._generate_text_string(media_item) == "März 09, 2024"

    format_datetime.assert_called_once()
    _, date_format, locale_value = format_datetime.call_args.args
    assert date_format == "%B %d, %Y"
    assert locale_value == "de_DE.utf8"


def test_renderer_start_stop(
    config: RendererConfig,
    mock_pi3d: MagicMock,
    mock_image_renderer: MagicMock,
    mock_text_renderer: MagicMock,
    mock_clock_renderer: MagicMock
) -> None:
    """Test starting and stopping the renderer."""
    renderer = Pi3dRenderer(config)

    # Start
    renderer.start()
    mock_pi3d.Display.create.assert_called_once()
    assert renderer._display is not None
    assert renderer._image_renderer is not None
    assert renderer._text_renderer is not None
    assert renderer._clock_renderer is not None

    # Stop
    display_mock = renderer._display
    renderer.stop()
    display_mock.destroy.assert_called_once()
    assert renderer._display is None
    assert renderer._image_renderer is None
    assert renderer._text_renderer is None
    assert renderer._clock_renderer is None


def test_renderer_stop_clears_pi3d_singletons(
    config: RendererConfig,
    mock_pi3d: MagicMock,
    mock_image_renderer: MagicMock,
    mock_text_renderer: MagicMock,
    mock_clock_renderer: MagicMock,
) -> None:
    class FakeDisplayClass:
        INSTANCE = object()

    renderer = Pi3dRenderer(config)
    renderer.start()
    mock_pi3d.Display.INSTANCE = object()
    mock_pi3d.Display.Display = FakeDisplayClass
    mock_pi3d.Camera.INSTANCE = object()
    mock_pi3d.Camera._INSTANCE = object()
    mock_pi3d.Camera._ALL_INSTANCES = {object()}

    renderer.stop()

    assert mock_pi3d.Display.INSTANCE is None
    assert FakeDisplayClass.INSTANCE is None
    assert mock_pi3d.Camera.INSTANCE is None
    assert mock_pi3d.Camera._INSTANCE is None
    assert mock_pi3d.Camera._ALL_INSTANCES == set()


def test_renderer_start_resets_stale_video_and_animation_state(
    config: RendererConfig,
    mock_pi3d: MagicMock,
    mock_image_renderer: MagicMock,
    mock_text_renderer: MagicMock,
    mock_clock_renderer: MagicMock,
) -> None:
    renderer = Pi3dRenderer(config)
    renderer.start()
    renderer._video_reveal_parked = True
    renderer._video_first_frame_transition = True
    renderer._was_transitioning = True
    renderer._animation_controller.suspend()
    renderer._local_queue.put(PrioritizedRenderTask(priority=0, task="clock_tick"))

    renderer.stop()
    renderer.start()

    assert renderer._video_reveal_parked is False
    assert renderer._video_first_frame_transition is False
    assert renderer._was_transitioning is False
    assert renderer._animation_controller._state == RenderState.STATIC
    assert renderer._local_queue.empty()


def test_renderer_start_forces_initial_background_draw(
    config: RendererConfig,
    mock_pi3d: MagicMock,
    mock_image_renderer: MagicMock,
    mock_text_renderer: MagicMock,
    mock_clock_renderer: MagicMock,
) -> None:
    renderer = Pi3dRenderer(config)
    renderer.start()

    result = renderer.render_frame()

    assert result is True
    mock_image_renderer.draw.assert_called_once_with()


def test_renderer_uses_fullscreen_host_for_custom_geometry_without_labwc(
    mock_pi3d: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = RendererConfig(
        display_x=0,
        display_y=0,
        display_w=1000,
        display_h=900,
        font_file="/path/to/font.ttf",
    )
    renderer = Pi3dRenderer(config)
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")
    monkeypatch.setattr(renderer, "_find_labwc_pid", lambda: None)

    with (
        patch("picframe.core.renderers.pi3d_renderer.ImageRenderer") as image_renderer,
        patch("picframe.core.renderers.pi3d_renderer.TextRenderer") as text_renderer,
        patch("picframe.core.renderers.pi3d_renderer.ClockRenderer") as clock_renderer,
    ):
        renderer.start()

    create_kwargs = mock_pi3d.Display.create.call_args.kwargs
    assert create_kwargs["x"] == 0
    assert create_kwargs["y"] == 0
    assert create_kwargs["w"] is None
    assert create_kwargs["h"] is None
    assert renderer.get_display_rect() == (0, 0, 1000, 900)
    assert image_renderer.call_args.kwargs["render_rect"] == (0, 0, 1000, 900)
    assert text_renderer.call_args.kwargs["render_rect"] == (0, 0, 1000, 900)
    assert clock_renderer.call_args.kwargs["render_rect"] == (0, 0, 1000, 900)


def test_renderer_keeps_configured_window_geometry_with_labwc(
    mock_pi3d: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = RendererConfig(
        display_x=10,
        display_y=20,
        display_w=1000,
        display_h=900,
        font_file="/path/to/font.ttf",
    )
    renderer = Pi3dRenderer(config)
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")
    monkeypatch.setattr(renderer, "_find_labwc_pid", lambda: 1234)
    monkeypatch.setattr(renderer, "_prepare_labwc_geometry_rules", MagicMock())

    with (
        patch("picframe.core.renderers.pi3d_renderer.ImageRenderer") as image_renderer,
        patch("picframe.core.renderers.pi3d_renderer.TextRenderer") as text_renderer,
        patch("picframe.core.renderers.pi3d_renderer.ClockRenderer") as clock_renderer,
    ):
        renderer.start()

    create_kwargs = mock_pi3d.Display.create.call_args.kwargs
    assert create_kwargs["x"] == 10
    assert create_kwargs["y"] == 20
    assert create_kwargs["w"] == 1000
    assert create_kwargs["h"] == 900
    assert image_renderer.call_args.kwargs["render_rect"] is None
    assert text_renderer.call_args.kwargs["render_rect"] is None
    assert clock_renderer.call_args.kwargs["render_rect"] is None


def test_renderer_get_display_rect_prefers_actual_display_geometry(
    mock_pi3d: MagicMock,
    mock_image_renderer: MagicMock,
    mock_text_renderer: MagicMock,
    mock_clock_renderer: MagicMock,
) -> None:
    """Actual pi3d geometry is the contract for matching video overlays."""
    config = RendererConfig(
        display_x=100,
        display_y=80,
        display_w=1800,
        display_h=1000,
        font_file="/path/to/font.ttf",
    )
    renderer = Pi3dRenderer(config)
    renderer.start()

    assert renderer._display is not None
    renderer._display.left = 0
    renderer._display.top = 80
    renderer._display.width = 1920
    renderer._display.height = 1080

    assert renderer.get_display_rect() == (0, 80, 1920, 1080)


def test_renderer_sets_stable_sdl_window_identity(
    config: RendererConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderer = Pi3dRenderer(config)
    for key in (
        "SDL_VIDEO_WAYLAND_WMCLASS",
        "SDL_VIDEO_X11_WMCLASS",
        "SDL_APP_ID",
    ):
        monkeypatch.delenv(key, raising=False)

    renderer._prepare_wayland_window_identity()

    assert os.environ["SDL_VIDEO_WAYLAND_WMCLASS"] == PI3D_LABWC_IDENTIFIER
    assert os.environ["SDL_VIDEO_X11_WMCLASS"] == PI3D_LABWC_IDENTIFIER
    assert os.environ["SDL_APP_ID"] == PI3D_LABWC_IDENTIFIER


def test_renderer_labwc_config_xml_positions_pi3d_and_decorates_video() -> None:
    xml = Pi3dRenderer._labwc_config_xml((100, 80, 1800, 1000))

    assert f'identifier="{PI3D_LABWC_IDENTIFIER}"' in xml
    assert f'title="{PI3D_LABWC_IDENTIFIER}"' in xml
    assert f'title="{VIDEO_WINDOW_TITLE}"' in xml
    assert '<action name="ResizeTo" width="1800" height="1000" />' in xml
    assert '<action name="MoveTo" x="100" y="80" />' in xml
    assert 'serverDecoration="no"' in xml


def test_renderer_labwc_config_xml_omits_geometry_for_fullscreen_default() -> None:
    xml = Pi3dRenderer._labwc_config_xml(None)

    assert f'identifier="{PI3D_LABWC_IDENTIFIER}"' in xml
    assert f'title="{VIDEO_WINDOW_TITLE}"' in xml
    assert "ResizeTo" not in xml
    assert "MoveTo" not in xml


def test_renderer_writes_labwc_rules_and_reconfigures_labwc(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderer = Pi3dRenderer(
        RendererConfig(
            display_x=100,
            display_y=80,
            display_w=1800,
            display_h=1000,
            font_file="/path/to/font.ttf",
        )
    )
    kill = MagicMock()
    sleep = MagicMock()
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")
    monkeypatch.setenv("PICFRAME_DIR", str(tmp_path))
    monkeypatch.setattr(renderer, "_find_labwc_pid", lambda: 1234)
    monkeypatch.setattr("picframe.core.renderers.pi3d_renderer.os.kill", kill)
    monkeypatch.setattr("picframe.core.renderers.pi3d_renderer.time.sleep", sleep)

    renderer._prepare_labwc_geometry_rules()

    rc_xml = tmp_path / "labwc" / "rc.xml"
    assert rc_xml.exists()
    assert f'identifier="{PI3D_LABWC_IDENTIFIER}"' in rc_xml.read_text()
    assert '<action name="MoveTo" x="100" y="80" />' in rc_xml.read_text()
    kill.assert_called_once_with(1234, signal.SIGHUP)
    sleep.assert_called_once_with(0.05)


def test_renderer_clears_labwc_geometry_rules_for_fullscreen_default(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderer = Pi3dRenderer(
        RendererConfig(
            display_x=0,
            display_y=0,
            display_w=None,
            display_h=None,
            font_file="/path/to/font.ttf",
        )
    )
    kill = MagicMock()
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")
    monkeypatch.setenv("PICFRAME_DIR", str(tmp_path))
    monkeypatch.setattr(renderer, "_find_labwc_pid", lambda: 1234)
    monkeypatch.setattr("picframe.core.renderers.pi3d_renderer.os.kill", kill)
    monkeypatch.setattr("picframe.core.renderers.pi3d_renderer.time.sleep", MagicMock())

    renderer._prepare_labwc_geometry_rules()

    rc_xml = tmp_path / "labwc" / "rc.xml"
    rc_xml_text = rc_xml.read_text()
    assert f'identifier="{PI3D_LABWC_IDENTIFIER}"' in rc_xml_text
    assert "MoveTo" not in rc_xml_text
    assert "ResizeTo" not in rc_xml_text
    kill.assert_called_once_with(1234, signal.SIGHUP)


def test_renderer_execute_without_start(
    config: RendererConfig,
    mock_image_renderer: MagicMock
) -> None:
    """Test executing a command before starting the renderer."""
    renderer = Pi3dRenderer(config)
    command = RenderCommand(image_path="/path/to/image.jpg")
    renderer.execute(command)
    # Should not call image renderer if not started
    mock_image_renderer.execute.assert_not_called()


def test_renderer_execute(
    config: RendererConfig,
    mock_pi3d: MagicMock,
    mock_image_renderer: MagicMock
) -> None:
    """Test executing a render command."""
    renderer = Pi3dRenderer(config)
    renderer.start()

    command = RenderCommand(
        image_path="/path/to/image.jpg",
        overlay=OverlayConfig(show_clock=True, show_text=True, text_string="Test"),
    )
    
    # Mock ImageRenderer.execute to return success and kb steps
    mock_image_renderer.execute.return_value = (True, 0.0, 0.0)
    
    renderer.execute(command)

    mock_image_renderer.execute.assert_called_once_with(command)
    assert renderer._animation_controller._state == RenderState.TRANSITIONING
    assert renderer._overlay_config.text_string == "Test"


def test_renderer_execute_video(
    config: RendererConfig,
    mock_pi3d: MagicMock,
    mock_image_renderer: MagicMock
) -> None:
    """Test executing a render command for a video."""
    renderer = Pi3dRenderer(config)
    renderer.start()

    # Mock ImageRenderer.execute to return False for video
    mock_image_renderer.execute.return_value = (False, 0.0, 0.0)

    command = RenderCommand(image_path="/path/to/video.mp4")
    renderer.execute(command)

    mock_image_renderer.execute.assert_called_once_with(command)
    # The state should not change to TRANSITIONING if execute returns False
    assert renderer._animation_controller._state == RenderState.STATIC


def test_renderer_execute_video_first_frame_marks_delayed_handoff(
    config: RendererConfig,
    mock_pi3d: MagicMock,
    mock_image_renderer: MagicMock,
) -> None:
    renderer = Pi3dRenderer(config)
    renderer.start()
    mock_image_renderer.execute.return_value = (True, 0.0, 0.0)

    command = RenderCommand(
        image_path="/cache/video.1.frame",
        overlay=OverlayConfig(show_text=True, text_string="Video"),
        render_action=RENDER_VIDEO_FIRST_FRAME,
    )

    renderer.execute(command)

    assert renderer._video_first_frame_transition is True
    assert renderer._was_transitioning is True
    assert renderer._animation_controller._state == RenderState.TRANSITIONING


def test_renderer_update_overlay_refreshes_text_without_image_transition(
    config: RendererConfig,
    mock_pi3d: MagicMock,
    mock_image_renderer: MagicMock,
    mock_text_renderer: MagicMock,
) -> None:
    renderer = Pi3dRenderer(config)
    renderer.start()
    mock_image_renderer.execute.reset_mock()

    renderer.execute(
        RenderCommand(
            image_path="UPDATE_OVERLAY",
            overlay=OverlayConfig(show_text=False, status_text="PAUSED"),
            render_action=RENDER_UPDATE_OVERLAY,
        )
    )

    mock_image_renderer.execute.assert_not_called()
    assert renderer._overlay_config.status_text == "PAUSED"
    mock_text_renderer.update_config.assert_called_once_with(renderer._overlay_config)
    assert renderer._animation_controller._state == RenderState.TEXT_ANIMATING


@patch("time.sleep")
def test_renderer_pause_action_freezes_inflight_transition(
    mock_sleep: MagicMock,
    config: RendererConfig,
    mock_pi3d: MagicMock,
    mock_image_renderer: MagicMock,
    mock_text_renderer: MagicMock,
    mock_clock_renderer: MagicMock,
) -> None:
    publisher = MagicMock()
    renderer = Pi3dRenderer(config, event_publisher=publisher)
    renderer.start()
    renderer._was_transitioning = True
    renderer._animation_controller._state = RenderState.TRANSITIONING
    renderer._animation_controller._image_alpha = 0.5
    renderer._animation_controller._text_alpha = 0.0
    renderer._animation_controller._frames_to_render = 0
    renderer._last_text_alpha = 0.0
    mock_clock_renderer.has_changed.return_value = False

    renderer.execute(
        RenderCommand(
            image_path="PAUSE_PLAYBACK",
            overlay=OverlayConfig(status_text="PAUSED"),
            render_action=RENDER_PAUSE_PLAYBACK,
        )
    )

    assert renderer._animation_controller.is_paused
    assert renderer._animation_controller._text_alpha == 1.0
    assert renderer._overlay_config.status_text == "PAUSED"

    renderer._animation_controller._frames_to_render = 0
    with patch("time.time", return_value=100.0):
        result = renderer.render_frame()

    assert result is True
    assert renderer._animation_controller._image_alpha == 0.5
    publisher.publish.assert_not_called()
    mock_sleep.assert_called_once_with(0.05)


def test_renderer_resume_action_continues_frozen_transition(
    config: RendererConfig,
    mock_pi3d: MagicMock,
    mock_image_renderer: MagicMock,
    mock_text_renderer: MagicMock,
    mock_clock_renderer: MagicMock,
) -> None:
    renderer = Pi3dRenderer(config)
    renderer.start()
    renderer._animation_controller._state = RenderState.TRANSITIONING
    renderer._animation_controller._image_alpha = 0.5
    renderer._animation_controller.pause(force_text_visible=True)

    renderer.execute(
        RenderCommand(
            image_path="RESUME_PLAYBACK",
            overlay=OverlayConfig(status_text=""),
            render_action=RENDER_RESUME_PLAYBACK,
        )
    )

    assert not renderer._animation_controller.is_paused
    assert renderer._overlay_config.status_text == ""


def test_renderer_pause_resume_preserves_visible_text_timer(
    config: RendererConfig,
    mock_pi3d: MagicMock,
    mock_image_renderer: MagicMock,
    mock_text_renderer: MagicMock,
    mock_clock_renderer: MagicMock,
) -> None:
    renderer = Pi3dRenderer(config)
    renderer.start()
    renderer._overlay_config = OverlayConfig(show_text=True, text_string="Photo")
    renderer._animation_controller._show_text = True
    renderer._animation_controller._state = RenderState.STATIC
    renderer._animation_controller._text_alpha = 1.0
    renderer._animation_controller._text_timer = 101.0

    renderer.execute(
        RenderCommand(
            image_path="PAUSE_PLAYBACK",
            overlay=OverlayConfig(show_text=True, text_string="Photo", status_text="PAUSED"),
            render_action=RENDER_PAUSE_PLAYBACK,
        )
    )
    renderer.execute(
        RenderCommand(
            image_path="RESUME_PLAYBACK",
            overlay=OverlayConfig(show_text=True, text_string="Photo", status_text=""),
            render_action=RENDER_RESUME_PLAYBACK,
        )
    )
    renderer._animation_controller.update(100.0)

    assert renderer._animation_controller._state == RenderState.STATIC
    assert renderer._animation_controller._text_timer == 101.0


@patch("time.sleep")
def test_renderer_video_first_frame_completion_publishes_transition_token(
    mock_sleep: MagicMock,
    config: RendererConfig,
    mock_pi3d: MagicMock,
    mock_image_renderer: MagicMock,
    mock_text_renderer: MagicMock,
    mock_clock_renderer: MagicMock,
) -> None:
    publisher = MagicMock()
    renderer = Pi3dRenderer(config, event_publisher=publisher)
    renderer.start()
    mock_image_renderer.execute.return_value = (True, 0.0, 0.0)

    renderer.execute(
        RenderCommand(
            image_path="/cache/video.1.frame",
            overlay=OverlayConfig(show_text=False),
            render_action=RENDER_VIDEO_FIRST_FRAME,
            transition_token=42,
        )
    )
    renderer._animation_controller._state = RenderState.STATIC
    renderer._animation_controller._image_alpha = 1.0
    renderer._animation_controller._show_text = False
    renderer._animation_controller._text_alpha = 0.0
    renderer._animation_controller._frames_to_render = 0
    renderer._last_text_alpha = 0.0
    renderer._last_redraw_time = 100.0
    mock_clock_renderer.has_changed.return_value = False

    with patch("time.time", return_value=101.0):
        result = renderer.render_frame()

    assert result is True
    event = publisher.publish.call_args.args[0]
    assert isinstance(event, TransitionCompletedEvent)
    assert event.transition_token == 42
    assert renderer._transition_token is None
    mock_sleep.assert_called_once_with(0.05)


def test_renderer_current_media_event_does_not_restart_same_single_overlay_text(
    config: RendererConfig,
    mock_pi3d: MagicMock,
    mock_image_renderer: MagicMock,
    mock_text_renderer: MagicMock,
    mock_clock_renderer: MagicMock,
) -> None:
    text_config = replace(
        config,
        show_text_enabled=True,
        text_overlay_format="name",
    )
    renderer = Pi3dRenderer(text_config)
    renderer.start()
    renderer._overlay_config = renderer._build_overlay_config(text_string="video.mp4")
    renderer._animation_controller._state = RenderState.STATIC
    renderer._animation_controller._show_text = False
    renderer._animation_controller._text_alpha = 0.0
    renderer._animation_controller._frames_to_render = 0
    media_item = MediaItem(
        id=1,
        filepath="/path/to/video.mp4",
        media_type=MediaType.VIDEO,
        filename="video.mp4",
        directory_id=1,
        file_size=1024,
        last_modified=1234567890.0,
    )

    renderer._handle_state_event(
        CurrentMediaChangedEvent(media_item=DisplayItem.single(media_item))
    )

    assert renderer._overlay_config.text_string == "video.mp4"
    assert renderer._overlay_config.text_strings == ()
    assert renderer._animation_controller._show_text is False
    assert renderer._animation_controller._frames_to_render == 0
    mock_text_renderer.update_config.assert_not_called()


def test_renderer_resume_forces_redraw_frames(
    config: RendererConfig,
    mock_pi3d: MagicMock,
    mock_image_renderer: MagicMock,
) -> None:
    renderer = Pi3dRenderer(config)
    renderer.start()
    renderer._animation_controller.suspend()

    renderer.execute(RenderCommand(image_path="RESUME"))

    assert renderer._animation_controller._state == RenderState.STATIC
    assert renderer._animation_controller._frames_to_render == RESUME_REDRAW_FRAMES
    mock_image_renderer.clear_video_reveal_texture.assert_called_once_with()
    mock_image_renderer.execute.assert_not_called()


def test_renderer_preloads_video_reveal_texture(
    config: RendererConfig,
    mock_pi3d: MagicMock,
    mock_image_renderer: MagicMock,
) -> None:
    renderer = Pi3dRenderer(config)
    renderer.start()
    mock_image_renderer.preload_video_reveal_texture.return_value = True

    command = RenderCommand(
        image_path="/cache/video.2.frame",
        render_action=RENDER_PRELOAD_VIDEO_REVEAL,
    )
    renderer.execute(command)

    mock_image_renderer.preload_video_reveal_texture.assert_called_once_with(command)
    mock_image_renderer.execute.assert_not_called()
    assert renderer._animation_controller._state == RenderState.STATIC


def test_renderer_promotes_video_reveal_texture(
    config: RendererConfig,
    mock_pi3d: MagicMock,
    mock_image_renderer: MagicMock,
) -> None:
    renderer = Pi3dRenderer(config)
    renderer.start()
    mock_image_renderer.promote_video_reveal_texture.return_value = True

    renderer.execute(
        RenderCommand(
            image_path="/cache/video.2.frame",
            render_action=RENDER_PROMOTE_VIDEO_REVEAL,
        )
    )

    mock_image_renderer.promote_video_reveal_texture.assert_called_once_with()
    mock_image_renderer.execute.assert_not_called()
    assert renderer._animation_controller._frames_to_render == RESUME_REDRAW_FRAMES


def test_renderer_parks_video_reveal_surface(
    config: RendererConfig,
    mock_pi3d: MagicMock,
    mock_image_renderer: MagicMock,
) -> None:
    renderer = Pi3dRenderer(config)
    renderer.start()

    renderer.execute(
        RenderCommand(
            image_path="PARK_VIDEO_REVEAL",
            render_action=RENDER_PARK_VIDEO_REVEAL,
        )
    )

    assert renderer._video_reveal_parked is True
    assert renderer._animation_controller._state == RenderState.STATIC
    mock_image_renderer.execute.assert_not_called()


def test_renderer_wakes_parked_video_reveal_surface(
    config: RendererConfig,
    mock_pi3d: MagicMock,
    mock_image_renderer: MagicMock,
) -> None:
    renderer = Pi3dRenderer(config)
    renderer.start()
    renderer._video_reveal_parked = True
    renderer._animation_controller.suspend()

    renderer.execute(
        RenderCommand(
            image_path="WAKE_VIDEO_REVEAL",
            render_action=RENDER_WAKE_VIDEO_REVEAL,
        )
    )

    assert renderer._video_reveal_parked is False
    assert renderer._animation_controller._frames_to_render == RESUME_REDRAW_FRAMES
    mock_image_renderer.clear_video_reveal_texture.assert_not_called()
    mock_image_renderer.execute.assert_not_called()


@patch("time.sleep")
def test_renderer_render_frame_video_reveal_parked(
    mock_sleep: MagicMock,
    config: RendererConfig,
    mock_pi3d: MagicMock,
    mock_image_renderer: MagicMock,
    mock_text_renderer: MagicMock,
    mock_clock_renderer: MagicMock,
) -> None:
    renderer = Pi3dRenderer(config)
    renderer.start()
    renderer._video_reveal_parked = True
    renderer._animation_controller._frames_to_render = 0

    result = renderer.render_frame()

    assert result is True
    mock_sleep.assert_called_once_with(0.05)
    mock_image_renderer.draw.assert_not_called()


@patch("time.sleep")
def test_renderer_render_frame_drains_forced_video_reveal_redraws_before_parking(
    mock_sleep: MagicMock,
    config: RendererConfig,
    mock_pi3d: MagicMock,
    mock_image_renderer: MagicMock,
    mock_text_renderer: MagicMock,
    mock_clock_renderer: MagicMock,
) -> None:
    renderer = Pi3dRenderer(config)
    renderer.start()
    renderer._video_reveal_parked = True
    renderer._animation_controller.force_redraw(1)

    result = renderer.render_frame()

    assert result is True
    mock_sleep.assert_not_called()
    mock_image_renderer.draw.assert_called_once_with()


def test_renderer_config_event_updates_image_renderer(
    config: RendererConfig,
    mock_pi3d: MagicMock,
    mock_image_renderer: MagicMock,
    mock_text_renderer: MagicMock,
    mock_clock_renderer: MagicMock,
) -> None:
    """Test that runtime renderer config changes reach image scaling logic."""
    renderer = Pi3dRenderer(config)
    renderer.start()

    updated = replace(
        config,
        fps=30,
        background=(0.1, 0.1, 0.1, 1.0),
        time_delay=30.0,
        time_fade=1.0,
        fit=True,
        kenburns=True,
    )

    renderer._handle_config_event(RendererConfigUpdatedEvent(config=updated))

    mock_image_renderer.update_config.assert_called_with(updated)
    assert mock_pi3d.Display.create.return_value.frames_per_second == 30
    assert renderer._kenburns is True
    assert renderer._animation_controller._fps == 30
    assert renderer._animation_controller._time_delay == 30.0


def test_renderer_config_event_defers_component_updates_for_display_geometry(
    config: RendererConfig,
    mock_pi3d: MagicMock,
    mock_image_renderer: MagicMock,
    mock_text_renderer: MagicMock,
    mock_clock_renderer: MagicMock,
) -> None:
    renderer = Pi3dRenderer(config)
    renderer.start()
    updated = replace(
        config,
        display_x=100,
        display_y=80,
        display_w=1000,
        display_h=900,
        fit=True,
    )

    renderer._handle_config_event(RendererConfigUpdatedEvent(config=updated))

    assert renderer._config == updated
    assert renderer._display_x == 100
    mock_image_renderer.update_config.assert_not_called()
    mock_text_renderer.update_config.assert_not_called()
    mock_clock_renderer.update_config.assert_not_called()


def test_renderer_backend_flags_require_service_restart(
    config: RendererConfig,
    mock_pi3d: MagicMock,
    mock_image_renderer: MagicMock,
    mock_text_renderer: MagicMock,
    mock_clock_renderer: MagicMock,
) -> None:
    renderer = Pi3dRenderer(config)
    renderer.start()
    updated = replace(config, use_glx=not config.use_glx, use_sdl2=not config.use_sdl2)

    assert renderer.requires_restart_for_config(config, updated) is True

    renderer._handle_config_event(RendererConfigUpdatedEvent(config=updated))

    assert renderer._config == updated
    assert renderer._pending_component_rebuild is False
    mock_image_renderer.update_config.assert_not_called()
    mock_text_renderer.update_config.assert_not_called()
    mock_clock_renderer.update_config.assert_not_called()


def test_renderer_mat_settings_do_not_require_service_restart(
    config: RendererConfig,
    mock_pi3d: MagicMock,
    mock_image_renderer: MagicMock,
    mock_text_renderer: MagicMock,
    mock_clock_renderer: MagicMock,
) -> None:
    renderer = Pi3dRenderer(config)
    renderer.start()
    updated = replace(
        config,
        mat_images=0.2,
        mat_resource_folder="/tmp/new-mats",
    )

    assert renderer.requires_restart_for_config(config, updated) is False

    renderer._handle_config_event(RendererConfigUpdatedEvent(config=updated))

    mock_image_renderer.update_config.assert_called_with(updated)
    assert renderer._pending_component_rebuild is False


def test_renderer_shader_and_font_changes_rebuild_components_without_restart(
    config: RendererConfig,
    mock_pi3d: MagicMock,
    mock_image_renderer: MagicMock,
    mock_text_renderer: MagicMock,
    mock_clock_renderer: MagicMock,
) -> None:
    renderer = Pi3dRenderer(config)
    renderer.start()
    updated = replace(
        config,
        shader_path="/new/shader",
        font_file="/new/font.ttf",
    )

    assert renderer.requires_restart_for_config(config, updated) is False

    renderer._handle_config_event(RendererConfigUpdatedEvent(config=updated))

    assert renderer._pending_component_rebuild is True
    mock_image_renderer.update_config.assert_not_called()
    mock_text_renderer.update_config.assert_not_called()
    mock_clock_renderer.update_config.assert_not_called()


def test_renderer_wayland_fullscreen_host_geometry_changes_do_not_require_restart(
    config: RendererConfig,
    mock_pi3d: MagicMock,
    mock_image_renderer: MagicMock,
    mock_text_renderer: MagicMock,
    mock_clock_renderer: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderer = Pi3dRenderer(config)
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")
    monkeypatch.setattr(renderer, "_find_labwc_pid", lambda: None)
    renderer.start()
    updated = replace(
        config,
        display_x=100,
        display_y=80,
        display_w=1000,
        display_h=900,
    )

    assert renderer.requires_restart_for_config(config, updated) is False


def test_renderer_labwc_geometry_changes_require_restart(
    config: RendererConfig,
    mock_pi3d: MagicMock,
    mock_image_renderer: MagicMock,
    mock_text_renderer: MagicMock,
    mock_clock_renderer: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderer = Pi3dRenderer(config)
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")
    monkeypatch.setattr(renderer, "_find_labwc_pid", lambda: 1234)
    monkeypatch.setattr(renderer, "_prepare_labwc_geometry_rules", MagicMock())
    renderer.start()
    updated = replace(
        config,
        display_x=100,
        display_y=80,
        display_w=1000,
        display_h=900,
    )

    assert renderer.requires_restart_for_config(config, updated) is True


def test_renderer_config_event_marks_wayland_fullscreen_host_geometry_for_rebuild(
    config: RendererConfig,
    mock_pi3d: MagicMock,
    mock_image_renderer: MagicMock,
    mock_text_renderer: MagicMock,
    mock_clock_renderer: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderer = Pi3dRenderer(config)
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")
    monkeypatch.setattr(renderer, "_find_labwc_pid", lambda: None)
    renderer.start()
    updated = replace(
        config,
        display_x=100,
        display_y=80,
        display_w=1000,
        display_h=900,
    )

    renderer._handle_config_event(RendererConfigUpdatedEvent(config=updated))

    assert renderer._config == updated
    assert renderer._pending_component_rebuild is True
    mock_image_renderer.update_config.assert_not_called()
    mock_text_renderer.update_config.assert_not_called()
    mock_clock_renderer.update_config.assert_not_called()


def test_renderer_execute_rebuilds_wayland_fullscreen_host_components_before_command(
    mock_pi3d: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = RendererConfig(
        display_x=0,
        display_y=0,
        display_w=1920,
        display_h=1080,
        font_file="/path/to/font.ttf",
    )
    renderer = Pi3dRenderer(config)
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")
    monkeypatch.setattr(renderer, "_find_labwc_pid", lambda: None)
    with (
        patch("picframe.core.renderers.pi3d_renderer.ImageRenderer") as image_renderer,
        patch("picframe.core.renderers.pi3d_renderer.TextRenderer"),
        patch("picframe.core.renderers.pi3d_renderer.ClockRenderer"),
    ):
        image_renderer.return_value.execute.return_value = (True, 0.0, 0.0)
        renderer.start()
        updated = replace(
            config,
            display_x=100,
            display_y=80,
            display_w=1000,
            display_h=900,
        )
        renderer._handle_config_event(RendererConfigUpdatedEvent(config=updated))
        command = RenderCommand(image_path="/tmp/image.jpg")

        renderer.execute(command)

    assert image_renderer.call_count == 2
    assert image_renderer.call_args.kwargs["render_rect"] == (100, 80, 1000, 900)
    image_renderer.return_value.execute.assert_called_once_with(command)
    assert renderer._pending_component_rebuild is False


def test_renderer_restart_uses_deferred_display_geometry_config(
    config: RendererConfig,
    mock_pi3d: MagicMock,
    mock_image_renderer: MagicMock,
    mock_text_renderer: MagicMock,
    mock_clock_renderer: MagicMock,
) -> None:
    renderer = Pi3dRenderer(config)
    renderer.start()
    updated = replace(
        config,
        display_x=33,
        display_y=44,
        display_w=1000,
        display_h=900,
    )

    renderer._handle_config_event(RendererConfigUpdatedEvent(config=updated))
    mock_pi3d.Display.create.reset_mock()
    renderer.stop()
    renderer.start()

    create_kwargs = mock_pi3d.Display.create.call_args.kwargs
    assert create_kwargs["x"] == 33
    assert create_kwargs["y"] == 44
    assert create_kwargs["w"] == 1000
    assert create_kwargs["h"] == 900


def test_renderer_render_frame(
    config: RendererConfig,
    mock_pi3d: MagicMock,
    mock_image_renderer: MagicMock,
    mock_text_renderer: MagicMock,
    mock_clock_renderer: MagicMock
) -> None:
    """Test rendering a frame."""
    renderer = Pi3dRenderer(config)
    renderer.start()
    
    # Set state to transitioning
    renderer._animation_controller._state = RenderState.TRANSITIONING
    renderer._animation_controller._image_alpha = 0.99 # Almost done
    renderer._animation_controller._fade_time = 0.01 # Fast fade

    renderer._animation_controller._show_text = True

    with patch("time.time", return_value=100.0):
        result = renderer.render_frame()

    assert result is True
    mock_image_renderer.set_alpha.assert_called_once()
    mock_image_renderer.draw.assert_called_once()
    # Should transition to TEXT_ANIMATING
    assert renderer._animation_controller._state == RenderState.TEXT_ANIMATING


def test_renderer_does_not_draw_text_during_image_transition(
    config: RendererConfig,
    mock_pi3d: MagicMock,
    mock_image_renderer: MagicMock,
    mock_text_renderer: MagicMock,
    mock_clock_renderer: MagicMock,
) -> None:
    renderer = Pi3dRenderer(config)
    renderer.start()
    renderer._overlay_config = OverlayConfig(show_clock=False, show_text=True, text_string="Test")
    renderer._animation_controller._state = RenderState.TRANSITIONING
    renderer._animation_controller._image_alpha = 0.5
    renderer._animation_controller._text_alpha = 0.0
    renderer._animation_controller._show_text = True
    renderer._last_text_alpha = 0.0
    renderer._kenburns = False
    mock_clock_renderer.has_changed.return_value = False

    with patch("time.time", return_value=100.0):
        result = renderer.render_frame()

    assert result is True
    mock_image_renderer.draw.assert_called_once()
    mock_text_renderer.set_alpha.assert_called_once_with(0.0)
    mock_text_renderer.draw.assert_not_called()


def test_renderer_skips_text_draw_and_flushes_buffers_after_fade_out(
    config: RendererConfig,
    mock_pi3d: MagicMock,
    mock_image_renderer: MagicMock,
    mock_text_renderer: MagicMock,
    mock_clock_renderer: MagicMock,
) -> None:
    """When text reaches alpha zero, pi3d needs extra clean frames to swap buffers."""
    renderer = Pi3dRenderer(config)
    renderer.start()
    renderer._overlay_config = OverlayConfig(show_clock=False, show_text=True, text_string="Test")
    renderer._animation_controller._state = RenderState.STATIC
    renderer._animation_controller._show_text = True
    renderer._animation_controller._text_alpha = 0.01
    renderer._animation_controller._text_timer = 90.0
    renderer._animation_controller._fps = 60
    renderer._last_text_alpha = 0.01
    renderer._kenburns = False
    mock_clock_renderer.has_changed.return_value = False

    with patch("time.time", return_value=100.0):
        result = renderer.render_frame()

    assert result is True
    mock_image_renderer.draw.assert_called_once()
    mock_text_renderer.set_alpha.assert_called_once_with(0.0)
    mock_text_renderer.draw.assert_not_called()
    assert renderer._animation_controller._frames_to_render == TEXT_CLEAR_REDRAW_FRAMES


def test_renderer_render_frame_not_running(
    config: RendererConfig,
    mock_pi3d: MagicMock,
    mock_image_renderer: MagicMock,
    mock_text_renderer: MagicMock,
    mock_clock_renderer: MagicMock
) -> None:
    """Test rendering when the display loop is not running."""
    renderer = Pi3dRenderer(config)
    renderer.start()
    if renderer._display:
        renderer._display.loop_running.return_value = False

    result = renderer.render_frame()
    assert result is False


@patch("time.sleep")
def test_renderer_render_frame_suspended(
    mock_sleep: MagicMock,
    config: RendererConfig,
    mock_pi3d: MagicMock,
    mock_image_renderer: MagicMock,
    mock_text_renderer: MagicMock,
    mock_clock_renderer: MagicMock
) -> None:
    """Test rendering when suspended (e.g., playing video)."""
    renderer = Pi3dRenderer(config)
    renderer.start()
    renderer._animation_controller._state = RenderState.SUSPENDED

    result = renderer.render_frame()

    assert result is True
    mock_sleep.assert_called_once_with(0.1)


@patch("time.sleep")
def test_renderer_render_frame_static(
    mock_sleep: MagicMock,
    config: RendererConfig,
    mock_pi3d: MagicMock,
    mock_image_renderer: MagicMock,
    mock_text_renderer: MagicMock,
    mock_clock_renderer: MagicMock
) -> None:
    """Test rendering when static (no transitions)."""
    renderer = Pi3dRenderer(config)
    renderer.start()
    renderer._animation_controller._state = RenderState.STATIC
    renderer._animation_controller._frames_to_render = 0
    renderer._kenburns = False
    renderer._last_redraw_time = 100.0
    renderer._last_text_alpha = 0.0
    renderer._overlay_config = OverlayConfig(show_clock=False, show_text=False, text_string="")
    mock_clock_renderer.has_changed.return_value = False

    with patch("time.time", return_value=101.0):
        result = renderer.render_frame()

    assert result is True
    mock_sleep.assert_called_once_with(0.05)
    if renderer._display:
        renderer._display.loop_running.assert_not_called()


@patch("time.sleep")
def test_renderer_normal_transition_completion_ignores_text_hold(
    mock_sleep: MagicMock,
    config: RendererConfig,
    mock_pi3d: MagicMock,
    mock_image_renderer: MagicMock,
    mock_text_renderer: MagicMock,
    mock_clock_renderer: MagicMock,
) -> None:
    publisher = MagicMock()
    renderer = Pi3dRenderer(config, event_publisher=publisher)
    renderer.start()
    renderer._was_transitioning = True
    renderer._video_first_frame_transition = False
    renderer._animation_controller._state = RenderState.STATIC
    renderer._animation_controller._show_text = True
    renderer._animation_controller._text_alpha = 1.0
    renderer._animation_controller._text_timer = 200.0
    renderer._animation_controller._frames_to_render = 0
    renderer._last_text_alpha = 1.0
    renderer._last_redraw_time = 100.0
    renderer._overlay_config = OverlayConfig(
        show_clock=False,
        show_text=True,
        text_string="Photo",
    )
    mock_clock_renderer.has_changed.return_value = False

    with patch("time.time", return_value=101.0):
        result = renderer.render_frame()

    assert result is True
    assert isinstance(publisher.publish.call_args.args[0], TransitionCompletedEvent)
    assert renderer._was_transitioning is False
    mock_sleep.assert_called_once_with(0.05)


@patch("time.sleep")
def test_renderer_video_first_frame_waits_while_text_is_visible(
    mock_sleep: MagicMock,
    config: RendererConfig,
    mock_pi3d: MagicMock,
    mock_image_renderer: MagicMock,
    mock_text_renderer: MagicMock,
    mock_clock_renderer: MagicMock,
) -> None:
    publisher = MagicMock()
    renderer = Pi3dRenderer(config, event_publisher=publisher)
    renderer.start()
    renderer._was_transitioning = True
    renderer._video_first_frame_transition = True
    renderer._animation_controller._state = RenderState.STATIC
    renderer._animation_controller._image_alpha = 1.0
    renderer._animation_controller._show_text = True
    renderer._animation_controller._text_alpha = 1.0
    renderer._animation_controller._text_timer = 200.0
    renderer._animation_controller._frames_to_render = 0
    renderer._last_text_alpha = 1.0
    renderer._last_redraw_time = 100.0
    renderer._overlay_config = OverlayConfig(
        show_clock=False,
        show_text=True,
        text_string="Video",
    )
    mock_clock_renderer.has_changed.return_value = False

    with patch("time.time", return_value=101.0):
        result = renderer.render_frame()

    assert result is True
    publisher.publish.assert_not_called()
    assert renderer._was_transitioning is True
    mock_sleep.assert_called_once_with(0.05)


def test_renderer_video_first_frame_waits_for_clean_redraw_frames(
    config: RendererConfig,
    mock_pi3d: MagicMock,
    mock_image_renderer: MagicMock,
    mock_text_renderer: MagicMock,
    mock_clock_renderer: MagicMock,
) -> None:
    publisher = MagicMock()
    renderer = Pi3dRenderer(config, event_publisher=publisher)
    renderer.start()
    renderer._was_transitioning = True
    renderer._video_first_frame_transition = True
    renderer._animation_controller._state = RenderState.STATIC
    renderer._animation_controller._image_alpha = 1.0
    renderer._animation_controller._show_text = True
    renderer._animation_controller._text_alpha = 0.0
    renderer._animation_controller._frames_to_render = 1
    renderer._last_text_alpha = 0.0
    renderer._last_redraw_time = 100.0
    renderer._overlay_config = OverlayConfig(
        show_clock=False,
        show_text=True,
        text_string="Video",
    )
    mock_clock_renderer.has_changed.return_value = False

    with patch("time.time", return_value=101.0):
        result = renderer.render_frame()

    assert result is True
    publisher.publish.assert_not_called()
    assert renderer._was_transitioning is True
    mock_image_renderer.draw.assert_called_once_with()


@patch("time.sleep")
def test_renderer_video_first_frame_completes_after_text_fade_out(
    mock_sleep: MagicMock,
    config: RendererConfig,
    mock_pi3d: MagicMock,
    mock_image_renderer: MagicMock,
    mock_text_renderer: MagicMock,
    mock_clock_renderer: MagicMock,
) -> None:
    publisher = MagicMock()
    renderer = Pi3dRenderer(config, event_publisher=publisher)
    renderer.start()
    renderer._was_transitioning = True
    renderer._video_first_frame_transition = True
    renderer._animation_controller._state = RenderState.STATIC
    renderer._animation_controller._image_alpha = 1.0
    renderer._animation_controller._show_text = True
    renderer._animation_controller._text_alpha = 0.0
    renderer._animation_controller._frames_to_render = 0
    renderer._last_text_alpha = 0.0
    renderer._last_redraw_time = 100.0
    renderer._overlay_config = OverlayConfig(
        show_clock=False,
        show_text=True,
        text_string="Video",
    )
    mock_clock_renderer.has_changed.return_value = False

    with patch("time.time", return_value=101.0):
        result = renderer.render_frame()

    assert result is True
    assert isinstance(publisher.publish.call_args.args[0], TransitionCompletedEvent)
    assert renderer._was_transitioning is False
    assert renderer._video_first_frame_transition is False
    mock_sleep.assert_called_once_with(0.05)


def test_renderer_enqueue_task(
    config: RendererConfig,
    mock_pi3d: MagicMock,
    mock_image_renderer: MagicMock,
    mock_text_renderer: MagicMock,
    mock_clock_renderer: MagicMock
) -> None:
    """Test enqueueing a task and processing it."""
    renderer = Pi3dRenderer(config)
    renderer.start()
    renderer._animation_controller._state = RenderState.STATIC
    renderer._animation_controller._frames_to_render = 0

    renderer.enqueue_task(1, "clock_tick")
    
    # Process the queue in render_frame
    with patch("time.sleep"):
        renderer.render_frame()

    assert renderer._animation_controller._frames_to_render == 2
    assert renderer._local_queue.empty()
