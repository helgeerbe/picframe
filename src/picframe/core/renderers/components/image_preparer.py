"""Image loading and matting preparation for the pi3d image renderer."""

from __future__ import annotations

import ast
import logging
import os
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageOps

from picframe.core.events.dto import RenderCommand
from picframe.mat_image import MatImage


@dataclass(frozen=True)
class MattingControl:
    """Parsed legacy matting switch and aspect-ratio threshold."""

    enabled: bool
    threshold: float

    @property
    def always(self) -> bool:
        return self.enabled and self.threshold < 0


class ImagePreparer:
    """Loads PIL images and applies optional legacy matting."""

    def __init__(
        self,
        display_size: tuple[int, int],
        config: Any,
        pair_composer: Callable[[Image.Image, Image.Image], Image.Image],
        *,
        matter_factory: Callable[..., Any] = MatImage,
        logger: logging.Logger | None = None,
    ) -> None:
        self._display_size = display_size
        self._pair_composer = pair_composer
        self._matter_factory = matter_factory
        self._logger = logger or logging.getLogger(__name__)
        self._matter: Any | None = None
        self._matting_unavailable = False
        self.update_config(config)

    @staticmethod
    def config_value(config: Any, key: str, default: Any) -> Any:
        if isinstance(config, dict):
            return config.get(key, default)
        return getattr(config, key, default)

    @staticmethod
    def parse_matting_control(raw_value: Any) -> MattingControl:
        """Parse legacy ``viewer.mat_images`` semantics."""
        value = str(raw_value).strip().lower()
        if value in {"true", "yes", "on"}:
            return MattingControl(enabled=True, threshold=-1.0)
        if value in {"false", "no", "off"}:
            return MattingControl(enabled=False, threshold=0.01)

        try:
            return MattingControl(enabled=True, threshold=float(value))
        except (TypeError, ValueError):
            logging.getLogger(__name__).warning(
                "Invalid value for config option 'mat_images'. Using default."
            )
            return MattingControl(enabled=True, threshold=0.01)

    @staticmethod
    def aspect_difference(
        screen_size: tuple[int, int], image_size: tuple[int, int]
    ) -> float:
        screen_w, screen_h = screen_size
        image_w, image_h = image_size
        if screen_w <= 0 or screen_h <= 0 or image_w <= 0 or image_h <= 0:
            return 0.0

        screen_aspect = screen_w / screen_h
        image_aspect = image_w / image_h
        if screen_aspect > image_aspect:
            return 1 - (image_aspect / screen_aspect)
        return 1 - (screen_aspect / image_aspect)

    @staticmethod
    def normalize_color(value: Any) -> tuple[int, int, int] | None:
        """Normalize common RGB config shapes to a tuple accepted by MatImage."""
        if value is None:
            return None

        if isinstance(value, str):
            text = value.strip()
            if not text or text.lower() in {"none", "null"}:
                return None
            if text.startswith("#") and len(text) == 7:
                try:
                    return (
                        int(text[1:3], 16),
                        int(text[3:5], 16),
                        int(text[5:7], 16),
                    )
                except ValueError:
                    return None
            try:
                value = ast.literal_eval(text)
            except (SyntaxError, ValueError):
                value = [part for part in re.split(r"[\s,]+", text) if part]

        if not isinstance(value, Sequence) or isinstance(value, (bytes, bytearray)):
            return None

        if len(value) < 3:
            return None

        try:
            channels = tuple(max(0, min(255, int(float(value[index])))) for index in range(3))
        except (TypeError, ValueError):
            return None
        return channels

    def update_config(self, config: Any) -> None:
        """Refresh matting settings after a runtime config change."""
        self._config = config
        self._control = self.parse_matting_control(
            self.config_value(config, "mat_images", 0.01)
        )
        self._mat_type = self.config_value(config, "mat_type", None)
        self._outer_mat_color = self.normalize_color(
            self.config_value(config, "outer_mat_color", None)
        )
        self._inner_mat_color = self.normalize_color(
            self.config_value(config, "inner_mat_color", None)
        )
        self._outer_mat_border = int(
            self.config_value(config, "outer_mat_border", 75)
        )
        self._inner_mat_border = int(
            self.config_value(config, "inner_mat_border", 40)
        )
        self._outer_mat_use_texture = bool(
            self.config_value(config, "outer_mat_use_texture", True)
        )
        self._inner_mat_use_texture = bool(
            self.config_value(config, "inner_mat_use_texture", False)
        )
        self._mat_resource_folder = os.path.expanduser(
            str(self.config_value(config, "mat_resource_folder", "~/.picframe/data/mat"))
        )
        self._matter = None
        self._matting_unavailable = False

    def load_single_image(self, image_path: str) -> Image.Image:
        image = self._load_image_from_path(image_path)
        return self.prepare_single_image(image)

    def prepare_unmatted_image(self, image: Image.Image) -> Image.Image:
        """Prepare preloaded video-frame images without applying matting."""
        return self._as_rgb(image)

    def load_portrait_pair(self, command: RenderCommand) -> Image.Image:
        image_objs = tuple(command.image_objs or ())
        image_paths = tuple(command.image_paths or ())

        if len(image_objs) >= 2:
            images = [self._as_rgb(image_objs[0]), self._as_rgb(image_objs[1])]
        elif len(image_paths) >= 2:
            images = [
                self._load_image_from_path(image_paths[0]),
                self._load_image_from_path(image_paths[1]),
            ]
        else:
            raise ValueError("portrait_pair render commands require two image paths or objects")

        return self.prepare_portrait_pair(images[0], images[1])

    def prepare_single_image(self, image: Image.Image) -> Image.Image:
        image = self._as_rgb(image)
        if not self.should_mat(image.size):
            return image
        return self._mat_images((image,), image)

    def prepare_portrait_pair(self, left: Image.Image, right: Image.Image) -> Image.Image:
        left = self._as_rgb(left)
        right = self._as_rgb(right)
        fallback = self._pair_composer(left, right)
        if not self.should_mat(left.size):
            return fallback
        return self._mat_images((left, right), fallback)

    def should_mat(self, image_size: tuple[int, int]) -> bool:
        if not self._control.enabled:
            return False
        if self._control.always:
            return True
        return self.aspect_difference(self._display_size, image_size) > self._control.threshold

    def _load_image_from_path(self, image_path: str) -> Image.Image:
        with Image.open(image_path) as image_file:
            return self._as_rgb(ImageOps.exif_transpose(image_file))

    def _as_rgb(self, image: Image.Image) -> Image.Image:
        image = image.copy()
        if image.mode != "RGB":
            return image.convert("RGB")
        return image

    def _get_matter(self) -> Any | None:
        if not self._control.enabled or self._matting_unavailable:
            return None
        if self._matter is not None:
            return self._matter

        try:
            self._matter = self._matter_factory(
                display_size=self._display_size,
                resource_folder=self._mat_resource_folder,
                mat_type=self._mat_type,
                outer_mat_color=self._outer_mat_color,
                inner_mat_color=self._inner_mat_color,
                outer_mat_border=self._outer_mat_border,
                inner_mat_border=self._inner_mat_border,
                outer_mat_use_texture=self._outer_mat_use_texture,
                inner_mat_use_texture=self._inner_mat_use_texture,
            )
        except Exception as exc:
            self._matting_unavailable = True
            self._logger.warning(
                "Matting resources unavailable; using unmatted image: %s", exc
            )
            return None
        return self._matter

    def _mat_images(
        self, images: tuple[Image.Image, ...], fallback: Image.Image
    ) -> Image.Image:
        matter = self._get_matter()
        if matter is None:
            return fallback

        try:
            matted = matter.mat_image(images)
        except Exception as exc:
            self._logger.warning("Matting failed; using unmatted image: %s", exc)
            return fallback

        if isinstance(matted, Image.Image):
            return self._as_rgb(matted)

        self._logger.warning("Matting returned no image; using unmatted image.")
        return fallback
