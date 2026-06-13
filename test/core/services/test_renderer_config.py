"""Tests for renderer configuration mapping."""

from __future__ import annotations

import os
from typing import Any

from picframe.core.services.renderer_config import build_renderer_config
from picframe.core.services.resource_paths import ResourcePaths


class FakeConfigRepository:
    def __init__(self, values: dict[str, Any]) -> None:
        self.values = values

    def get_app_config(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)

    def get_app_config_bool(self, key: str, default: bool = False) -> bool:
        value = self.values.get(key, default)
        if isinstance(value, str):
            return value.strip().lower() in {"true", "1", "t", "y", "yes", "on"}
        return bool(value)


def test_build_renderer_config_maps_matting_values() -> None:
    repo = FakeConfigRepository(
        {
            "viewer.display_w": "1920",
            "viewer.display_h": "1080",
            "viewer.background": [0.1, 0.2, 0.3, 1.0],
            "viewer.blur_amount": 20,
            "viewer.blur_zoom": 1.2,
            "viewer.blur_edges": True,
            "viewer.video_fit_display": True,
            "viewer.show_text_fm": "%Y",
            "viewer.show_text_sz": 52,
            "viewer.text_justify": "C",
            "viewer.text_bkg_hgt": 0.3,
            "viewer.text_opacity": 0.6,
            "viewer.text_x_margin": 42,
            "viewer.text_y_margin": -4,
            "viewer.geo_suppress_list": ["County"],
            "viewer.clock_justify": "L",
            "viewer.clock_text_sz": 80,
            "viewer.clock_opacity": 0.7,
            "viewer.clock_top_bottom": "B",
            "viewer.clock_wdt_offset_pct": 5.0,
            "viewer.clock_hgt_offset_pct": 6.0,
            "viewer.mat_images": "on",
            "viewer.mat_type": "float",
            "viewer.outer_mat_color": [10, 20, 30],
            "viewer.inner_mat_color": "40,50,60",
            "viewer.outer_mat_border": 33,
            "viewer.inner_mat_border": 22,
            "viewer.outer_mat_use_texture": False,
            "viewer.inner_mat_use_texture": True,
            "viewer.mat_resource_folder": "~/custom-mat",
        }
    )

    config = build_renderer_config(repo)

    assert config.display_w == 1920
    assert config.display_h == 1080
    assert config.background == (0.1, 0.2, 0.3, 1.0)
    assert config.blur_amount == 20
    assert config.blur_zoom == 1.2
    assert config.blur_edges is True
    assert config.video_fit_display is True
    assert config.show_text_fm == "%Y"
    assert config.show_text_sz == 52
    assert config.text_justify == "C"
    assert config.text_bkg_hgt == 0.3
    assert config.text_opacity == 0.6
    assert config.text_x_margin == 42
    assert config.text_y_margin == -4
    assert config.geo_suppress_list == ["County"]
    assert config.clock_justify == "L"
    assert config.clock_text_sz == 80
    assert config.clock_opacity == 0.7
    assert config.clock_top_bottom == "B"
    assert config.clock_wdt_offset_pct == 5.0
    assert config.clock_hgt_offset_pct == 6.0
    assert config.mat_images == "on"
    assert config.mat_type == "float"
    assert config.outer_mat_color == [10, 20, 30]
    assert config.inner_mat_color == "40,50,60"
    assert config.outer_mat_border == 33
    assert config.inner_mat_border == 22
    assert config.outer_mat_use_texture is False
    assert config.inner_mat_use_texture is True
    assert config.mat_resource_folder == os.path.expanduser("~/custom-mat")


def test_build_renderer_config_uses_matting_defaults() -> None:
    resource_paths = ResourcePaths.from_base_dir("/tmp/picframe-test")
    config = build_renderer_config(FakeConfigRepository({}), resource_paths)

    assert config.mat_images == 0.01
    assert config.mat_type is None
    assert config.outer_mat_color is None
    assert config.inner_mat_color is None
    assert config.outer_mat_border == 75
    assert config.inner_mat_border == 40
    assert config.outer_mat_use_texture is True
    assert config.inner_mat_use_texture is False
    assert config.shader_path == "/tmp/picframe-test/data/shaders/blend_new"
    assert config.font_file == "/tmp/picframe-test/data/fonts/NotoSans-Regular.ttf"
    assert config.mat_resource_folder == "/tmp/picframe-test/data/mat"
