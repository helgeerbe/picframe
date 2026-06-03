import pytest
from unittest.mock import MagicMock, patch
from picframe.core.renderers.components.text_renderer import TextRenderer
from picframe.core.events.dto import OverlayConfig

@pytest.fixture
def mock_display():
    display = MagicMock()
    display.width = 1920
    display.height = 1080
    return display

@pytest.fixture
def mock_shader():
    return MagicMock()

@pytest.fixture
def text_renderer(mock_display, mock_shader):
    with patch('picframe.core.renderers.components.text_renderer.pi3d.FixedString') as mock_fixed_string:
        mock_fixed_string.return_value.sprite = MagicMock()
        return TextRenderer(mock_display, mock_shader, "src/picframe/data/fonts/NotoSans-Regular.ttf")

def test_text_renderer_initialization(text_renderer, mock_display):
    assert text_renderer._display == mock_display
    assert text_renderer._text_block is None
    assert text_renderer._current_text == ""

def test_text_renderer_update_config_show_text(text_renderer):
    config = OverlayConfig(show_text=True, text_string="Test String")
    text_renderer.update_config(config)
    assert text_renderer._text_block is not None

def test_text_renderer_update_config_hide_text(text_renderer):
    config = OverlayConfig(show_text=False, text_string="Test String")
    text_renderer.update_config(config)
    assert text_renderer._text_block is None

def test_text_renderer_set_alpha(text_renderer):
    config = OverlayConfig(show_text=True, text_string="Test String")
    text_renderer.update_config(config)
    with patch.object(text_renderer._text_block.sprite, 'set_alpha') as mock_set_alpha:
        text_renderer.set_alpha(0.5)
        mock_set_alpha.assert_called_once_with(0.5)

def test_text_renderer_draw(text_renderer):
    config = OverlayConfig(show_text=True, text_string="Test String")
    text_renderer.update_config(config)
    # Mock the draw method to avoid pi3d Camera issues
    with patch.object(text_renderer._text_block.sprite, 'draw') as mock_draw:
        text_renderer.draw()
        mock_draw.assert_called_once()


def test_text_renderer_pair_text_blocks(text_renderer):
    config = OverlayConfig(show_text=True, text_string="Left", text_strings=("Left", "Right"))
    text_renderer.update_config(config)

    assert len(text_renderer._text_blocks) == 2


def test_text_renderer_draws_pair_text_blocks(text_renderer):
    config = OverlayConfig(show_text=True, text_string="Left", text_strings=("Left", "Right"))
    text_renderer.update_config(config)

    assert len(text_renderer._text_blocks) == 2
    draw_mocks = [
        patch.object(text_block.sprite, "draw")
        for text_block in text_renderer._text_blocks
    ]

    with draw_mocks[0] as left_draw, draw_mocks[1] as right_draw:
        text_renderer.draw()

    left_draw.assert_called_once()
    right_draw.assert_called_once()
