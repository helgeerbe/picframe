from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

from picframe.core.services.resource_paths import ResourcePaths
from picframe.mat_image import MatImage


def _without_content(image: Image.Image, rect: tuple[int, int, int, int]) -> Image.Image:
    copy = image.copy()
    x, y, w, h = rect
    ImageDraw.Draw(copy).rectangle((x, y, x + w - 1, y + h - 1), fill=(0, 0, 0))
    return copy


def _color_bbox(
    image: Image.Image,
    color: tuple[int, int, int],
) -> tuple[int, int, int, int] | None:
    rgb = image.convert("RGB")
    xs = []
    ys = []
    for y in range(rgb.height):
        for x in range(rgb.width):
            if rgb.getpixel((x, y)) == color:
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return (
        min(xs),
        min(ys),
        max(xs) - min(xs) + 1,
        max(ys) - min(ys) + 1,
    )


def _rect_contains(
    outer: tuple[int, int, int, int],
    inner: tuple[int, int, int, int],
) -> bool:
    outer_x, outer_y, outer_w, outer_h = outer
    inner_x, inner_y, inner_w, inner_h = inner
    return (
        inner_x >= outer_x
        and inner_y >= outer_y
        and inner_x + inner_w <= outer_x + outer_w
        and inner_y + inner_h <= outer_y + outer_h
    )


def test_mat_image_with_layout_reuses_identical_video_mat_frame() -> None:
    matter = MatImage(
        display_size=(400, 300),
        resource_folder=str(Path(ResourcePaths.packaged_data_dir()) / "mat"),
        mat_type="double_flat",
        outer_mat_color=(10, 20, 30),
        inner_mat_color=(40, 50, 60),
        outer_mat_border=40,
        inner_mat_border=20,
        outer_mat_use_texture=False,
        inner_mat_use_texture=False,
    )
    first = Image.new("RGB", (160, 90), "red")
    last = Image.new("RGB", (160, 90), "blue")

    first_result = matter.mat_image_with_layout((first,))
    last_result = matter.mat_image_with_layout(
        (last,),
        layout_spec=first_result.layout_spec,
    )

    assert first_result.layout_spec == last_result.layout_spec
    assert first_result.content_rects == last_result.content_rects
    content_rect = first_result.content_rects[0]
    first_mat = _without_content(first_result.image, content_rect)
    last_mat = _without_content(last_result.image, content_rect)
    assert ImageChops.difference(first_mat, last_mat).getbbox() is None


def test_mat_image_with_layout_reports_logical_source_rects_for_all_styles() -> None:
    source_color = (253, 5, 121)
    resource_folder = str(Path(ResourcePaths.packaged_data_dir()) / "mat")

    for mat_type in (
        "float",
        "float_polaroid",
        "float_color_wrap",
        "double_flat",
    ):
        matter = MatImage(
            display_size=(400, 300),
            resource_folder=resource_folder,
            mat_type=mat_type,
            outer_mat_color=(10, 20, 30),
            inner_mat_color=(40, 50, 60),
            outer_mat_border=40,
            inner_mat_border=20,
            outer_mat_use_texture=False,
            inner_mat_use_texture=False,
        )

        result = matter.mat_image_with_layout(
            (Image.new("RGB", (160, 90), source_color),)
        )

        assert result.content_rects[0] == _color_bbox(result.image, source_color), mat_type

    for mat_type in (
        "single_bevel",
        "double_bevel",
    ):
        matter = MatImage(
            display_size=(400, 300),
            resource_folder=resource_folder,
            mat_type=mat_type,
            outer_mat_color=(10, 20, 30),
            inner_mat_color=(40, 50, 60),
            outer_mat_border=40,
            inner_mat_border=20,
            outer_mat_use_texture=False,
            inner_mat_use_texture=False,
        )

        result = matter.mat_image_with_layout(
            (Image.new("RGB", (160, 90), source_color),)
        )
        visible_rect = _color_bbox(result.image, source_color)

        assert visible_rect is not None
        assert _rect_contains(result.content_rects[0], visible_rect), mat_type
        assert result.content_rects[0][0] < visible_rect[0], mat_type
        assert result.content_rects[0][1] < visible_rect[1], mat_type


def test_legacy_mat_image_api_still_returns_image() -> None:
    matter = MatImage(
        display_size=(200, 100),
        resource_folder=str(Path(ResourcePaths.packaged_data_dir()) / "mat"),
        mat_type="single_bevel",
        outer_mat_color=(10, 20, 30),
        outer_mat_border=20,
        outer_mat_use_texture=False,
    )

    result = matter.mat_image((Image.new("RGB", (100, 50), "red"),))

    assert isinstance(result, Image.Image)
