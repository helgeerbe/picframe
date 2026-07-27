from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from picframe.core.events.dto import OverlayConfig
from picframe.core.renderers.components.text_renderer import TextRenderer

FIXED_STRING_PATCH = "picframe.core.renderers.components.text_renderer.pi3d.FixedString"
SPRITE_PATCH = "picframe.core.renderers.components.text_renderer.pi3d.Sprite"
TEXTURE_PATCH = "picframe.core.renderers.components.text_renderer.pi3d.Texture"
CAMERA_PATCH = "picframe.core.renderers.components.text_renderer.pi3d.Camera"


@contextmanager
def mock_pi3d_text_components():
    """Patch pi3d components needed by TextRenderer including gradient sprites."""
    with (
        patch(FIXED_STRING_PATCH) as mock_fixed_string,
        patch(SPRITE_PATCH),
        patch(TEXTURE_PATCH),
        patch(CAMERA_PATCH) as mock_camera,
    ):
        mock_fixed_string.return_value.sprite = MagicMock()
        mock_camera.instance.return_value = MagicMock()
        mock_camera.return_value = MagicMock()
        yield mock_fixed_string


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
def text_renderer(mock_display, mock_shader, monkeypatch):
    mock_fixed_string = MagicMock()
    mock_fixed_string.return_value.sprite = MagicMock()
    monkeypatch.setattr(
        "picframe.core.renderers.components.text_renderer.pi3d.FixedString",
        mock_fixed_string,
    )
    monkeypatch.setattr(
        "picframe.core.renderers.components.text_renderer.pi3d.Sprite",
        MagicMock(),
    )
    monkeypatch.setattr(
        "picframe.core.renderers.components.text_renderer.pi3d.Texture",
        MagicMock(),
    )
    mock_camera = MagicMock()
    mock_camera.instance.return_value = MagicMock()
    monkeypatch.setattr(
        "picframe.core.renderers.components.text_renderer.pi3d.Camera",
        mock_camera,
    )
    return TextRenderer(
        mock_display,
        mock_shader,
        "src/picframe/data/fonts/NotoSans-Regular.ttf",
    )


def test_text_renderer_initialization(text_renderer, mock_display):
    assert text_renderer._display == mock_display
    assert text_renderer._text_block is None
    assert text_renderer._current_text == ""
    assert text_renderer._background_sprites == []


def test_text_renderer_update_config_show_text(text_renderer):
    config = OverlayConfig(show_text=True, text_string="Test String")
    text_renderer.update_config(config)
    assert text_renderer._text_block is not None


def test_text_renderer_update_config_hide_text(text_renderer):
    config = OverlayConfig(show_text=False, text_string="Test String")
    text_renderer.update_config(config)
    assert text_renderer._text_block is None
    assert text_renderer._background_sprites == []


def test_text_renderer_status_text_shows_when_metadata_hidden(mock_display, mock_shader):
    with mock_pi3d_text_components() as mock_fixed_string:
        renderer = TextRenderer(mock_display, mock_shader, "font.ttf")

        renderer.update_config(
            OverlayConfig(
                show_text=False,
                text_string="Metadata",
                status_text="PAUSED",
            )
        )

    assert mock_fixed_string.call_count == 1
    assert mock_fixed_string.call_args.args[1] == "PAUSED"


def test_text_renderer_status_text_is_single_center_overlay_for_pairs(
    mock_display,
    mock_shader,
):
    with mock_pi3d_text_components() as mock_fixed_string:
        text_blocks = []
        for height in (40, 40, 54):
            text_block = MagicMock()
            text_block.sprite = MagicMock()
            text_block.sprite.height = height
            text_blocks.append(text_block)
        mock_fixed_string.side_effect = text_blocks
        renderer = TextRenderer(mock_display, mock_shader, "font.ttf")

        renderer.update_config(
            OverlayConfig(
                show_text=True,
                text_string="Left",
                text_strings=("Left", "Right"),
                status_text="PAUSED",
            )
        )

    rendered_texts = [call.args[1] for call in mock_fixed_string.call_args_list]
    assert rendered_texts == ["Left", "Right", "PAUSED"]
    text_blocks[2].sprite.position.assert_called_once_with(0.0, 0.0, 0.2)


def test_text_renderer_set_alpha(text_renderer):
    config = OverlayConfig(show_text=True, text_string="Test String")
    text_renderer.update_config(config)
    with patch.object(text_renderer._text_block.sprite, "set_alpha") as mock_set_alpha:
        text_renderer.set_alpha(0.5)
        mock_set_alpha.assert_called_once_with(0.5)


