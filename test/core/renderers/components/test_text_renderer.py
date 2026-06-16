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


def test_text_renderer_applies_overlay_style(mock_display, mock_shader):
    with patch('picframe.core.renderers.components.text_renderer.pi3d.FixedString') as mock_fixed_string:
        mock_fixed_string.return_value.sprite = MagicMock()
        renderer = TextRenderer(mock_display, mock_shader, "font.ttf")
        renderer.update_config(
            OverlayConfig(
                show_text=True,
                text_string="Styled",
                show_text_sz=54,
                text_justify="R",
                text_opacity=0.5,
                text_bkg_hgt=0.2,
                text_x_margin=30,
                text_y_margin=12,
            )
        )

    kwargs = mock_fixed_string.call_args.kwargs
    assert kwargs["font_size"] == 54
    assert kwargs["justify"] == "R"
    assert kwargs["color"][3] == 127
    assert kwargs["background_color"] is not None
    expected_margin = max(30, (int(mock_display.height * 0.2) - 54) // 2)
    assert kwargs["width"] == mock_display.width - (expected_margin * 2)


def test_text_renderer_positions_text_inside_render_rect(mock_display, mock_shader):
    with patch('picframe.core.renderers.components.text_renderer.pi3d.FixedString') as mock_fixed_string:
        sprite = MagicMock()
        sprite.height = 50
        mock_fixed_string.return_value.sprite = sprite
        renderer = TextRenderer(
            mock_display,
            mock_shader,
            "font.ttf",
            render_rect=(0, 0, 1000, 900),
        )
        renderer.update_config(
            OverlayConfig(
                show_text=True,
                text_string="Viewport",
                text_y_margin=12,
            )
        )

    kwargs = mock_fixed_string.call_args.kwargs
    assert kwargs["width"] == 800
    sprite.position.assert_called_once_with(-460.0, -323.0, 0.1)


def test_text_renderer_rebuilds_when_style_changes_for_same_text(mock_display, mock_shader):
    with patch('picframe.core.renderers.components.text_renderer.pi3d.FixedString') as mock_fixed_string:
        mock_fixed_string.return_value.sprite = MagicMock()
        renderer = TextRenderer(mock_display, mock_shader, "font.ttf")

        renderer.update_config(
            OverlayConfig(show_text=True, text_string="Styled", show_text_sz=40)
        )
        renderer.update_config(
            OverlayConfig(show_text=True, text_string="Styled", show_text_sz=64)
        )

    assert mock_fixed_string.call_count == 2
    assert mock_fixed_string.call_args_list[0].kwargs["font_size"] == 40
    assert mock_fixed_string.call_args_list[1].kwargs["font_size"] == 64
