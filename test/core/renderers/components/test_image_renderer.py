"""Unit tests for the ImageRenderer component."""

from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from picframe.core.events.dto import RenderCommand
from picframe.core.exceptions import MediaProcessingError
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
        mock.Texture.return_value = MagicMock(ix=1920, iy=1080)

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
        "video_extensions": [".mp4", ".mov", ".avi", ".mkv"],
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
    if renderer._slide:
        renderer._slide.set_shader.assert_called_once_with(shader)


def test_image_renderer_initializes_background_texture(
    mock_pi3d: MagicMock, mock_display: MagicMock, config: dict[str, Any]
) -> None:
    shader = MagicMock()
    renderer = ImageRenderer(
        mock_display,
        shader,
        {**config, "background": (0.2, 0.4, 0.6, 1.0)},
    )

    texture_image = mock_pi3d.Texture.call_args.args[0]
    assert isinstance(texture_image, Image.Image)
    assert texture_image.size == (1920, 1080)
    assert texture_image.getpixel((0, 0)) == (51, 102, 153)
    if renderer._slide:
        renderer._slide.set_textures.assert_called()


def test_image_renderer_render_rect_positions_slide_and_sets_size(
    mock_pi3d: MagicMock, mock_display: MagicMock, config: dict[str, Any]
) -> None:
    shader = MagicMock()
    renderer = ImageRenderer(
        mock_display,
        shader,
        config,
        render_rect=(0, 0, 1000, 900),
    )

    mock_pi3d.Sprite.assert_called_once()
    assert mock_pi3d.Sprite.call_args.kwargs["w"] == 1000
    assert mock_pi3d.Sprite.call_args.kwargs["h"] == 900
    if renderer._slide:
        renderer._slide.position.assert_called_once_with(-460.0, 90.0, 5.0)


def test_image_renderer_initialization_honors_fit_true(
    mock_pi3d: MagicMock, mock_display: MagicMock, config: dict[str, Any]
) -> None:
    """Test that fit=True is honored when initializing from config."""
    shader = MagicMock()
    renderer = ImageRenderer(mock_display, shader, {**config, "fit": True})

    assert renderer._fit is True


def test_image_renderer_update_config_refreshes_fit(
    mock_pi3d: MagicMock, mock_display: MagicMock, config: dict[str, Any]
) -> None:
    """Test that runtime config changes refresh image scaling settings."""
    shader = MagicMock()
    renderer = ImageRenderer(mock_display, shader, config)

    renderer.update_config(
        {
            **config,
            "blend_type": "burn",
            "edge_alpha": 0.25,
            "fit": True,
            "time_delay": 30.0,
        }
    )

    assert renderer._fit is True
    assert renderer._time_delay == 30.0
    if renderer._slide:
        assert renderer._slide.unif[47] == 0.25
        assert renderer._slide.unif[54] == 1.0


def test_image_renderer_update_config_rescales_current_texture(
    mock_pi3d: MagicMock, mock_display: MagicMock, config: dict[str, Any]
) -> None:
    """Test that fit changes rescale an already-loaded portrait texture."""
    shader = MagicMock()
    renderer = ImageRenderer(mock_display, shader, config)
    renderer._sfg = MagicMock(ix=600, iy=1200)

    renderer.update_config({**config, "fit": True})

    expected_wh_ratio = (1920 * 1200) / (1080 * 600)
    if renderer._slide:
        assert renderer._slide.unif[42] == pytest.approx(expected_wh_ratio)
        assert renderer._slide.unif[43] == 1.0
        assert renderer._slide.unif[48] == pytest.approx((expected_wh_ratio - 1.0) * 0.5)
        assert renderer._slide.unif[49] == 0.0