def test_text_renderer_set_alpha_propagates_to_background_sprites(text_renderer):
    config = OverlayConfig(show_text=True, text_string="Test String")
    text_renderer.update_config(config)
    assert len(text_renderer._background_sprites) > 0
    with (
        patch.object(text_renderer._text_block.sprite, "set_alpha"),
        patch.object(text_renderer._background_sprites[0], "set_alpha") as mock_bg_alpha,
    ):
        text_renderer.set_alpha(0.7)
        mock_bg_alpha.assert_called_once_with(0.7)


def test_text_renderer_draw(text_renderer):
    config = OverlayConfig(show_text=True, text_string="Test String")
    text_renderer.update_config(config)
    # Mock the draw method to avoid pi3d Camera issues
    with patch.object(text_renderer._text_block.sprite, "draw") as mock_draw:
        text_renderer.draw()
        mock_draw.assert_called_once()


def test_text_renderer_draws_background_before_text(text_renderer):
    config = OverlayConfig(show_text=True, text_string="Test String")
    text_renderer.update_config(config)
    assert len(text_renderer._background_sprites) > 0

    call_order = []
    bg_draw = patch.object(
        text_renderer._background_sprites[0], "draw", side_effect=lambda: call_order.append("bg")
    )
    text_draw = patch.object(
        text_renderer._text_block.sprite, "draw", side_effect=lambda: call_order.append("text")
    )

    with bg_draw, text_draw:
        text_renderer.draw()

    assert call_order == ["bg", "text"]


def test_text_renderer_pair_text_blocks(text_renderer):
    config = OverlayConfig(show_text=True, text_string="Left", text_strings=("Left", "Right"))
    text_renderer.update_config(config)

    assert len(text_renderer._text_blocks) == 2


def test_text_renderer_draws_pair_text_blocks(mock_display, mock_shader):
    with mock_pi3d_text_components() as mock_fixed_string:
        # Distinct FixedString instances for each text block
        block1 = MagicMock()
        block1.sprite = MagicMock()
        block2 = MagicMock()
        block2.sprite = MagicMock()
        mock_fixed_string.side_effect = [block1, block2]
        renderer = TextRenderer(mock_display, mock_shader, "font.ttf")
        renderer.update_config(
            OverlayConfig(show_text=True, text_string="Left", text_strings=("Left", "Right"))
        )

        assert len(renderer._text_blocks) == 2
        with (
            patch.object(block1.sprite, "draw") as left_draw,
            patch.object(block2.sprite, "draw") as right_draw,
        ):
            renderer.draw()

        left_draw.assert_called_once()
        right_draw.assert_called_once()


