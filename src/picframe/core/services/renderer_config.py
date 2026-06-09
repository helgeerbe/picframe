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
        ),  # type: ignore[arg-type]
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
        show_text_enabled=config_repository.get_app_config_bool(
            "viewer.show_text_enabled", False
        ),
        text_overlay_format=str(
            config_repository.get_app_config("viewer.text_overlay_format", "%b %d, %Y")
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
        edge_alpha=float(config_repository.get_app_config("viewer.edge_alpha", 0.5)),
        fit=config_repository.get_app_config_bool("viewer.fit", False),
        video_extensions=config_repository.get_app_config(
            "model.video_extensions", [".mp4", ".mov", ".avi", ".mkv"]
        ),
        mat_images=config_repository.get_app_config("viewer.mat_images", 0.01),
        mat_type=config_repository.get_app_config("viewer.mat_type", None),
        outer_mat_color=config_repository.get_app_config("viewer.outer_mat_color", None),
        inner_mat_color=config_repository.get_app_config("viewer.inner_mat_color", None),
        outer_mat_border=int(
            config_repository.get_app_config("viewer.outer_mat_border", 75)
        ),
        inner_mat_border=int(
            config_repository.get_app_config("viewer.inner_mat_border", 40)
        ),
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