def test_image_renderer_execute_video(
    mock_pi3d: MagicMock, mock_display: MagicMock, config: dict[str, Any]
) -> None:
    """Test executing a command with a video file."""
    shader = MagicMock()
    renderer = ImageRenderer(mock_display, shader, config)

    command = RenderCommand(image_path="/path/to/video.mp4")
    result = renderer.execute(command)

    assert result == (False, 0.0, 0.0)


@patch("picframe.core.renderers.components.image_preparer.Image.open")
def test_image_renderer_execute_image_error(
    mock_image_open: MagicMock,
    mock_pi3d: MagicMock,
    mock_display: MagicMock,
    config: dict[str, Any],
) -> None:
    """Test executing a command with an image file that fails to load."""
    shader = MagicMock()
    renderer = ImageRenderer(mock_display, shader, config)

    mock_image_open.side_effect = Exception("Failed to load image")

    command = RenderCommand(image_path="/path/to/image.jpg")

    with pytest.raises(MediaProcessingError) as exc_info:
        renderer.execute(command)

    assert "Failed to load image /path/to/image.jpg" in str(exc_info.value)


def test_image_renderer_execute_image(
    mock_pi3d: MagicMock,
    mock_display: MagicMock,
    config: dict[str, Any],
    tmp_path: Path,
) -> None:
    """Test executing a command with an image file."""
    shader = MagicMock()
    renderer = ImageRenderer(mock_display, shader, config)

    image_path = tmp_path / "image.jpg"
    Image.new("RGB", (1920, 1080), "red").save(image_path)

    mock_texture = MagicMock()
    mock_texture.ix = 1920
    mock_texture.iy = 1080
    mock_pi3d.Texture.return_value = mock_texture

    command = RenderCommand(image_path=str(image_path))

    with patch("time.time", return_value=100.0):
        result = renderer.execute(command)

    assert result == (True, 0.0, 0.0)
    texture_image = mock_pi3d.Texture.call_args.args[0]
    assert isinstance(texture_image, Image.Image)
    assert texture_image.size == (1920, 1080)
    assert mock_pi3d.Texture.call_args.kwargs == {
        "blend": True,
        "m_repeat": True,
        "free_after_load": True,
    }
    assert renderer._next_tm == 100.0 + 200.0
    assert renderer._sfg == mock_texture
    assert renderer._sbg is not None
    assert renderer._sbg != mock_texture


def test_image_renderer_does_not_mat_preloaded_video_frame(
    mock_pi3d: MagicMock, mock_display: MagicMock, config: dict[str, Any]
) -> None:
    """Preloaded video transition frames stay unmatted even if matting is enabled."""
    shader = MagicMock()
    renderer = ImageRenderer(mock_display, shader, {**config, "mat_images": "on"})
    frame = Image.new("RGB", (320, 180), "black")

    mock_texture = MagicMock()
    mock_texture.ix = 320
    mock_texture.iy = 180
    mock_pi3d.Texture.return_value = mock_texture

    result = renderer.execute(RenderCommand(image_path="/tmp/generated.frame", image_obj=frame))

    assert result == (True, 0.0, 0.0)
    texture_image = mock_pi3d.Texture.call_args.args[0]
    assert isinstance(texture_image, Image.Image)
    assert texture_image.size == (320, 180)


def test_image_renderer_preloads_video_reveal_without_changing_visible_textures(
    mock_pi3d: MagicMock, mock_display: MagicMock, config: dict[str, Any]
) -> None:
    shader = MagicMock()
    renderer = ImageRenderer(mock_display, shader, config)
    first_texture = MagicMock(ix=1920, iy=1080)
    reveal_texture = MagicMock(ix=640, iy=180)
    mock_pi3d.Texture.side_effect = [first_texture, reveal_texture]

    renderer.execute(
        RenderCommand(
            image_path="/cache/video.1.frame",
            image_obj=Image.new("RGB", (1920, 1080), "red"),
        )
    )
    if renderer._slide:
        renderer._slide.set_textures.reset_mock()

    result = renderer.preload_video_reveal_texture(
        RenderCommand(
            image_path="/cache/video.2.frame",
            image_obj=Image.new("RGB", (640, 180), "blue"),
        )
    )

    assert result is True
    assert renderer._sfg == first_texture
    assert renderer._sbg is not None
    assert renderer._sbg != reveal_texture
    assert renderer._video_reveal_texture == reveal_texture
    if renderer._slide:
        renderer._slide.set_textures.assert_not_called()


