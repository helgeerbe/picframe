"""Unit tests for the Pi3dRenderer."""
import queue
from typing import Any, Generator
from unittest.mock import MagicMock, patch

import pytest

from picframe.core.events.dto import OverlayConfig, RenderCommand
from picframe.core.renderers.pi3d_renderer import Pi3dRenderer, RenderState


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
def config() -> dict[str, Any]:
    """Provide a basic configuration for the renderer."""
    return {
        "display_w": 1920,
        "display_h": 1080,
        "fps": 60,
        "background": (0.0, 0.0, 0.0, 1.0),
        "blend_type": "blend",
        "time_delay": 200,
        "time_fade": 2,
        "font_file": "/path/to/font.ttf",
    }


def test_renderer_initialization(config: dict[str, Any]) -> None:
    """Test that the renderer initializes with the correct configuration."""
    renderer = Pi3dRenderer(config)
    assert renderer._display_w == 1920
    assert renderer._display_h == 1080
    assert renderer._fps == 60
    assert renderer._render_state == RenderState.STATIC


def test_renderer_start_stop(
    config: dict[str, Any], 
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


def test_renderer_execute_without_start(
    config: dict[str, Any],
    mock_image_renderer: MagicMock
) -> None:
    """Test executing a command before starting the renderer."""
    renderer = Pi3dRenderer(config)
    command = RenderCommand(image_path="/path/to/image.jpg")
    renderer.execute(command)
    # Should not call image renderer if not started
    mock_image_renderer.execute.assert_not_called()


def test_renderer_execute(
    config: dict[str, Any], 
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
    renderer.execute(command)

    mock_image_renderer.execute.assert_called_once_with(command)
    assert renderer._render_state == RenderState.TRANSITIONING
    assert renderer._overlay_config.text_string == "Test"


def test_renderer_execute_video(
    config: dict[str, Any],
    mock_pi3d: MagicMock,
    mock_image_renderer: MagicMock
) -> None:
    """Test executing a render command for a video."""
    renderer = Pi3dRenderer(config)
    renderer.start()

    # Mock ImageRenderer.execute to return False for video
    mock_image_renderer.execute.return_value = False

    command = RenderCommand(image_path="/path/to/video.mp4")
    renderer.execute(command)

    mock_image_renderer.execute.assert_not_called()
    assert renderer._render_state == RenderState.SUSPENDED


def test_renderer_render_frame(
    config: dict[str, Any], 
    mock_pi3d: MagicMock,
    mock_image_renderer: MagicMock,
    mock_text_renderer: MagicMock,
    mock_clock_renderer: MagicMock
) -> None:
    """Test rendering a frame."""
    renderer = Pi3dRenderer(config)
    renderer.start()
    
    # Set state to transitioning
    renderer._render_state = RenderState.TRANSITIONING
    mock_image_renderer.update_transition.return_value = True

    with patch("time.time", return_value=100.0):
        result = renderer.render_frame()

    assert result is True
    mock_image_renderer.update_transition.assert_called_once()
    mock_image_renderer.draw.assert_called_once()
    # Should transition to TEXT_ANIMATING
    assert renderer._render_state == RenderState.TEXT_ANIMATING


def test_renderer_render_frame_not_running(
    config: dict[str, Any],
    mock_pi3d: MagicMock,
    mock_image_renderer: MagicMock,
    mock_text_renderer: MagicMock,
    mock_clock_renderer: MagicMock
) -> None:
    """Test rendering when the display loop is not running."""
    renderer = Pi3dRenderer(config)
    renderer.start()
    renderer._display.loop_running.return_value = False

    result = renderer.render_frame()
    assert result is False


@patch("time.sleep")
def test_renderer_render_frame_suspended(
    mock_sleep: MagicMock,
    config: dict[str, Any],
    mock_pi3d: MagicMock,
    mock_image_renderer: MagicMock,
    mock_text_renderer: MagicMock,
    mock_clock_renderer: MagicMock
) -> None:
    """Test rendering when suspended (e.g., playing video)."""
    renderer = Pi3dRenderer(config)
    renderer.start()
    renderer._render_state = RenderState.SUSPENDED

    result = renderer.render_frame()

    assert result is True
    mock_sleep.assert_called_once_with(0.1)


@patch("time.sleep")
def test_renderer_render_frame_static(
    mock_sleep: MagicMock,
    config: dict[str, Any],
    mock_pi3d: MagicMock,
    mock_image_renderer: MagicMock,
    mock_text_renderer: MagicMock,
    mock_clock_renderer: MagicMock
) -> None:
    """Test rendering when static (no transitions)."""
    renderer = Pi3dRenderer(config)
    renderer.start()
    renderer._render_state = RenderState.STATIC
    renderer._frames_to_render = 0
    renderer._kenburns = False

    result = renderer.render_frame()

    assert result is True
    mock_sleep.assert_called_once_with(0.1)


def test_renderer_enqueue_task(
    config: dict[str, Any],
    mock_pi3d: MagicMock,
    mock_image_renderer: MagicMock,
    mock_text_renderer: MagicMock,
    mock_clock_renderer: MagicMock
) -> None:
    """Test enqueueing a task and processing it."""
    renderer = Pi3dRenderer(config)
    renderer.start()
    renderer._render_state = RenderState.STATIC
    renderer._frames_to_render = 0

    renderer.enqueue_task(1, "clock_tick")
    
    # Process the queue in render_frame
    with patch("time.sleep"):
        renderer.render_frame()

    assert renderer._frames_to_render == 1
    assert renderer._local_queue.empty()
