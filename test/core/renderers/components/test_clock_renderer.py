import pytest
from unittest.mock import MagicMock, patch
from picframe.core.renderers.components.clock_renderer import ClockRenderer
from picframe.core.events.dto import OverlayConfig
import time

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
def clock_renderer(mock_display, mock_shader):
    with patch('picframe.core.renderers.components.clock_renderer.pi3d.FixedString') as mock_fixed_string:
        mock_fixed_string.return_value.sprite = MagicMock()
        return ClockRenderer(mock_display, mock_shader, "src/picframe/data/fonts/NotoSans-Regular.ttf")

def test_clock_renderer_initialization(clock_renderer, mock_display):
    assert clock_renderer._display == mock_display
    assert clock_renderer._clock_block is None
    assert clock_renderer._current_time_str == ""

def test_clock_renderer_update_config_show_clock(clock_renderer):
    config = OverlayConfig(show_clock=True, clock_format="%H:%M")
    clock_renderer.update_config(config)
    # It doesn't create the block until draw() is called
    assert clock_renderer._clock_block is None

def test_clock_renderer_update_config_hide_clock(clock_renderer):
    config = OverlayConfig(show_clock=False, clock_format="%H:%M")
    clock_renderer.update_config(config)
    assert clock_renderer._clock_block is None

def test_clock_renderer_draw_updates_time(clock_renderer):
    config = OverlayConfig(show_clock=True, clock_format="%H:%M")
    clock_renderer.update_config(config)
    
    # Mock time to return a specific string
    with patch('picframe.core.renderers.components.clock_renderer.datetime') as mock_datetime:
        mock_datetime.now.return_value.strftime.return_value = "12:00"
        # Mock the draw method to avoid pi3d Camera issues
        with patch('pi3d.Sprite.draw') as mock_draw:
            clock_renderer.draw()
            assert clock_renderer._current_time_str == "12:00"
            # The sprite is created inside draw, so we check the mocked class method
            mock_draw.assert_called_once()

def test_clock_renderer_draw_no_update_if_time_same(clock_renderer):
    config = OverlayConfig(show_clock=True, clock_format="%H:%M")
    clock_renderer.update_config(config)
    
    with patch('picframe.core.renderers.components.clock_renderer.datetime') as mock_datetime:
        mock_datetime.now.return_value.strftime.return_value = "12:00"
        with patch('pi3d.Sprite.draw') as mock_draw:
            clock_renderer.draw()
            mock_draw.reset_mock()
            
            # Draw again with same time
            clock_renderer.draw()
            # It should still draw, but not recreate the sprite
            mock_draw.assert_called_once()


def test_clock_renderer_applies_overlay_style(mock_display, mock_shader):
    with patch('picframe.core.renderers.components.clock_renderer.pi3d.FixedString') as mock_fixed_string:
        mock_fixed_string.return_value.sprite = MagicMock()
        renderer = ClockRenderer(mock_display, mock_shader, "font.ttf")
        renderer.update_config(
            OverlayConfig(
                show_clock=True,
                clock_format="%H:%M",
                clock_justify="L",
                clock_text_sz=72,
                clock_opacity=0.5,
                clock_top_bottom="B",
                clock_wdt_offset_pct=5,
                clock_hgt_offset_pct=10,
            )
        )
        with patch('picframe.core.renderers.components.clock_renderer.datetime') as mock_datetime:
            mock_datetime.now.return_value.strftime.return_value = "12:00"
            renderer.draw()

    kwargs = mock_fixed_string.call_args.kwargs
    assert kwargs["font_size"] == 72
    assert kwargs["justify"] == "L"
    assert kwargs["color"][3] == 127
    assert kwargs["width"] == mock_display.width - (int(mock_display.width * 0.05) * 2)