def test_image_renderer_promotes_preloaded_video_reveal_texture(
    mock_pi3d: MagicMock, mock_display: MagicMock, config: dict[str, Any]
) -> None:
    shader = MagicMock()
    renderer = ImageRenderer(mock_display, shader, config)
    first_texture = MagicMock(ix=1920, iy=1080)
    reveal_texture = MagicMock(ix=640, iy=180)
    mock_pi3d.Texture.side_effect = [first_texture, reveal_texture]

    renderer.execute(
        RenderCommand(
            image_path="/cache/video.1.frame",
            image_obj=Image.new("RGB", (1920, 1080), "red"),
        )
    )
    renderer.preload_video_reveal_texture(
        RenderCommand(
            image_path="/cache/video.2.frame",
            image_obj=Image.new("RGB", (640, 180), "blue"),
        )
    )
    if renderer._slide:
        renderer._slide.set_textures.reset_mock()

    result = renderer.promote_video_reveal_texture()

    assert result is True
    assert renderer._sfg == reveal_texture
    assert renderer._sbg == first_texture
    assert renderer._video_reveal_texture is None
    assert renderer._video_reveal_scale is None
    if renderer._slide:
        renderer._slide.set_textures.assert_called_once_with([reveal_texture, first_texture])
        assert renderer._slide.unif[42] == pytest.approx(0.5)
        assert renderer._slide.unif[43] == 1.0
        assert renderer._slide.unif[48] == pytest.approx(-0.25)
        assert renderer._slide.unif[49] == 0.0
        assert renderer._slide.unif[44] == 1.0


def test_image_renderer_normal_execute_clears_stale_video_reveal(
    mock_pi3d: MagicMock, mock_display: MagicMock, config: dict[str, Any]
) -> None:
    shader = MagicMock()
    renderer = ImageRenderer(mock_display, shader, config)
    renderer._video_reveal_texture = MagicMock()
    renderer._video_reveal_scale = (1.0, 1.0, 0.0, 0.0)
    mock_pi3d.Texture.return_value = MagicMock(ix=1920, iy=1080)

    renderer.execute(
        RenderCommand(
            image_path="/cache/image.frame",
            image_obj=Image.new("RGB", (1920, 1080), "red"),
        )
    )

    assert renderer._video_reveal_texture is None
    assert renderer._video_reveal_scale is None


def test_image_renderer_create_portrait_pair_image() -> None:
    left = Image.new("RGB", (400, 800), "red")
    right = Image.new("RGB", (200, 600), "blue")

    result = ImageRenderer._create_portrait_pair_image(left, right)

    assert result.mode == "RGB"
    assert result.width == 408
    assert result.height == 400


def test_image_renderer_set_alpha(
    mock_pi3d: MagicMock, mock_display: MagicMock, config: dict[str, Any]
) -> None:
    """Test setting the alpha value."""
    shader = MagicMock()
    renderer = ImageRenderer(mock_display, shader, config)

    renderer.set_alpha(0.6)

    if renderer._slide:
        assert renderer._slide.unif[44] == pytest.approx(0.6 * 0.6 * (3.0 - 2.0 * 0.6))


def test_image_renderer_draw(
    mock_pi3d: MagicMock, mock_display: MagicMock, config: dict[str, Any]
) -> None:
    """Test drawing the image."""
    shader = MagicMock()
    renderer = ImageRenderer(mock_display, shader, config)

    renderer.draw()

    if renderer._slide:
        renderer._slide.draw.assert_called_once()
