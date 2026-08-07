from unittest.mock import MagicMock, mock_open, patch

import pytest

from picframe.core.events.dto import OverlayConfig
from picframe.core.renderers.components.clock_renderer import ClockRenderer


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
    with patch(
        "picframe.core.renderers.components.clock_renderer.pi3d.FixedString"
    ) as mock_fixed_string:
        mock_fixed_string.return_value.sprite = MagicMock()
        return ClockRenderer(
            mock_display, mock_shader, "src/picframe/data/fonts/NotoSans-Regular.ttf"
        )


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
    with patch("picframe.core.renderers.components.clock_renderer.datetime") as mock_datetime:
        mock_datetime.now.return_value.strftime.return_value = "12:00"
        clock_renderer.draw()
        assert clock_renderer._current_time_str == "12:00"
        # The sprite is a MagicMock from the fixture; verify its draw was called
        clock_renderer._clock_block.sprite.draw.assert_called_once()


def test_clock_renderer_draw_no_update_if_time_same(clock_renderer):
    config = OverlayConfig(show_clock=True, clock_format="%H:%M")
    clock_renderer.update_config(config)

    with patch("picframe.core.renderers.components.clock_renderer.datetime") as mock_datetime:
        mock_datetime.now.return_value.strftime.return_value = "12:00"
        clock_renderer.draw()
        sprite_draw = clock_renderer._clock_block.sprite.draw
        sprite_draw.reset_mock()

        # Draw again with same time
        clock_renderer.draw()
        # It should still draw, but not recreate the sprite
        sprite_draw.assert_called_once()


def test_clock_renderer_applies_overlay_style(mock_display, mock_shader):
    with patch(
        "picframe.core.renderers.components.clock_renderer.pi3d.FixedString"
    ) as mock_fixed_string:
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
        with patch("picframe.core.renderers.components.clock_renderer.datetime") as mock_datetime:
            mock_datetime.now.return_value.strftime.return_value = "12:00"
            renderer.draw()

    kwargs = mock_fixed_string.call_args.kwargs
    assert kwargs["font_size"] == 72
    assert kwargs["justify"] == "L"
    assert kwargs["color"][3] == 127
    assert kwargs["width"] == mock_display.width - (int(mock_display.width * 0.05) * 2)


def test_clock_renderer_positions_clock_inside_render_rect(mock_display, mock_shader):
    """#728: default justify R positions clock at right edge of render area."""
    with patch(
        "picframe.core.renderers.components.clock_renderer.pi3d.FixedString"
    ) as mock_fixed_string:
        sprite = MagicMock()
        sprite.height = 60
        sprite.width = 300
        mock_fixed_string.return_value.sprite = sprite
        renderer = ClockRenderer(
            mock_display,
            mock_shader,
            "font.ttf",
            render_rect=(0, 0, 1000, 900),
        )
        renderer.update_config(
            OverlayConfig(
                show_clock=True,
                clock_format="%H:%M",
                clock_wdt_offset_pct=5,
                clock_hgt_offset_pct=10,
            )
        )
        with patch("picframe.core.renderers.components.clock_renderer.datetime") as mock_datetime:
            mock_datetime.now.return_value.strftime.return_value = "12:00"
            renderer.draw()

    kwargs = mock_fixed_string.call_args.kwargs
    assert kwargs["width"] == 900
    # #728: default justify R → x_offset = width//2 - sprite.width//2 = 450 - 150 = 300
    # render_center_x = -460.0, x = -460.0 + 300 = -160.0
    sprite.position.assert_called_once_with(-160.0, 420.0, 0.1)


def test_clock_renderer_left_justify_positions_at_left_edge(mock_display, mock_shader):
    """#728: L-justified clock sits at the left edge of the render area."""
    with patch(
        "picframe.core.renderers.components.clock_renderer.pi3d.FixedString"
    ) as mock_fixed_string:
        sprite = MagicMock()
        sprite.height = 60
        sprite.width = 300
        mock_fixed_string.return_value.sprite = sprite
        renderer = ClockRenderer(mock_display, mock_shader, "font.ttf")
        renderer.update_config(
            OverlayConfig(
                show_clock=True,
                clock_format="%H:%M",
                clock_justify="L",
                clock_wdt_offset_pct=3,
            )
        )
        with patch("picframe.core.renderers.components.clock_renderer.datetime") as mock_datetime:
            mock_datetime.now.return_value.strftime.return_value = "12:00"
            renderer.draw()

    # x_margin = 1920 * 0.03 = 57, width = max(480, 1920 - 114) = 1806
    # x_offset = 1806//2 - 300//2 = 903 - 150 = 753
    # render_center_x = 0.0, x = 0.0 - 753 = -753.0
    called_x = sprite.position.call_args.args[0]
    assert called_x == pytest.approx(-753.0, abs=1.0)