def test_text_renderer_applies_overlay_style(mock_display, mock_shader):
    with mock_pi3d_text_components() as mock_fixed_string:
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
    # Gradient replaces the solid background_color band — FixedString no longer gets one
    assert kwargs["background_color"] is None
    expected_margin = max(30, (int(mock_display.height * 0.2) - 54) // 2)
    assert kwargs["width"] == mock_display.width - (expected_margin * 2)


def test_text_renderer_positions_text_inside_render_rect(mock_display, mock_shader):
    with mock_pi3d_text_components() as mock_fixed_string:
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
    # y_margin scales with font_size: 12 + 40//4 = 22
    # justify_x_offset for L: -1000 * 0.02 = -20.0
    sprite.position.assert_called_once_with(-480.0, -313.0, 0.1)


def test_text_renderer_rebuilds_when_style_changes_for_same_text(mock_display, mock_shader):
    with mock_pi3d_text_components() as mock_fixed_string:
        renderer = TextRenderer(mock_display, mock_shader, "font.ttf")

        renderer.update_config(OverlayConfig(show_text=True, text_string="Styled", show_text_sz=40))
        renderer.update_config(OverlayConfig(show_text=True, text_string="Styled", show_text_sz=64))

    assert mock_fixed_string.call_count == 2
    assert mock_fixed_string.call_args_list[0].kwargs["font_size"] == 40
    assert mock_fixed_string.call_args_list[1].kwargs["font_size"] == 64


def test_text_renderer_creates_gradient_sprite_when_bkg_enabled(mock_display, mock_shader):
    with (
        mock_pi3d_text_components(),
        patch(SPRITE_PATCH) as mock_sprite,
        patch(TEXTURE_PATCH) as mock_texture,
    ):
        renderer = TextRenderer(mock_display, mock_shader, "font.ttf")
        renderer.update_config(
            OverlayConfig(
                show_text=True,
                text_string="With Gradient",
                text_bkg_hgt=0.3,
            )
        )

    assert mock_texture.call_count == 1
    assert mock_sprite.call_count == 1
    assert len(renderer._background_sprites) == 1


def test_text_renderer_no_gradient_sprite_when_bkg_disabled(mock_display, mock_shader):
    with (
        mock_pi3d_text_components(),
        patch(SPRITE_PATCH) as mock_sprite,
        patch(TEXTURE_PATCH) as mock_texture,
    ):
        renderer = TextRenderer(mock_display, mock_shader, "font.ttf")
        renderer.update_config(
            OverlayConfig(
                show_text=True,
                text_string="No Gradient",
                text_bkg_hgt=0.0,
            )
        )

    mock_texture.assert_not_called()
    mock_sprite.assert_not_called()
    assert len(renderer._background_sprites) == 0


def test_text_renderer_gradient_texture_uses_numpy_linspace(mock_display, mock_shader):
    # Compute the return value before patching np.linspace
    preset_values = np.linspace(0, 255, 216, dtype=np.float32)
    with (
        mock_pi3d_text_components(),
        patch(TEXTURE_PATCH) as mock_texture,
        patch("picframe.core.renderers.components.text_renderer.np.linspace") as mock_linspace,
    ):
        mock_linspace.return_value = preset_values
        renderer = TextRenderer(mock_display, mock_shader, "font.ttf")
        renderer.update_config(
            OverlayConfig(
                show_text=True,
                text_string="Gradient",
                text_bkg_hgt=0.2,
            )
        )

    mock_linspace.assert_called_once()
    args = mock_linspace.call_args.args
    assert args[0] == 0.0
    # max_alpha * brightness = int(255 * 0.45) * 1.0 = 114
    assert args[1] == 114
    # Height of band = int(1080 * 0.2) = 216
    assert args[2] == 216
    mock_texture.assert_called_once()


def test_text_renderer_gradient_sprite_uses_uv_flat_shader(mock_display, mock_shader):
    mock_shader_obj = MagicMock()
    with (
        mock_pi3d_text_components(),
        patch(SPRITE_PATCH) as mock_sprite,
    ):
        mock_sprite.return_value = MagicMock()
        renderer = TextRenderer(mock_display, mock_shader_obj, "font.ttf")
        renderer.update_config(
            OverlayConfig(
                show_text=True,
                text_string="Shader Test",
                text_bkg_hgt=0.25,
            )
        )

    # The gradient sprite must use the same shader passed to TextRenderer
    # (which is uv_flat in production)
    mock_sprite.return_value.set_shader.assert_called_once_with(mock_shader_obj)


def test_text_renderer_justify_offset_applies_to_non_pair_text(mock_display, mock_shader):
    with mock_pi3d_text_components() as mock_fixed_string:
        sprite = MagicMock()
        sprite.height = 40
        mock_fixed_string.return_value.sprite = sprite
        renderer = TextRenderer(mock_display, mock_shader, "font.ttf")

        # Right justify: x offset = +render_w * 0.02
        renderer.update_config(
            OverlayConfig(
                show_text=True,
                text_string="Right Text",
                text_justify="R",
                text_bkg_hgt=0.0,
            )
        )

    # render_w = 1920, offset = 1920 * 0.02 = 38.4
    # render_center_x = 0.0, x = 0.0 + 38.4 = 38.4
    called_x = sprite.position.call_args.args[0]
    assert called_x == pytest.approx(38.4, abs=0.01)


def test_text_renderer_justify_offset_not_applied_for_center(mock_display, mock_shader):
    with mock_pi3d_text_components() as mock_fixed_string:
        sprite = MagicMock()
        sprite.height = 40
        mock_fixed_string.return_value.sprite = sprite
        renderer = TextRenderer(mock_display, mock_shader, "font.ttf")

        renderer.update_config(
            OverlayConfig(
                show_text=True,
                text_string="Center Text",
                text_justify="C",
                text_bkg_hgt=0.0,
            )
        )

    called_x = sprite.position.call_args.args[0]
    assert called_x == 0.0


def test_text_renderer_y_margin_scales_with_font_size(mock_display, mock_shader):
    with mock_pi3d_text_components() as mock_fixed_string:
        sprite = MagicMock()
        sprite.height = 60
        mock_fixed_string.return_value.sprite = sprite
        renderer = TextRenderer(
            mock_display,
            mock_shader,
            "font.ttf",
            render_rect=(0, 0, 1000, 900),
        )

        # font_size = 80, y_margin = 10 + 80//4 = 30
        renderer.update_config(
            OverlayConfig(
                show_text=True,
                text_string="Big Text",
                show_text_sz=80,
                text_y_margin=10,
                text_bkg_hgt=0.0,
            )
        )

    # render_center_y = 540 - 450 = 90
    # y = 90 - 450 + 30 + 30 = -300
    called_y = sprite.position.call_args.args[1]
    assert called_y == -300
