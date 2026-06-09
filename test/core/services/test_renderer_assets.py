"""Tests for renderer asset validation."""

from __future__ import annotations

from pathlib import Path

from picframe.core.events.dto import RendererConfig
from picframe.core.services.renderer_assets import validate_renderer_assets


def _config(tmp_path: Path, **overrides: object) -> RendererConfig:
    values = {
        "shader_path": str(tmp_path / "shaders" / "blend_new"),
        "font_file": str(tmp_path / "fonts" / "NotoSans-Regular.ttf"),
        "mat_resource_folder": str(tmp_path / "mat"),
        "mat_images": 0.01,
        "show_text_enabled": True,
    }
    values.update(overrides)
    return RendererConfig(**values)


def _write_valid_assets(tmp_path: Path) -> Path:
    shader_dir = tmp_path / "shaders"
    shader_dir.mkdir()
    (shader_dir / "blend_new.vs").write_text("vertex")
    (shader_dir / "blend_new.fs").write_text("fragment")
    font_dir = tmp_path / "fonts"
    font_dir.mkdir()
    font_file = font_dir / "NotoSans-Regular.ttf"
    font_file.write_bytes(b"font")
    (tmp_path / "mat").mkdir()
    fallback = tmp_path / "no_pictures.jpg"
    fallback.write_bytes(b"image")
    return fallback


def test_validate_renderer_assets_accepts_valid_defaults(tmp_path: Path) -> None:
    fallback = _write_valid_assets(tmp_path)

    issues = validate_renderer_assets(_config(tmp_path), no_files_img=str(fallback))

    assert issues == []


def test_validate_renderer_assets_reports_missing_shader_pair(tmp_path: Path) -> None:
    fallback = _write_valid_assets(tmp_path)
    (tmp_path / "shaders" / "blend_new.vs").unlink()

    issues = validate_renderer_assets(_config(tmp_path), no_files_img=str(fallback))

    assert [(issue.field, issue.path) for issue in issues] == [
        ("viewer.shader", str(tmp_path / "shaders" / "blend_new.vs"))
    ]


def test_validate_renderer_assets_reports_missing_fragment_shader(tmp_path: Path) -> None:
    fallback = _write_valid_assets(tmp_path)
    (tmp_path / "shaders" / "blend_new.fs").unlink()

    issues = validate_renderer_assets(_config(tmp_path), no_files_img=str(fallback))

    assert [(issue.field, issue.path) for issue in issues] == [
        ("viewer.shader", str(tmp_path / "shaders" / "blend_new.fs"))
    ]


def test_validate_renderer_assets_reports_missing_font_when_overlay_enabled(
    tmp_path: Path,
) -> None:
    fallback = _write_valid_assets(tmp_path)
    (tmp_path / "fonts" / "NotoSans-Regular.ttf").unlink()

    issues = validate_renderer_assets(_config(tmp_path), no_files_img=str(fallback))

    assert [issue.field for issue in issues] == ["viewer.font_file"]


def test_validate_renderer_assets_allows_missing_font_when_overlay_disabled(
    tmp_path: Path,
) -> None:
    fallback = _write_valid_assets(tmp_path)
    (tmp_path / "fonts" / "NotoSans-Regular.ttf").unlink()

    issues = validate_renderer_assets(
        _config(tmp_path, show_text_enabled=False, show_clock=False),
        no_files_img=str(fallback),
    )

    assert issues == []


def test_validate_renderer_assets_reports_missing_mat_folder(tmp_path: Path) -> None:
    fallback = _write_valid_assets(tmp_path)
    (tmp_path / "mat").rmdir()

    issues = validate_renderer_assets(_config(tmp_path), no_files_img=str(fallback))

    assert [issue.field for issue in issues] == ["viewer.mat_resource_folder"]


def test_validate_renderer_assets_reports_missing_fallback_image(tmp_path: Path) -> None:
    fallback = _write_valid_assets(tmp_path)
    fallback.unlink()

    issues = validate_renderer_assets(_config(tmp_path), no_files_img=str(fallback))

    assert [issue.field for issue in issues] == ["model.no_files_img"]


def test_validate_renderer_assets_allows_packaged_fallback_image(tmp_path: Path) -> None:
    fallback = _write_valid_assets(tmp_path)
    packaged_fallback = tmp_path / "packaged_no_pictures.jpg"
    fallback.unlink()
    packaged_fallback.write_bytes(b"image")

    issues = validate_renderer_assets(
        _config(tmp_path),
        no_files_img=str(fallback),
        packaged_no_files_img=str(packaged_fallback),
    )

    assert issues == []