def test_clock_renderer_right_justify_positions_at_right_edge(mock_display, mock_shader):
    """#728: R-justified clock sits at the right edge of the render area."""
    with patch(
        "picframe.core.renderers.components.clock_renderer.pi3d.FixedString"
    ) as mock_fixed_string:
        sprite = MagicMock()
        sprite.height = 60
        sprite.width = 300
        mock_fixed_string.return_value.sprite = sprite
        renderer = ClockRenderer(mock_display, mock_shader, "font.ttf")
        renderer.update_config(
            OverlayConfig(
                show_clock=True,
                clock_format="%H:%M",
                clock_justify="R",
                clock_wdt_offset_pct=3,
            )
        )
        with patch("picframe.core.renderers.components.clock_renderer.datetime") as mock_datetime:
            mock_datetime.now.return_value.strftime.return_value = "12:00"
            renderer.draw()

    # x_margin = 1920 * 0.03 = 57, width = max(480, 1920 - 114) = 1806
    # x_offset = 1806//2 - 300//2 = 903 - 150 = 753
    # render_center_x = 0.0, x = 0.0 + 753 = 753.0
    called_x = sprite.position.call_args.args[0]
    assert called_x == pytest.approx(753.0, abs=1.0)


def test_clock_renderer_center_justify_stays_centered(mock_display, mock_shader):
    """#728: C-justified clock remains horizontally centered (no x offset)."""
    with patch(
        "picframe.core.renderers.components.clock_renderer.pi3d.FixedString"
    ) as mock_fixed_string:
        sprite = MagicMock()
        sprite.height = 60
        sprite.width = 300
        mock_fixed_string.return_value.sprite = sprite
        renderer = ClockRenderer(mock_display, mock_shader, "font.ttf")
        renderer.update_config(
            OverlayConfig(
                show_clock=True,
                clock_format="%H:%M",
                clock_justify="C",
                clock_wdt_offset_pct=3,
            )
        )
        with patch("picframe.core.renderers.components.clock_renderer.datetime") as mock_datetime:
            mock_datetime.now.return_value.strftime.return_value = "12:00"
            renderer.draw()

    # render_center_x = 0.0, no justify offset for C
    called_x = sprite.position.call_args.args[0]
    assert called_x == 0.0


def test_clock_renderer_left_justify_uses_min_width_when_render_area_is_narrow(
    mock_display, mock_shader
):
    """#728: when render_w - 2*x_margin < font_size*4, width is clamped to font_size*4.

    Sourcery feedback: validate the ``max(font_size * 4, ...)`` branch of the
    width calculation so the justify offset is correct in both branches.
    """
    # Narrow display: render_w=400, x_margin = 400*0.05 = 20, so
    # render_w - 2*x_margin = 360 < font_size*4 = 480 → width = 480
    mock_display.width = 400
    with patch(
        "picframe.core.renderers.components.clock_renderer.pi3d.FixedString"
    ) as mock_fixed_string:
        sprite = MagicMock()
        sprite.height = 60
        sprite.width = 300
        mock_fixed_string.return_value.sprite = sprite
        renderer = ClockRenderer(mock_display, mock_shader, "font.ttf")
        renderer.update_config(
            OverlayConfig(
                show_clock=True,
                clock_format="%H:%M",
                clock_justify="L",
                clock_text_sz=120,
                clock_wdt_offset_pct=5,
            )
        )
        with patch("picframe.core.renderers.components.clock_renderer.datetime") as mock_datetime:
            mock_datetime.now.return_value.strftime.return_value = "12:00"
            renderer.draw()

    kwargs = mock_fixed_string.call_args.kwargs
    # font_size=120 → font_size*4=480 > 400-40=360 → width=480
    assert kwargs["width"] == 480
    # justify_offset = 480//2 - 300//2 = 240 - 150 = 90
    # render_center_x = 0.0 (no render_rect), x = 0.0 - 90 = -90.0
    called_x = sprite.position.call_args.args[0]
    assert called_x == pytest.approx(-90.0, abs=0.01)


