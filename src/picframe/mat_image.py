import logging
import random
from collections.abc import Sequence
from dataclasses import asdict, dataclass

import numpy as np
from ninepatch import Ninepatch
from PIL import Image, ImageDraw, ImageOps


@dataclass(frozen=True)
class MatLayoutSpec:
    """Reusable mat layout details for rendering matching images."""

    display_size: tuple[int, int]
    mat_type: str
    outer_mat_color: tuple[int, int, int]
    inner_mat_color: tuple[int, int, int] | None
    outer_mat_border: int
    inner_mat_border: int
    outer_mat_use_texture: bool
    inner_mat_use_texture: bool
    content_rects: tuple[tuple[int, int, int, int], ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class MatImageResult:
    """Rendered mat image plus metadata describing where source content landed."""

    image: Image.Image
    layout_spec: MatLayoutSpec
    content_rects: tuple[tuple[int, int, int, int], ...]


class MatImage:
    # region Constructor

    def __init__(
        self,
        display_size: tuple[int, int],
        mat_type: str | None = None,
        outer_mat_color: tuple[int, int, int] | None = None,
        resource_folder: str = ".",
        inner_mat_color: tuple[int, int, int] | None = None,
        outer_mat_border: int = 75,
        inner_mat_border: int = 40,
        outer_mat_use_texture: bool = True,
        inner_mat_use_texture: bool = False,
        auto_inner_mat_color: bool = True,
    ) -> None:

        self.__mat_types = [
            "float",
            "float_polaroid",
            "float_color_wrap",
            "single_bevel",
            "double_bevel",
            "double_flat",
        ]

        self.__logger = logging.getLogger("mat_image.MatImage")

        self.auto_inner_mat_color = auto_inner_mat_color
        self.display_size = display_size
        self.inner_mat_border = inner_mat_border
        self.inner_mat_color = inner_mat_color
        self.mat_type = mat_type
        self.outer_mat_border = outer_mat_border
        self.outer_mat_color = outer_mat_color
        self.outer_mat_use_texture = outer_mat_use_texture
        self.inner_mat_use_texture = inner_mat_use_texture

        # --- Matting resources ---
        self.__mat_texture = Image.open(f"{resource_folder}/mat_texture.jpg").convert("L")
        self.__9patch_bevel = Ninepatch(f"{resource_folder}/9_patch_bevel.png")
        self.__9patch_drop_shadow = Ninepatch(f"{resource_folder}/9_patch_drop_shadow.png")
        self.__9patch_inner_shadow = Ninepatch(f"{resource_folder}/9_patch_inner_shadow.png")
        self.__9patch_highlight = Ninepatch(f"{resource_folder}/9_patch_highlight.png")

    # endregion Constructor

    # region Public Properties

    @property
    def display_size(self) -> tuple[int, int]:
        return self.__display_size

    @display_size.setter
    def display_size(self, val: tuple[int, int]) -> None:
        self.__display_size = val
        self.__display_width, self.__display_height = val

    @property
    def display_width(self) -> int:
        return self.__display_width

    @property
    def display_height(self) -> int:
        return self.__display_height

    @property
    def outer_mat_border(self) -> int:
        return self.__outer_mat_border

    @outer_mat_border.setter
    def outer_mat_border(self, val: int) -> None:
        self.__outer_mat_border = val

    @property
    def inner_mat_border(self) -> int:
        return self.__inner_mat_border

    @inner_mat_border.setter
    def inner_mat_border(self, val: int) -> None:
        self.__inner_mat_border = val

    @property
    def outer_mat_color(self) -> tuple[int, int, int] | None:
        return self.__outer_mat_color

    @outer_mat_color.setter
    def outer_mat_color(self, val: tuple[int, int, int] | None) -> None:
        self.__outer_mat_color = val

    @property
    def inner_mat_color(self) -> tuple[int, int, int] | None:
        return self.__inner_mat_color

    @inner_mat_color.setter
    def inner_mat_color(self, val: tuple[int, int, int] | None) -> None:
        self.__inner_mat_color = val

    @property
    def mat_type(self) -> list[str]:
        return self.__mat_type

    @mat_type.setter
    def mat_type(self, val: str | None) -> None:
        self.__mat_type = self.__get_mat_type_from_user_string(val)

    @property
    def mat_types(self) -> list[str]:
        return self.__mat_types

    @property
    def outer_mat_use_texture(self) -> bool:
        return self.__outer_mat_use_texture

    @outer_mat_use_texture.setter
    def outer_mat_use_texture(self, val: bool) -> None:
        self.__outer_mat_use_texture = val

    @property
    def inner_mat_use_texture(self) -> bool:
        return self.__inner_mat_use_texture

    @inner_mat_use_texture.setter
    def inner_mat_use_texture(self, val: bool) -> None:
        self.__inner_mat_use_texture = val

    # endregion Pubic Properties

    # region Public Methods

    def mat_image(self, images: Sequence[Image.Image]) -> Image.Image | None:

        # Randomly pick a mat type from those specified by the User
        mat_type = random.choice(self.mat_type)

        # If a mat color wasn't specified, get one
        if not self.outer_mat_color:
            self.__outer_mat_color_save = self.__get_outer_mat_color(images[0])
        else:
            assert self.outer_mat_color is not None
            self.__outer_mat_color_save = self.outer_mat_color
        self.__inner_mat_color_save = self.__effective_inner_mat_color()

        if mat_type == "float":
            image = self.__style_float(images)
        elif mat_type == "float_polaroid":
            image = self.__style_float_polaroid(images)
        elif mat_type == "float_color_wrap":
            image = self.__style_float_color_wrap(images)
        elif mat_type == "single_bevel":
            image = self.__style_single_mat_bevel(images)
        elif mat_type == "double_bevel":
            image = self.__style_double_mat_bevel(images)
        elif mat_type == "double_flat":
            image = self.__style_double_mat_flat(images)
        else:
            image = None

        return image

    def mat_image_with_layout(
        self,
        images: Sequence[Image.Image],
        layout_spec: MatLayoutSpec | None = None,
    ) -> MatImageResult:
        """Render images and return the reusable mat layout metadata.

        If ``layout_spec`` is provided, the same mat type and colors are reused.
        This is used by video handoff frames so first/last frames have identical
        mat decoration and content placement.
        """
        images = tuple(images)
        if not images:
            raise ValueError("mat_image_with_layout requires at least one image")

        if layout_spec is None:
            mat_type = random.choice(self.mat_type)
            if not self.outer_mat_color:
                outer_color = self.__get_outer_mat_color(images[0])
            else:
                assert self.outer_mat_color is not None
                outer_color = self.outer_mat_color
            self.__outer_mat_color_save = outer_color
            self.__inner_mat_color_save = self.__effective_inner_mat_color()
        else:
            mat_type = layout_spec.mat_type
            self.__outer_mat_color_save = layout_spec.outer_mat_color
            self.__inner_mat_color_save = (
                layout_spec.inner_mat_color if layout_spec.inner_mat_color is not None else None
            )

        image, computed_content_rects = self.__render_with_rects(images, mat_type)
        if layout_spec is None:
            content_rects = self.__measure_content_rects(
                images,
                mat_type,
                computed_content_rects,
            )
            layout_spec = MatLayoutSpec(
                display_size=self.display_size,
                mat_type=mat_type,
                outer_mat_color=self.__outer_mat_color_save,
                inner_mat_color=(
                    self.__inner_mat_color_save if self.__inner_mat_color_save is not None else None
                ),
                outer_mat_border=int(self.outer_mat_border),
                inner_mat_border=int(self.inner_mat_border),
                outer_mat_use_texture=bool(self.outer_mat_use_texture),
                inner_mat_use_texture=bool(self.inner_mat_use_texture),
                content_rects=tuple(content_rects),
            )
        else:
            content_rects = tuple(layout_spec.content_rects) or tuple(computed_content_rects)

        return MatImageResult(
            image=image,
            layout_spec=layout_spec,
            content_rects=tuple(content_rects),
        )

    # endregion Public Methods

    # region Matting Styles

    def __style_float(self, images: Sequence[Image.Image]) -> Image.Image:
        pic_count = len(images)
        pic_wid = (self.display_width / pic_count) - (
            ((pic_count + 1) / pic_count) * self.outer_mat_border
        )
        pic_height = self.display_height - (self.outer_mat_border * 2)

        final_images: list[Image.Image] = []
        for image in images:
            image = self.__scale_image(image, (pic_wid, pic_height))
            self.__add_image_outline(image, self.__outer_mat_color_save, auto_adjust=True)
            image = self.__add_drop_shadow(image)
            final_images.append(image)

        return self.__layout_images(final_images)

    def __style_float_polaroid(self, images: Sequence[Image.Image]) -> Image.Image:
        border_width = 18
        pic_count = len(images)
        pic_wid = (
            (self.display_width / pic_count)
            - (((pic_count + 1) / pic_count) * self.outer_mat_border)
            - (border_width * 2)
        )
        pic_height = self.display_height - (self.outer_mat_border * 2) - (border_width * 2)

        final_images: list[Image.Image] = []
        for image in images:
            image = self.__scale_image(image, (pic_wid, pic_height))
            self.__add_image_outline(image, self.__outer_mat_color_save)
            image = ImageOps.expand(image, border_width)
            self.__add_image_outline(image, (210, 210, 210), outline_width=border_width)
            image = self.__add_drop_shadow(image)
            final_images.append(image)

        return self.__layout_images(final_images)

    def __style_float_color_wrap(self, images: Sequence[Image.Image]) -> Image.Image:
        border_width = 18
        pic_count = len(images)
        pic_wid = (
            (self.display_width / pic_count)
            - (((pic_count + 1) / pic_count) * self.outer_mat_border)
            - (border_width * 2)
        )
        pic_height = self.display_height - (self.outer_mat_border * 2) - (border_width * 2)

        final_images: list[Image.Image] = []
        for image in images:
            color = self.__get_darker_shade(self.__outer_mat_color_save, 0.35)
            color2 = self.__get_darker_shade(self.__outer_mat_color_save, 0.2)
            image = self.__scale_image(image, (pic_wid, pic_height))
            self.__add_image_outline(image, color2)
            image = ImageOps.expand(image, border_width)
            self.__add_image_outline(image, color, outline_width=border_width)
            highlight = self.__9patch_highlight.render(
                image.width,
                image.height,
                Image.Resampling.LANCZOS,
            )
            image.paste(highlight, (0, 0), highlight)
            image = self.__add_drop_shadow(image)
            final_images.append(image)

        return self.__layout_images(final_images)

    def __style_single_mat_bevel(self, images: Sequence[Image.Image]) -> Image.Image:
        bevel_wid = 5
        pic_count = len(images)
        pic_wid = (
            (self.display_width / pic_count)
            - (((pic_count + 1) / pic_count) * self.outer_mat_border)
            - (bevel_wid * 2)
        )
        pic_height = self.display_height - (self.outer_mat_border * 2) - (bevel_wid * 2)

        final_images: list[Image.Image] = []
        for image in images:
            image = self.__scale_image(image, (pic_wid, pic_height))
            image = self.__add_outer_bevel(image)
            final_images.append(image)

        return self.__layout_images(final_images)

    def __style_double_mat_bevel(self, images: Sequence[Image.Image]) -> Image.Image:
        bevel_wid = 5
        pic_count = len(images)
        pic_wid = (
            (self.display_width / pic_count)
            - (((pic_count + 1) / pic_count) * self.outer_mat_border)
            - (self.inner_mat_border * 2)
            - (bevel_wid * 4)
        )
        pic_height = (
            self.display_height
            - (self.outer_mat_border * 2)
            - (self.inner_mat_border * 2)
            - (bevel_wid * 4)
        )

        final_images: list[Image.Image] = []
        for image in images:
            image = self.__scale_image(image, (pic_wid, pic_height))
            mat_size = (
                image.width + (self.inner_mat_border * 2) + (bevel_wid * 2),
                image.height + (self.inner_mat_border * 2) + (bevel_wid * 2),
            )
            mat_image = self.__get_inner_mat(mat_size)
            mat_image = self.__add_outer_bevel(mat_image)
            image = self.__add_outer_bevel(image)
            mat_image.paste(
                image,
                (
                    self.inner_mat_border + bevel_wid,
                    self.inner_mat_border + bevel_wid,
                ),
            )
            final_images.append(mat_image)

        return self.__layout_images(final_images)

    def __style_double_mat_flat(self, images: Sequence[Image.Image]) -> Image.Image:
        pic_count = len(images)
        pic_wid = (
            (self.display_width / pic_count)
            - (((pic_count + 1) / pic_count) * self.outer_mat_border)
            - (self.inner_mat_border * 2)
        )
        pic_height = self.display_height - (self.outer_mat_border * 2) - (self.inner_mat_border * 2)

        final_images: list[Image.Image] = []
        for image in images:
            image = self.__scale_image(image, (pic_wid, pic_height))
            self.__add_image_outline(image, self.__outer_mat_color_save)
            mat_size = (
                image.width + (self.inner_mat_border * 2),
                image.height + (self.inner_mat_border * 2),
            )
            mat_image = self.__get_inner_mat(mat_size)
            mat_image = self.__add_inner_shadow(mat_image)
            mat_image.paste(image, (self.inner_mat_border, self.inner_mat_border))
            final_images.append(mat_image)

        return self.__layout_images(final_images)

    # endregion Matting styles

    # region Helper Methods

    def __get_mat_type_from_user_string(self, mat_type_string: str | None) -> list[str]:
        if mat_type_string is None:
            mat_type_string = ""

        final: list[str] = []
        mat_type_string = mat_type_string.replace(",", "")  # remove commas from the string
        for type in mat_type_string.split():
            if type in self.mat_types:
                final.append(type)
            else:
                self.__logger.debug("Skipping invalid mat type: %s", type)

        if not final:
            self.__logger.debug("No valid mat types defined - using: %s", self.mat_types)
            final = self.mat_types

        return final

    def __scale_image(
        self, image: Image.Image, size: tuple[float, float] | None = None
    ) -> Image.Image:
        if size is None:
            width: float = float(self.display_size[0])
            height: float = float(self.display_size[1])
        else:
            width, height = size

        scale = min(width / image.width, height / image.height)
        image = image.resize(
            (int(image.width * scale), int(image.height * scale)),
            resample=Image.Resampling.BICUBIC,
        )
        return image

    def __get_outer_mat_color(self, image: Image.Image) -> tuple[int, int, int]:
        k = KmeansNp(k=3, max_iterations=10, size=100)
        colors = k.run(image)
        r, g, b = int(colors[0][0]), int(colors[0][1]), int(colors[0][2])
        return (r, g, b)

    def __get_darker_shade(
        self, rgb_color: tuple[int, int, int], fractional_percent: float = 0.5
    ) -> tuple[int, int, int]:
        return (
            int(rgb_color[0] * fractional_percent),
            int(rgb_color[1] * fractional_percent),
            int(rgb_color[2] * fractional_percent),
        )

    def __effective_inner_mat_color(self) -> tuple[int, int, int] | None:
        if not self.inner_mat_color:
            return self.__get_darker_shade(self.__outer_mat_color_save, 0.50)
        assert self.inner_mat_color is not None
        return self.inner_mat_color

    def __get_colorized_mat(self, color: tuple[int, int, int], use_texture: bool) -> Image.Image:
        if use_texture:
            mat_img = self.__mat_texture.copy()
            mat_img = mat_img.resize(self.display_size, resample=Image.Resampling.BICUBIC)
            mat_img = ImageOps.colorize(mat_img, black="black", white=color)
        else:
            mat_img = Image.new("RGB", self.display_size, color)

        return mat_img

    def __get_inner_mat(self, size: tuple[int, int]) -> Image.Image:
        w, h = size

        color = self.__inner_mat_color_save or self.__effective_inner_mat_color()
        assert color is not None

        mat = self.__get_colorized_mat(color, self.inner_mat_use_texture)
        mat = mat.crop((0, 0, w, h))

        return mat

    def __add_outer_bevel(self, image: Image.Image, expand: bool = True) -> Image.Image:
        if expand:
            image = ImageOps.expand(image, 5)
        outer_bevel_image = self.__9patch_bevel.render(
            image.width,
            image.height,
            Image.Resampling.LANCZOS,
        )
        image.paste(outer_bevel_image, (0, 0), outer_bevel_image)
        return image

    def __add_inner_shadow(self, image: Image.Image) -> Image.Image:
        inner_shadow_image = self.__9patch_inner_shadow.render(
            image.width,
            image.height,
            Image.Resampling.LANCZOS,
        )
        image.paste(inner_shadow_image, (0, 0), inner_shadow_image)
        return image

    def __add_image_outline(
        self,
        img: Image.Image,
        mat_base_color: tuple[int, int, int],
        outline_width: int = 1,
        auto_adjust: bool = False,
    ) -> None:
        if auto_adjust:
            # Calculate the outline color from the mat_color
            brightness = sum(mat_base_color[0:3]) / 3
            outline_color_offset = 30 if brightness < 127 else -30
            outline_color = tuple(x + outline_color_offset for x in mat_base_color)
        else:
            outline_color = mat_base_color

        rect = ImageDraw.Draw(img)
        shape = [0, 0, img.width - 1, img.height - 1]
        rect.rectangle(shape, outline=outline_color, width=outline_width)

    def __add_drop_shadow(self, image: Image.Image) -> Image.Image:
        shadow_offset = 15
        mod_image = Image.new(
            "RGBA",
            (image.width + shadow_offset, image.height + shadow_offset),
            (0, 0, 0, 0),
        )
        shadow_image = self.__9patch_drop_shadow.render(
            mod_image.width,
            mod_image.height,
            Image.Resampling.LANCZOS,
        )
        mod_image.paste(shadow_image, (0, 0), shadow_image)
        mod_image.paste(image, (0, 0))
        return mod_image

    def __render_with_rects(
        self,
        images: Sequence[Image.Image],
        mat_type: str,
    ) -> tuple[Image.Image, tuple[tuple[int, int, int, int], ...]]:
        if mat_type == "float":
            final_images, content_rects = self.__style_float_items(images)
        elif mat_type == "float_polaroid":
            final_images, content_rects = self.__style_float_polaroid_items(images)
        elif mat_type == "float_color_wrap":
            final_images, content_rects = self.__style_float_color_wrap_items(images)
        elif mat_type == "single_bevel":
            final_images, content_rects = self.__style_single_mat_bevel_items(images)
        elif mat_type == "double_bevel":
            final_images, content_rects = self.__style_double_mat_bevel_items(images)
        elif mat_type == "double_flat":
            final_images, content_rects = self.__style_double_mat_flat_items(images)
        else:
            raise ValueError(f"Unknown mat type: {mat_type}")
        return self.__layout_images_with_rects(final_images, content_rects)

    def __style_float_items(
        self, images: Sequence[Image.Image]
    ) -> tuple[list[Image.Image], list[tuple[int, int, int, int]]]:
        pic_count = len(images)
        pic_wid = (self.display_width / pic_count) - (
            ((pic_count + 1) / pic_count) * self.outer_mat_border
        )
        pic_height = self.display_height - (self.outer_mat_border * 2)

        final_images: list[Image.Image] = []
        content_rects: list[tuple[int, int, int, int]] = []
        for image in images:
            image = self.__scale_image(image, (pic_wid, pic_height))
            self.__add_image_outline(image, self.__outer_mat_color_save, auto_adjust=True)
            content_rects.append((1, 1, max(1, image.width - 2), max(1, image.height - 2)))
            image = self.__add_drop_shadow(image)
            final_images.append(image)
        return final_images, content_rects

    def __style_float_polaroid_items(
        self, images: Sequence[Image.Image]
    ) -> tuple[list[Image.Image], list[tuple[int, int, int, int]]]:
        border_width = 18
        pic_count = len(images)
        pic_wid = (
            (self.display_width / pic_count)
            - (((pic_count + 1) / pic_count) * self.outer_mat_border)
            - (border_width * 2)
        )
        pic_height = self.display_height - (self.outer_mat_border * 2) - (border_width * 2)

        final_images: list[Image.Image] = []
        content_rects: list[tuple[int, int, int, int]] = []
        for image in images:
            image = self.__scale_image(image, (pic_wid, pic_height))
            self.__add_image_outline(image, self.__outer_mat_color_save)
            content_w = max(1, image.width - 2)
            content_h = max(1, image.height - 2)
            image = ImageOps.expand(image, border_width)
            self.__add_image_outline(image, (210, 210, 210), outline_width=border_width)
            content_rects.append((border_width + 1, border_width + 1, content_w, content_h))
            image = self.__add_drop_shadow(image)
            final_images.append(image)
        return final_images, content_rects

    def __style_float_color_wrap_items(
        self, images: Sequence[Image.Image]
    ) -> tuple[list[Image.Image], list[tuple[int, int, int, int]]]:
        border_width = 18
        pic_count = len(images)
        pic_wid = (
            (self.display_width / pic_count)
            - (((pic_count + 1) / pic_count) * self.outer_mat_border)
            - (border_width * 2)
        )
        pic_height = self.display_height - (self.outer_mat_border * 2) - (border_width * 2)

        final_images: list[Image.Image] = []
        content_rects: list[tuple[int, int, int, int]] = []
        for image in images:
            color = self.__get_darker_shade(self.__outer_mat_color_save, 0.35)
            color2 = self.__get_darker_shade(self.__outer_mat_color_save, 0.2)
            image = self.__scale_image(image, (pic_wid, pic_height))
            self.__add_image_outline(image, color2)
            content_w = max(1, image.width - 2)
            content_h = max(1, image.height - 2)
            image = ImageOps.expand(image, border_width)
            self.__add_image_outline(image, color, outline_width=border_width)
            highlight = self.__9patch_highlight.render(
                image.width,
                image.height,
                Image.Resampling.LANCZOS,
            )
            image.paste(highlight, (0, 0), highlight)
            content_rects.append((border_width + 1, border_width + 1, content_w, content_h))
            image = self.__add_drop_shadow(image)
            final_images.append(image)
        return final_images, content_rects

    def __style_single_mat_bevel_items(
        self, images: Sequence[Image.Image]
    ) -> tuple[list[Image.Image], list[tuple[int, int, int, int]]]:
        bevel_wid = 5
        pic_count = len(images)
        pic_wid = (
            (self.display_width / pic_count)
            - (((pic_count + 1) / pic_count) * self.outer_mat_border)
            - (bevel_wid * 2)
        )
        pic_height = self.display_height - (self.outer_mat_border * 2) - (bevel_wid * 2)

        final_images: list[Image.Image] = []
        content_rects: list[tuple[int, int, int, int]] = []
        for image in images:
            image = self.__scale_image(image, (pic_wid, pic_height))
            content_rects.append((bevel_wid, bevel_wid, image.width, image.height))
            image = self.__add_outer_bevel(image)
            final_images.append(image)
        return final_images, content_rects

    def __style_double_mat_bevel_items(
        self, images: Sequence[Image.Image]
    ) -> tuple[list[Image.Image], list[tuple[int, int, int, int]]]:
        bevel_wid = 5
        pic_count = len(images)
        pic_wid = (
            (self.display_width / pic_count)
            - (((pic_count + 1) / pic_count) * self.outer_mat_border)
            - (self.inner_mat_border * 2)
            - (bevel_wid * 4)
        )
        pic_height = (
            self.display_height
            - (self.outer_mat_border * 2)
            - (self.inner_mat_border * 2)
            - (bevel_wid * 4)
        )

        final_images: list[Image.Image] = []
        content_rects: list[tuple[int, int, int, int]] = []
        for image in images:
            image = self.__scale_image(image, (pic_wid, pic_height))
            content_w, content_h = image.width, image.height
            mat_size = (
                image.width + (self.inner_mat_border * 2) + (bevel_wid * 2),
                image.height + (self.inner_mat_border * 2) + (bevel_wid * 2),
            )
            mat_image = self.__get_inner_mat(mat_size)
            mat_image = self.__add_outer_bevel(mat_image)
            image = self.__add_outer_bevel(image)
            mat_image.paste(
                image,
                (
                    self.inner_mat_border + bevel_wid,
                    self.inner_mat_border + bevel_wid,
                ),
            )
            content_offset = self.inner_mat_border + (bevel_wid * 3)
            content_rects.append((content_offset, content_offset, content_w, content_h))
            final_images.append(mat_image)
        return final_images, content_rects

    def __style_double_mat_flat_items(
        self, images: Sequence[Image.Image]
    ) -> tuple[list[Image.Image], list[tuple[int, int, int, int]]]:
        pic_count = len(images)
        pic_wid = (
            (self.display_width / pic_count)
            - (((pic_count + 1) / pic_count) * self.outer_mat_border)
            - (self.inner_mat_border * 2)
        )
        pic_height = self.display_height - (self.outer_mat_border * 2) - (self.inner_mat_border * 2)

        final_images: list[Image.Image] = []
        content_rects: list[tuple[int, int, int, int]] = []
        for image in images:
            image = self.__scale_image(image, (pic_wid, pic_height))
            self.__add_image_outline(image, self.__outer_mat_color_save)
            content_w = max(1, image.width - 2)
            content_h = max(1, image.height - 2)
            mat_size = (
                image.width + (self.inner_mat_border * 2),
                image.height + (self.inner_mat_border * 2),
            )
            mat_image = self.__get_inner_mat(mat_size)
            mat_image = self.__add_inner_shadow(mat_image)
            mat_image.paste(image, (self.inner_mat_border, self.inner_mat_border))
            content_rects.append(
                (self.inner_mat_border + 1, self.inner_mat_border + 1, content_w, content_h)
            )
            final_images.append(mat_image)
        return final_images, content_rects

    def __layout_images(self, images: Sequence[Image.Image]) -> Image.Image:
        mat_image, _content_rects = self.__layout_images_with_rects(
            images,
            tuple((0, 0, image.width, image.height) for image in images),
        )
        return mat_image

    def __layout_images_with_rects(
        self,
        images: Sequence[Image.Image],
        content_rects: Sequence[tuple[int, int, int, int]],
    ) -> tuple[Image.Image, tuple[tuple[int, int, int, int], ...]]:
        mat_image = self.__get_colorized_mat(
            self.__outer_mat_color_save,
            self.outer_mat_use_texture,
        )
        total_wid = self.outer_mat_border * (len(images) + 1)
        for image in images:
            total_wid += image.width

        xloc = int((mat_image.width - total_wid) / 2)
        final_rects: list[tuple[int, int, int, int]] = []
        for image in images:
            xloc += self.outer_mat_border
            yloc = int((mat_image.height - image.height) / 2)
            if image.mode == "RGBA":
                mat_image.paste(image, (xloc, yloc), image)
            else:
                mat_image.paste(image, (xloc, yloc))
            if content_rects:
                rect_x, rect_y, rect_w, rect_h = content_rects[len(final_rects)]
                final_rects.append((xloc + rect_x, yloc + rect_y, rect_w, rect_h))
            xloc += image.width

        return mat_image, tuple(final_rects)

    def __measure_content_rects(
        self,
        images: Sequence[Image.Image],
        mat_type: str,
        fallback_rects: Sequence[tuple[int, int, int, int]],
    ) -> tuple[tuple[int, int, int, int], ...]:
        fallback_rects = tuple(fallback_rects)
        try:
            sentinel_colors = tuple(
                self.__sentinel_color(index) for index, _image in enumerate(images)
            )
            sentinel_images = tuple(
                Image.new("RGB", image.size, sentinel_colors[index])
                for index, image in enumerate(images)
            )
            sentinel_render, _fallback_rects = self.__render_with_rects(
                sentinel_images,
                mat_type,
            )
            measured_rects: list[tuple[int, int, int, int]] = []
            for color, fallback_rect in zip(sentinel_colors, fallback_rects):
                rect = self.__color_bbox(sentinel_render, color)
                if rect is None:
                    raise ValueError(f"sentinel color {color} was not visible")
                if not self.__rect_within(rect, fallback_rect):
                    raise ValueError(f"measured rect {rect} exceeded computed rect {fallback_rect}")
                measured_rects.append(rect)
            if len(measured_rects) != len(fallback_rects):
                raise ValueError(
                    f"measured {len(measured_rects)} rects for {len(fallback_rects)} images"
                )
            return tuple(measured_rects)
        except Exception as exc:
            self.__logger.warning(
                "Could not measure mat content rects; using computed rects: %s",
                exc,
            )
            return fallback_rects

    @staticmethod
    def __sentinel_color(index: int) -> tuple[int, int, int]:
        palette = (
            (253, 5, 121),
            (7, 251, 199),
            (241, 229, 3),
            (83, 19, 251),
            (251, 137, 11),
            (23, 191, 17),
        )
        if index < len(palette):
            return palette[index]
        return (
            (37 + index * 73) % 256,
            (97 + index * 151) % 256,
            (193 + index * 199) % 256,
        )

    @staticmethod
    def __color_bbox(
        image: Image.Image, color: tuple[int, int, int]
    ) -> tuple[int, int, int, int] | None:
        pixels = np.asarray(image.convert("RGB"))
        target = np.asarray(color, dtype=pixels.dtype)
        mask = np.all(pixels == target, axis=2)
        if not mask.any():
            return None
        ys, xs = np.where(mask)
        x_min = int(xs.min())
        y_min = int(ys.min())
        return (
            x_min,
            y_min,
            int(xs.max()) - x_min + 1,
            int(ys.max()) - y_min + 1,
        )

    @staticmethod
    def __rect_within(
        inner: tuple[int, int, int, int],
        outer: tuple[int, int, int, int],
    ) -> bool:
        inner_x, inner_y, inner_w, inner_h = inner
        outer_x, outer_y, outer_w, outer_h = outer
        return (
            inner_w > 0
            and inner_h > 0
            and inner_x >= outer_x
            and inner_y >= outer_y
            and inner_x + inner_w <= outer_x + outer_w
            and inner_y + inner_h <= outer_y + outer_h
        )


class KmeansNp:
    def __init__(
        self,
        k: int = 3,
        max_iterations: int = 5,
        min_distance: float = 5.0,
        size: int = 200,
    ) -> None:
        self.k = k
        self.max_iterations = max_iterations
        self.min_distance = min_distance
        self.size = (size, size)

    def run(
        self,
        image: Image.Image,
        start_clusters: list[list[float]] | None = None,
    ) -> np.ndarray:
        image = image.copy()
        image.thumbnail(self.size)
        im = np.array(image, dtype=float)[:, :, :3]
        d = im.shape[-1]  # 3 or 5 if u,v added
        # Floats avoid coercing to uint8 and scrambling subtractions.
        im = im.reshape(-1, d)
        n = len(im)
        if start_clusters is None:
            centroids = im[np.random.choice(np.arange(n), self.k)]
        else:
            centroids = np.array(start_clusters, dtype=float)
        old_centroids = centroids.copy()
        for i in range(self.max_iterations):
            im.shape = (1, n, d)  # add dimension to allow broadcasting
            centroids.shape = (self.k, 1, d)  # ditto
            dists = (
                ((im - centroids) ** 2).sum(axis=2)
            ) ** 0.5  # euclidean distance - manhattan might be fine and faster # noqa: E501
            ix = np.argmin(dists, axis=0)  # indices of nearest centroid for each pixel
            im.shape = (n, d)  # reduce dimensions for mean
            centroids.shape = (self.k, d)  # ditto
            to_keep = []  # discard any centroids with no pixels nearest to them
            for j in range(self.k):  # write back average location of all nearest pixels
                j_pixels = im[ix == j]  # view into im where ix points to centroid j
                if len(j_pixels) > 0:
                    centroids[j] = j_pixels.mean(axis=0)
                    to_keep.append(j)
            if len(to_keep) < len(centroids):  # this will be relatively rare
                for j in to_keep[::-1]:  # delete in reverse order of index
                    centroids = np.delete(centroids, j, axis=0)
                    old_centroids = np.delete(old_centroids, j, axis=0)
            movement = ((((centroids - old_centroids) ** 2).sum(axis=1)) ** 0.5).max()
            if movement < self.min_distance:
                break
            old_centroids = centroids.copy()

        c_max, c_min = (
            centroids[:, :3].max(axis=1),
            centroids[:, :3].min(axis=1),
        )
        c_sat = (
            c_max - c_min
        )  # value used previously includes element of lum TODO bias more to lighter using (1.5 * c_max - c_min) # noqa: E501
        ix_order = np.argsort(c_sat)[::-1]  # indices to sorted values - reversed
        result: np.ndarray = centroids[ix_order, :3].astype(np.uint8)
        return result


if __name__ == "__main__":
    save_folder = "/home/pi/pic_save"
    file1 = "/home/pi/Pictures/Sagelight/2011-01-22_12-05-18-10_edited.jpg"
    file2 = "/home/pi/Pictures/Sagelight/2011-01-22_12-06-07-10_edited.jpg"
    image1 = Image.open(file1)
    image2 = Image.open(file2)
    images = (image1, image2)

    matter = MatImage((1920, 1080))

    for mat_type in matter.mat_types:
        matter.mat_type = mat_type
        img = matter.mat_image(images)
        assert img is not None
        img.save(f"{save_folder}/{mat_type}_texture.jpg")
