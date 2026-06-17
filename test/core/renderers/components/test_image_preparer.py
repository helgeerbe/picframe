"""Tests for renderer image preparation and matting."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from picframe.core.events.dto import RenderCommand
from picframe.core.renderers.components.image_preparer import (
    ImagePreparer,
    MattingControl,
)


class FakeMatter:
    def __init__(self, output: Image.Image | None = None) -> None:
        self.output = output or Image.new("RGB", (10, 10), "green")
        self.calls: list[tuple[Image.Image, ...]] = []

    def mat_image(self, images: tuple[Image.Image, ...]) -> Image.Image:
        self.calls.append(images)
        return self.output


def pair_composer(left: Image.Image, right: Image.Image) -> Image.Image:
    return Image.new("RGB", (left.width + right.width + 8, min(left.height, right.height)), "blue")


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("true", MattingControl(True, -1.0)),
        ("yes", MattingControl(True, -1.0)),
        ("on", MattingControl(True, -1.0)),
        (True, MattingControl(True, -1.0)),
        ("false", MattingControl(False, 0.01)),
        ("no", MattingControl(False, 0.01)),
        ("off", MattingControl(False, 0.01)),
        (False, MattingControl(False, 0.01)),
        ("0", MattingControl(False, 0.01)),
        ("0.0", MattingControl(False, 0.01)),
        (0, MattingControl(False, 0.01)),
        (0.0, MattingControl(False, 0.01)),
        ("0.25", MattingControl(True, 0.25)),
        (0.5, MattingControl(True, 0.5)),
    ],
)
def test_parse_matting_control(raw_value: Any, expected: MattingControl) -> None:
    assert ImagePreparer.parse_matting_control(raw_value) == expected


def test_parse_matting_control_invalid_uses_default() -> None:
    assert ImagePreparer.parse_matting_control("not-a-number") == MattingControl(True, 0.01)


def test_aspect_threshold_decision() -> None:
    config = {"mat_images": 0.1}
    preparer = ImagePreparer((1920, 1080), config, pair_composer, matter_factory=FakeMatter)

    assert preparer.should_mat((800, 1200)) is True
    assert preparer.should_mat((1600, 900)) is False


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ([10, 20, 30], (10, 20, 30)),
        ((10.2, 20.8, 300), (10, 20, 255)),
        ("10,20,30", (10, 20, 30)),
        ("10 20 30", (10, 20, 30)),
        ("[10, 20, 30]", (10, 20, 30)),
        ("#0a141e", (10, 20, 30)),
        ("", None),
        ("null", None),
        ("bad", None),
    ],
)
def test_normalize_color(raw_value: Any, expected: tuple[int, int, int] | None) -> None:
    assert ImagePreparer.normalize_color(raw_value) == expected


def test_single_image_matting_calls_mat_image() -> None:
    matter = FakeMatter(Image.new("RGB", (20, 20), "green"))
    created_kwargs: dict[str, Any] = {}

    def factory(**kwargs: Any) -> FakeMatter:
        created_kwargs.update(kwargs)
        return matter

    preparer = ImagePreparer(
        (1920, 1080),
        {
            "mat_images": "on",
            "mat_type": "float",
            "outer_mat_color": "10,20,30",
            "inner_mat_color": [40, 50, 60],
            "outer_mat_border": 12,
            "inner_mat_border": 6,
            "outer_mat_use_texture": False,
            "inner_mat_use_texture": True,
            "mat_resource_folder": "~/mat-test",
        },
        pair_composer,
        matter_factory=factory,
    )

    result = preparer.prepare_single_image(Image.new("RGBA", (400, 800), "red"))

    assert result.size == (20, 20)
    assert len(matter.calls) == 1
    assert matter.calls[0][0].mode == "RGB"
    assert created_kwargs["mat_type"] == "float"
    assert created_kwargs["outer_mat_color"] == (10, 20, 30)
    assert created_kwargs["inner_mat_color"] == (40, 50, 60)
    assert created_kwargs["outer_mat_border"] == 12
    assert created_kwargs["inner_mat_border"] == 6
    assert created_kwargs["outer_mat_use_texture"] is False
    assert created_kwargs["inner_mat_use_texture"] is True
    assert str(created_kwargs["resource_folder"]).endswith("mat-test")


def test_blur_edges_returns_display_sized_composite() -> None:
    preparer = ImagePreparer(
        (200, 100),
        {
            "mat_images": "off",
            "blur_edges": True,
            "blur_amount": 4,
            "blur_zoom": 1.1,
        },
        pair_composer,
        matter_factory=FakeMatter,
    )

    result = preparer.prepare_single_image(Image.new("RGB", (50, 100), "red"))

    assert result.size == (200, 100)


def test_portrait_pair_matting_passes_both_images() -> None:
    matter = FakeMatter(Image.new("RGB", (30, 30), "green"))
    preparer = ImagePreparer(
        (1920, 1080),
        {"mat_images": "on"},
        pair_composer,
        matter_factory=lambda **_: matter,
    )

    result = preparer.prepare_portrait_pair(
        Image.new("RGB", (400, 800), "red"),
        Image.new("RGB", (400, 800), "yellow"),
    )

    assert result.size == (30, 30)
    assert len(matter.calls) == 1
    assert len(matter.calls[0]) == 2


def test_disabled_matting_uses_pair_composer_without_matter() -> None:
    def factory(**_: Any) -> FakeMatter:
        raise AssertionError("MatImage should not be created when matting is disabled")

    preparer = ImagePreparer(
        (1920, 1080),
        {"mat_images": "off"},
        pair_composer,
        matter_factory=factory,
    )

    result = preparer.prepare_portrait_pair(
        Image.new("RGB", (400, 800), "red"),
        Image.new("RGB", (300, 700), "yellow"),
    )

    assert result.mode == "RGB"
    assert result.size == (708, 700)


def test_mat_resource_failure_falls_back_to_unmatted_image() -> None:
    def factory(**_: Any) -> FakeMatter:
        raise FileNotFoundError("mat resource missing")

    image = Image.new("RGB", (400, 800), "red")
    preparer = ImagePreparer(
        (1920, 1080),
        {"mat_images": "on"},
        pair_composer,
        matter_factory=factory,
    )

    result = preparer.prepare_single_image(image)

    assert result.mode == "RGB"
    assert result.size == image.size


def test_load_single_image_applies_exif_orientation(tmp_path: Path) -> None:
    image_path = tmp_path / "rotated.jpg"
    image = Image.new("RGB", (120, 60), "red")
    exif = Image.Exif()
    exif[274] = 6
    image.save(image_path, exif=exif)
    preparer = ImagePreparer(
        (1920, 1080),
        {"mat_images": "off"},
        pair_composer,
        matter_factory=FakeMatter,
    )

    result = preparer.load_single_image(str(image_path))

    assert result.size == (60, 120)


def test_load_portrait_pair_from_paths_uses_exif_corrected_images(tmp_path: Path) -> None:
    left_path = tmp_path / "left.jpg"
    right_path = tmp_path / "right.jpg"
    Image.new("RGB", (100, 200), "red").save(left_path)
    Image.new("RGB", (80, 160), "yellow").save(right_path)
    preparer = ImagePreparer(
        (1920, 1080),
        {"mat_images": "off"},
        pair_composer,
        matter_factory=FakeMatter,
    )

    result = preparer.load_portrait_pair(
        RenderCommand(
            image_path=str(left_path),
            layout="portrait_pair",
            image_paths=(str(left_path), str(right_path)),
        )
    )

    assert result.size == (188, 160)