def test_clock_renderer_rebuilds_when_style_changes_at_same_time(mock_display, mock_shader):
    with patch(
        "picframe.core.renderers.components.clock_renderer.pi3d.FixedString"
    ) as mock_fixed_string:
        mock_fixed_string.return_value.sprite = MagicMock()
        renderer = ClockRenderer(mock_display, mock_shader, "font.ttf")

        with patch("picframe.core.renderers.components.clock_renderer.datetime") as mock_datetime:
            mock_datetime.now.return_value.strftime.return_value = "12:00"

            renderer.update_config(OverlayConfig(show_clock=True, clock_text_sz=72))
            renderer.draw()

            renderer.update_config(OverlayConfig(show_clock=True, clock_text_sz=96))
            renderer.draw()

    assert mock_fixed_string.call_count == 2
    assert mock_fixed_string.call_args_list[0].kwargs["font_size"] == 72
    assert mock_fixed_string.call_args_list[1].kwargs["font_size"] == 96


def test_clock_renderer_draw_appends_extra_text(mock_display, mock_shader):
    with patch(
        "picframe.core.renderers.components.clock_renderer.pi3d.FixedString"
    ) as mock_fixed_string:
        mock_fixed_string.return_value.sprite = MagicMock()
        renderer = ClockRenderer(mock_display, mock_shader, "font.ttf")
        renderer.update_config(
            OverlayConfig(
                show_clock=True,
                clock_format="%H:%M",
                clock_extra_source="ui_text",
                clock_extra_text="Hello World",
            )
        )
        with patch("picframe.core.renderers.components.clock_renderer.datetime") as mock_datetime:
            mock_datetime.now.return_value.strftime.return_value = "12:00"
            with patch("pi3d.Sprite.draw"):
                renderer.draw()

    assert renderer._current_extra_text == "Hello World"
    assert mock_fixed_string.call_args.args[1] == "12:00\nHello World"


def test_clock_renderer_draw_without_extra_text(mock_display, mock_shader):
    with patch(
        "picframe.core.renderers.components.clock_renderer.pi3d.FixedString"
    ) as mock_fixed_string:
        mock_fixed_string.return_value.sprite = MagicMock()
        renderer = ClockRenderer(mock_display, mock_shader, "font.ttf")
        renderer.update_config(
            OverlayConfig(
                show_clock=True,
                clock_format="%H:%M",
                clock_extra_text="",
            )
        )
        with patch("picframe.core.renderers.components.clock_renderer.datetime") as mock_datetime:
            mock_datetime.now.return_value.strftime.return_value = "12:00"
            with patch("pi3d.Sprite.draw"):
                renderer.draw()

    assert renderer._current_extra_text == ""
    assert mock_fixed_string.call_args.args[1] == "12:00"


def test_clock_renderer_has_changed_when_extra_text_changes(mock_display, mock_shader):
    with patch("picframe.core.renderers.components.clock_renderer.pi3d.FixedString"):
        renderer = ClockRenderer(mock_display, mock_shader, "font.ttf")
        renderer.update_config(
            OverlayConfig(
                show_clock=True,
                clock_format="%H:%M",
                clock_extra_source="ui_text",
                clock_extra_text="",
            )
        )
        with patch("picframe.core.renderers.components.clock_renderer.datetime") as mock_datetime:
            mock_datetime.now.return_value.strftime.return_value = "12:00"
            with patch("pi3d.Sprite.draw"):
                renderer.draw()
            assert renderer.has_changed() is False

        renderer.update_config(
            OverlayConfig(
                show_clock=True,
                clock_format="%H:%M",
                clock_extra_source="ui_text",
                clock_extra_text="Updated",
            )
        )
        with patch("picframe.core.renderers.components.clock_renderer.datetime") as mock_datetime:
            mock_datetime.now.return_value.strftime.return_value = "12:00"
            assert renderer.has_changed() is True


