"""
Unit tests for the Pi3dRenderer.
"""
from collections.abc import Generator
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

from picframe.core.events.dto import RenderCommand
from picframe.core.renderers.pi3d_renderer import Pi3dRenderer


@pytest.fixture
def mock_pi3d() -> Generator[MagicMock, None, None]:
    """Mock the pi3d module to avoid requiring a real display."""
    with patch("picframe.core.renderers.pi3d_renderer.pi3d") as mock:
        # Setup mock display
        mock_display = MagicMock()
        mock_display.width = 1920
        mock_display.height = 1080
        mock_display.near = 1.0
        mock_display.far = 1000.0
        mock_display.fov = 45.0
        mock_display.loop_running.return_value = True
        mock.Display.create.return_value = mock_display
        mock.Display.INSTANCE = mock_display
        
        # Setup mock camera
        mock_camera = MagicMock()
        mock.Camera.instance.return_value = mock_camera
        
        # Setup mock sprite
        mock_sprite = MagicMock()
        mock_sprite.unif = [0.0] * 60
        mock.Sprite.return_value = mock_sprite
        
        # Setup mock texture
        mock_texture = MagicMock()
        mock_texture.ix = 1920
        mock_texture.iy = 1080
        mock.Texture.return_value = mock_texture
        
        yield mock


@pytest.fixture
def mock_image() -> Generator[MagicMock, None, None]:
    """Mock PIL Image."""
    with patch("picframe.core.renderers.pi3d_renderer.Image") as mock:
        yield mock


@pytest.fixture
def config() -> dict[str, Any]:
    """Default renderer configuration."""
    return {
        "display_x": 0,
        "display_y": 0,
        "display_w": 1920,
        "display_h": 1080,
        "fps": 60,
        "background": (0.0, 0.0, 0.0, 1.0),
        "use_glx": False,
        "use_sdl2": False,
        "shader": "blend_new",
        "blend_type": "blend",
        "edge_alpha": 0.5,
        "fit": False,
        "kenburns": False,
        "time_fade": 2.0,
        "time_delay": 10.0,
    }


def test_renderer_initialization(config: dict[str, Any]) -> None:
    """Test that the renderer initializes with the correct configuration."""
    renderer = Pi3dRenderer(config)
    assert renderer._display_w == 1920
    assert renderer._display_h == 1080
    assert renderer._fps == 60
    assert renderer._blend_type == 0.0
    assert renderer._edge_alpha == 0.5
    assert renderer._fit is False
    assert renderer._kenburns is False


def test_renderer_start_stop(config: dict[str, Any], mock_pi3d: MagicMock) -> None:
    """Test starting and stopping the renderer."""
    renderer = Pi3dRenderer(config)

    # Start
    renderer.start()
    mock_pi3d.Display.create.assert_called_once()
    mock_pi3d.Camera.assert_called_once()
    mock_pi3d.Shader.assert_any_call("blend_new")
    mock_pi3d.Shader.assert_any_call("uv_flat")
    mock_pi3d.Sprite.assert_called_once()
    assert renderer._display is not None
    assert renderer._slide is not None
    
    # Stop
    mock_display = renderer._display
    renderer.stop()
    cast(MagicMock, mock_display).destroy.assert_called_once()
    assert renderer._display is None


def test_renderer_execute_without_start(
    config: dict[str, Any], mock_pi3d: MagicMock, mock_image: MagicMock
) -> None:
    """Test executing a command before starting the renderer."""
    renderer = Pi3dRenderer(config)
    command = RenderCommand(image_path="/path/to/image.jpg")
    
    # Should not raise an exception, but should log a warning
    renderer.execute(command)
    mock_image.open.assert_not_called()


def test_renderer_execute(
    config: dict[str, Any], mock_pi3d: MagicMock, mock_image: MagicMock
) -> None:
    """Test executing a render command."""
    renderer = Pi3dRenderer(config)
    renderer.start()
    
    command = RenderCommand(image_path="/path/to/image.jpg")
    renderer.execute(command)
    
    mock_image.open.assert_called_once_with("/path/to/image.jpg")
    mock_pi3d.Texture.assert_called_once()
    
    # Verify textures were set on the slide
    cast(MagicMock, renderer._slide).set_textures.assert_called_once()
    
    # Verify transition state was reset
    assert renderer._alpha == 0.0
    assert renderer._delta_alpha > 0.0


def test_renderer_render_frame(
    config: dict[str, Any], mock_pi3d: MagicMock, mock_image: MagicMock
) -> None:
    """Test rendering a frame."""
    renderer = Pi3dRenderer(config)
    renderer.start()
    
    # Execute a command to set up the transition
    command = RenderCommand(image_path="/path/to/image.jpg")
    renderer.execute(command)
    
    # Mock pi3d.Camera.instance to return a mock camera
    with patch(
        "picframe.core.renderers.pi3d_renderer.pi3d.Camera.instance"
    ) as mock_camera_instance:
        mock_camera_instance.return_value = MagicMock()
        
        # Also mock pi3d.Display.INSTANCE for the internal pi3d call
        with patch("pi3d.Display.Display.INSTANCE", mock_pi3d.Display.INSTANCE):
            # Render a frame
            result = renderer.render_frame()
    
    assert result is True
    cast(MagicMock, renderer._slide).draw.assert_called_once()
    
    # Alpha should have increased
    assert renderer._alpha > 0.0


def test_renderer_render_frame_not_running(config: dict[str, Any], mock_pi3d: MagicMock) -> None:
    """Test rendering a frame when the display loop is not running."""
    renderer = Pi3dRenderer(config)
    renderer.start()
    
    # Mock loop_running to return False
    cast(MagicMock, renderer._display).loop_running.return_value = False
    
    result = renderer.render_frame()
    
    assert result is False
    cast(MagicMock, renderer._slide).draw.assert_not_called()
