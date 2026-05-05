"""Unit tests for the ImageRenderer component."""
from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from picframe.core.events.dto import RenderCommand
from picframe.core.renderers.components.image_renderer import ImageRenderer


@pytest.fixture
def mock_pi3d() -> Generator[MagicMock, None, None]:
    """Mock the pi3d module."""
    with patch("picframe.core.renderers.components.image_renderer.pi3d") as mock:
        mock_camera = MagicMock()
        mock_camera.mtrx_made = True
        mock.Camera.instance.return_value = mock_camera
        mock.Camera.return_value = mock_camera
        
        mock_sprite = MagicMock()
        mock_sprite.unif = [0.0] * 60
        mock.Sprite.return_value = mock_sprite
        
        # Mock Display.INSTANCE to avoid AttributeError in Camera initialization
        mock_display_instance = MagicMock()
        mock_display_instance.near = 1.0
        mock_display_instance.far = 1000.0
        mock_display_instance.fov = 45.0
        mock_display_instance.width = 1920
        mock_display_instance.height = 1080
        mock.Display.INSTANCE = mock_display_instance
        
        # Also patch the global pi3d module to catch the internal import in _init_slide
        with patch.dict("sys.modules", {"pi3d": mock}):
            yield mock


@pytest.fixture
def mock_display() -> MagicMock:
    """Mock the pi3d display."""
    display = MagicMock()
    display.width = 1920
    display.height = 1080
    return display


@pytest.fixture
def config() -> dict[str, Any]:
    """Provide a basic configuration."""
    return {
        "blend_type": "blend",
        "edge_alpha": 0.5,
        "fit": False,
        "kenburns": False,
        "time_fade": 2.0,
        "time_delay": 200.0,
        "fps": 20,
        "video_extensions": [".mp4", ".mov", ".avi", ".mkv"]
    }


def test_image_renderer_initialization(
    mock_pi3d: MagicMock, mock_display: MagicMock, config: dict[str, Any]
) -> None:
    """Test that the ImageRenderer initializes correctly."""
    shader = MagicMock()
    renderer = ImageRenderer(mock_display, shader, config)

    assert renderer._blend_type == 0.0
    assert renderer._edge_alpha == 0.5
    assert renderer._fit is False
    assert renderer._kenburns is False
    
    mock_pi3d.Sprite.assert_called_once()
    renderer._slide.set_shader.assert_called_once_with(shader)


def test_image_renderer_execute_video(
    mock_pi3d: MagicMock, mock_display: MagicMock, config: dict[str, Any]
) -> None:
    """Test executing a command with a video file."""
    shader = MagicMock()
    renderer = ImageRenderer(mock_display, shader, config)
    
    command = RenderCommand(image_path="/path/to/video.mp4")
    result = renderer.execute(command)
    
    assert result is False


@patch("picframe.core.renderers.components.image_renderer.Image")
def test_image_renderer_execute_image(
    mock_image: MagicMock, mock_pi3d: MagicMock, mock_display: MagicMock, config: dict[str, Any]
) -> None:
    """Test executing a command with an image file."""
    shader = MagicMock()
    renderer = ImageRenderer(mock_display, shader, config)
    
    mock_img_instance = MagicMock()
    mock_image.open.return_value = mock_img_instance
    
    mock_texture = MagicMock()
    mock_texture.ix = 1920
    mock_texture.iy = 1080
    mock_pi3d.Texture.return_value = mock_texture
    
    command = RenderCommand(image_path="/path/to/image.jpg")
    
    with patch("time.time", return_value=100.0):
        result = renderer.execute(command)
    
    assert result is True
    mock_image.open.assert_called_once_with("/path/to/image.jpg")
    mock_pi3d.Texture.assert_called_once_with(
        mock_img_instance, blend=True, m_repeat=True, free_after_load=True
    )
    assert renderer._next_tm == 100.0 + 200.0
    assert renderer._sfg == mock_texture
    assert renderer._sbg == mock_texture  # First image, so sbg is set to sfg


def test_image_renderer_update_transition(
    mock_pi3d: MagicMock, mock_display: MagicMock, config: dict[str, Any]
) -> None:
    """Test updating the transition state."""
    shader = MagicMock()
    renderer = ImageRenderer(mock_display, shader, config)
    
    renderer._alpha = 0.5
    renderer._delta_alpha = 0.1
    
    result = renderer.update_transition()
    
    assert result is False
    assert renderer._alpha == pytest.approx(0.6)
    
    # Test transition complete
    renderer._alpha = 1.0
    result = renderer.update_transition()
    assert result is True


def test_image_renderer_draw(
    mock_pi3d: MagicMock, mock_display: MagicMock, config: dict[str, Any]
) -> None:
    """Test drawing the image."""
    shader = MagicMock()
    renderer = ImageRenderer(mock_display, shader, config)
    
    renderer.draw()
    
    renderer._slide.draw.assert_called_once()