def test_clock_renderer_clock_txt_source_reads_file(mock_display, mock_shader):
    """When clock_extra_source is 'clock_txt', the renderer reads /dev/shm/clock.txt."""
    with (
        patch("picframe.core.renderers.components.clock_renderer.pi3d.FixedString") as mock_fs,
        patch(
            "picframe.core.renderers.components.clock_renderer.os.path.isfile",
            return_value=True,
        ),
        patch("builtins.open", mock_open(read_data="Hello from ramdisk")),
    ):
        mock_fs.return_value.sprite = MagicMock()
        renderer = ClockRenderer(mock_display, mock_shader, "font.ttf")
        renderer.update_config(
            OverlayConfig(
                show_clock=True,
                clock_format="%H:%M",
                clock_extra_source="clock_txt",
            )
        )
        with patch("picframe.core.renderers.components.clock_renderer.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "12:00"
            with patch("pi3d.Sprite.draw"):
                renderer.draw()

    assert renderer._current_extra_text == "Hello from ramdisk"
    assert mock_fs.call_args.args[1] == "12:00\nHello from ramdisk"


def test_clock_renderer_clock_txt_source_re_reads_on_has_changed(mock_display, mock_shader):
    """has_changed() returns True when the file content changes between calls."""
    with (
        patch("picframe.core.renderers.components.clock_renderer.pi3d.FixedString"),
        patch(
            "picframe.core.renderers.components.clock_renderer.os.path.isfile",
            return_value=True,
        ),
        patch("builtins.open", mock_open(read_data="First")),
    ):
        renderer = ClockRenderer(mock_display, mock_shader, "font.ttf")
        renderer.update_config(
            OverlayConfig(
                show_clock=True,
                clock_format="%H:%M",
                clock_extra_source="clock_txt",
            )
        )
        with patch("picframe.core.renderers.components.clock_renderer.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "12:00"
            with patch("pi3d.Sprite.draw"):
                renderer.draw()
            assert renderer.has_changed() is False

        # File content changes
        with patch("builtins.open", mock_open(read_data="Second")):
            assert renderer.has_changed() is True


def test_clock_renderer_clock_txt_source_missing_file_returns_empty(mock_display, mock_shader):
    """When /dev/shm/clock.txt doesn't exist, extra text is empty."""
    with (
        patch("picframe.core.renderers.components.clock_renderer.pi3d.FixedString") as mock_fs,
        patch(
            "picframe.core.renderers.components.clock_renderer.os.path.isfile",
            return_value=False,
        ),
    ):
        mock_fs.return_value.sprite = MagicMock()
        renderer = ClockRenderer(mock_display, mock_shader, "font.ttf")
        renderer.update_config(
            OverlayConfig(
                show_clock=True,
                clock_format="%H:%M",
                clock_extra_source="clock_txt",
            )
        )
        with patch("picframe.core.renderers.components.clock_renderer.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "12:00"
            with patch("pi3d.Sprite.draw"):
                renderer.draw()

    assert renderer._current_extra_text == ""
    assert mock_fs.call_args.args[1] == "12:00"


def test_clock_renderer_rebuilds_when_only_extra_text_changes(mock_display, mock_shader):
    """Visual signature includes clock_extra_text so the clock block is invalidated
    when only the text changes (not the source)."""
    with patch(
        "picframe.core.renderers.components.clock_renderer.pi3d.FixedString"
    ) as mock_fixed_string:
        mock_fixed_string.return_value.sprite = MagicMock()
        renderer = ClockRenderer(mock_display, mock_shader, "font.ttf")

        with patch("picframe.core.renderers.components.clock_renderer.datetime") as mock_datetime:
            mock_datetime.now.return_value.strftime.return_value = "12:00"
            with patch("pi3d.Sprite.draw"):
                # First draw with "Hello"
                renderer.update_config(
                    OverlayConfig(
                        show_clock=True,
                        clock_format="%H:%M",
                        clock_extra_source="ui_text",
                        clock_extra_text="Hello",
                    )
                )
                renderer.draw()
                assert mock_fixed_string.call_count == 1
                assert mock_fixed_string.call_args.args[1] == "12:00\nHello"

                # Same time, same source, but different text — should rebuild
                renderer.update_config(
                    OverlayConfig(
                        show_clock=True,
                        clock_format="%H:%M",
                        clock_extra_source="ui_text",
                        clock_extra_text="World",
                    )
                )
                renderer.draw()
                assert mock_fixed_string.call_count == 2
                assert mock_fixed_string.call_args.args[1] == "12:00\nWorld"


def test_clock_renderer_off_source_ignores_clock_extra_text(mock_display, mock_shader):
    """When source is 'off', clock_extra_text is ignored even if set."""
    with (
        patch("picframe.core.renderers.components.clock_renderer.pi3d.FixedString") as mock_fs,
        patch("pi3d.Sprite.draw"),
    ):
        mock_fs.return_value.sprite = MagicMock()
        renderer = ClockRenderer(mock_display, mock_shader, "font.ttf")
        renderer.update_config(
            OverlayConfig(
                show_clock=True,
                clock_format="%H:%M",
                clock_extra_source="off",
                clock_extra_text="Should be ignored",
            )
        )
        with patch("picframe.core.renderers.components.clock_renderer.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "12:00"
            renderer.draw()

    assert renderer._current_extra_text == ""
    assert mock_fs.call_args.args[1] == "12:00"
