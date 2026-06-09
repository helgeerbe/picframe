"""Validation helpers for renderer runtime assets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from picframe.core.events.dto import RendererConfig


@dataclass(frozen=True)
class RendererAssetIssue:
    """A missing or invalid renderer asset path."""

    field: str
    path: str
    message: str


class RendererAssetValidationError(RuntimeError):
    """Raised when renderer assets are not ready for startup."""

    def __init__(self, issues: list[RendererAssetIssue]) -> None:
        self.issues = issues
        super().__init__(format_renderer_asset_issues(issues))


def format_renderer_asset_issues(issues: list[RendererAssetIssue]) -> str:
    """Build a concise user-facing renderer asset error message."""
    if not issues:
        return ""
    return "; ".join(f"{issue.field}: {issue.message} ({issue.path})" for issue in issues)


def _shader_base(shader_path: str) -> str:
    path = str(Path(shader_path).expanduser())
    if path.lower().endswith((".fs", ".vs")):
        return path[:-3]
    return path


def _matting_enabled(raw_value: Any) -> bool:
    if isinstance(raw_value, bool):
        return raw_value
    text = str(raw_value).strip().lower()
    if text in {"false", "no", "off", "0", ""}:
        return False
    try:
        return float(text) != 0.0
    except ValueError:
        return text in {"true", "yes", "on"}


def validate_renderer_assets(
    config: RendererConfig,
    *,
    no_files_img: str | None = None,
    packaged_no_files_img: str | None = None,
) -> list[RendererAssetIssue]:
    """Return renderer asset issues that should block media rendering."""
    issues: list[RendererAssetIssue] = []

    shader_base = _shader_base(config.shader_path)
    for suffix in (".vs", ".fs"):
        shader_file = Path(f"{shader_base}{suffix}").expanduser()
        if not shader_file.is_file():
            issues.append(
                RendererAssetIssue(
                    field="viewer.shader",
                    path=str(shader_file),
                    message=f"Missing shader {suffix} file",
                )
            )

    if config.show_text_enabled or config.show_clock:
        font_file = Path(config.font_file).expanduser()
        if not font_file.is_file():
            issues.append(
                RendererAssetIssue(
                    field="viewer.font_file",
                    path=str(font_file),
                    message="Font file does not exist",
                )
            )

    if _matting_enabled(config.mat_images):
        mat_folder = Path(config.mat_resource_folder).expanduser()
        if not mat_folder.is_dir():
            issues.append(
                RendererAssetIssue(
                    field="viewer.mat_resource_folder",
                    path=str(mat_folder),
                    message="Mat resource folder does not exist",
                )
            )

    if no_files_img:
        fallback_image = Path(no_files_img).expanduser()
        packaged_fallback = (
            Path(packaged_no_files_img).expanduser()
            if packaged_no_files_img
            else None
        )
        if not fallback_image.is_file() and not (
            packaged_fallback is not None and packaged_fallback.is_file()
        ):
            issues.append(
                RendererAssetIssue(
                    field="model.no_files_img",
                    path=str(fallback_image),
                    message="Fallback image does not exist and packaged fallback is unavailable",
                )
            )

    return issues
