"""Build renderer configuration from the application config repository."""

from __future__ import annotations

from typing import Any

from picframe.core.events.dto import RendererConfig
from picframe.core.services.resource_paths import (
    PICFRAME_DATA_TOKEN,
    ResourcePaths,
)


def _optional_int(raw_value: Any) -> int | None:
    if raw_value in (None, ""):
        return None
    return int(raw_value)


def _string_list(raw_value: Any) -> list[str]:
    if raw_value in (None, ""):
        return []
    if isinstance(raw_value, str):
        return [raw_value]
    if isinstance(raw_value, list):
        return [str(item) for item in raw_value if str(item).strip()]
    return [str(raw_value)]


def build_renderer_config(
    config_repository: Any,
    resource_paths: ResourcePaths | None = None,
) -> RendererConfig:
    """Map persisted application config values into a RendererConfig DTO."""
    paths = resource_paths or ResourcePaths.from_base_dir("~/.picframe")
    return RendererConfig(
        display_x=int(config_repository.get_app_config("viewer.display_x", 0)),
        display_y=int(config_repository.get_app_config("viewer.display_y", 0)),
        display_w=_optional_int(config_repository.get_app_config("viewer.display_w")),
        display_h=_optional_int(config_repository.get_app_config("viewer.display_h")),
        fps=int(config_repository.get_app_config("viewer.fps", 20)),
        background=tuple(
            config_repository.get_app_config("viewer.background", [0.0, 0.0, 0.0, 1.0])
        ),
        use_glx=config_repository.get_app_config_bool("viewer.use_glx", False),
        use_sdl2=config_repository.get_app_config_bool("viewer.use_sdl2", False),
        shader_path=paths.resolve(
            config_repository.get_app_config(
                "viewer.shader", f"{PICFRAME_DATA_TOKEN}/shaders/blend_new"
            )
        ),
        kenburns=config_repository.get_app_config_bool("viewer.kenburns", False),
        show_clock=config_repository.get_app_config_bool("viewer.show_clock", False),
        clock_format=str(config_repository.get_app_config("viewer.clock_format", "%H:%M")),
        clock_justify=str(config_repository.get_app_config("viewer.clock_justify", "R")),
        clock_text_sz=int(config_repository.get_app_config("viewer.clock_text_sz", 120)),
        clock_opacity=float(config_repository.get_app_config("viewer.clock_opacity", 1.0)),
        clock_top_bottom=str(config_repository.get_app_config("viewer.clock_top_bottom", "T")),
        clock_wdt_offset_pct=float(
            config_repository.get_app_config("viewer.clock_wdt_offset_pct", 3.0)
        ),
        clock_hgt_offset_pct=float(
            config_repository.get_app_config("viewer.clock_hgt_offset_pct", 3.0)
        ),
        clock_extra_source=str(
            config_repository.get_app_config("viewer.clock_extra_source", "off")
        ),
        clock_extra_text=str(config_repository.get_app_config("viewer.clock_extra_text", "")),
        show_text_enabled=config_repository.get_app_config_bool("viewer.show_text_enabled", True),
        text_overlay_format=str(
            config_repository.get_app_config(
                "viewer.text_overlay_format", "title caption name date folder location"
            )
        ),
        show_text_fm=str(config_repository.get_app_config("viewer.show_text_fm", "%b %d, %Y")),
        model_locale=str(config_repository.get_app_config("model.locale", "en_US.utf8")),
        text_justify=str(config_repository.get_app_config("viewer.text_justify", "L")),
        show_text_sz=int(config_repository.get_app_config("viewer.show_text_sz", 40)),
        text_bkg_hgt=float(config_repository.get_app_config("viewer.text_bkg_hgt", 0.25)),
        text_opacity=float(config_repository.get_app_config("viewer.text_opacity", 1.0)),
        text_x_margin=int(config_repository.get_app_config("viewer.text_x_margin", 100)),
        text_y_margin=int(config_repository.get_app_config("viewer.text_y_margin", 0)),
        geo_suppress_list=_string_list(
            config_repository.get_app_config("viewer.geo_suppress_list", [])
        ),
        time_fade=float(config_repository.get_app_config("model.fade_time", 2.0)),
        time_delay=float(config_repository.get_app_config("model.time_delay", 200.0)),
        show_text_tm=float(config_repository.get_app_config("viewer.show_text_tm", 10.0)),
        font_file=paths.resolve(
            config_repository.get_app_config(
                "viewer.font_file",
                f"{PICFRAME_DATA_TOKEN}/fonts/NotoSans-Regular.ttf",
            )
        ),
        blend_type=str(config_repository.get_app_config("viewer.blend_type", "blend")),
        blur_amount=int(config_repository.get_app_config("viewer.blur_amount", 12)),
        blur_zoom=float(config_repository.get_app_config("viewer.blur_zoom", 1.0)),
        blur_edges=config_repository.get_app_config_bool("viewer.blur_edges", False),
        edge_alpha=float(config_repository.get_app_config("viewer.edge_alpha", 0.5)),
        fit=config_repository.get_app_config_bool("viewer.fit", False),
        video_fit_display=config_repository.get_app_config_bool("viewer.video_fit_display", False),
        show_text_on_video=config_repository.get_app_config_bool(
            "viewer.show_text_on_video", False
        ),
        video_extensions=config_repository.get_app_config(
            "model.video_extensions", [".mp4", ".mov", ".avi", ".mkv"]
        ),
        mat_images=config_repository.get_app_config("viewer.mat_images", 0.01),
        mat_type=config_repository.get_app_config("viewer.mat_type", None),
        outer_mat_color=config_repository.get_app_config("viewer.outer_mat_color", None),
        inner_mat_color=config_repository.get_app_config("viewer.inner_mat_color", None),
        outer_mat_border=int(config_repository.get_app_config("viewer.outer_mat_border", 75)),
        inner_mat_border=int(config_repository.get_app_config("viewer.inner_mat_border", 40)),
        outer_mat_use_texture=config_repository.get_app_config_bool(
            "viewer.outer_mat_use_texture", True
        ),
        inner_mat_use_texture=config_repository.get_app_config_bool(
            "viewer.inner_mat_use_texture", False
        ),
        mat_resource_folder=str(
            paths.resolve(
                config_repository.get_app_config(
                    "viewer.mat_resource_folder", f"{PICFRAME_DATA_TOKEN}/mat"
                )
            )
        ),
    )
