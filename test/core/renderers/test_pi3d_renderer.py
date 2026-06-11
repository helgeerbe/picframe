"""Unit tests for the Pi3dRenderer."""
import os
import queue
import signal
from typing import Any, Generator
from unittest.mock import MagicMock, patch

import pytest

from picframe.core.events.dto import (
    OverlayConfig,
    RENDER_PARK_VIDEO_REVEAL,
    RENDER_PRELOAD_VIDEO_REVEAL,
    RENDER_PROMOTE_VIDEO_REVEAL,
    RenderCommand,
    RendererConfigUpdatedEvent,
)
from picframe.core.renderers.pi3d_renderer import (
    PI3D_LABWC_IDENTIFIER,
    RESUME_REDRAW_FRAMES,
    VIDEO_WINDOW_TITLE,
    Pi3dRenderer,
)
from picframe.core.renderers.animation_controller import RenderState


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


from picframe.core.events.dto import RendererConfig

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


def test_renderer_get_display_rect_prefers_configured_geometry(
    mock_pi3d: MagicMock,
    mock_image_renderer: MagicMock,
    mock_text_renderer: MagicMock,
    mock_clock_renderer: MagicMock,
) -> None:
    """Configured pi3d geometry is the contract for matching video overlays."""
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

    assert renderer.get_display_rect() == (100, 80, 1800, 1000)


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

    assert renderer._animation_controller._state == RenderState.SUSPENDED
    mock_image_renderer.execute.assert_not_called()


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

    updated = RendererConfig(
        display_w=1920,
        display_h=1080,
        fps=30,
        background=(0.1, 0.1, 0.1, 1.0),
        blend_type="blend",
        time_delay=30.0,
        time_fade=1.0,
        font_file="/path/to/font.ttf",
        fit=True,
        kenburns=True,
    )

    renderer._handle_config_event(RendererConfigUpdatedEvent(config=updated))

    mock_image_renderer.update_config.assert_called_with(updated)
    assert renderer._kenburns is True
    assert renderer._animation_controller._fps == 30
    assert renderer._animation_controller._time_delay == 30.0


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
