"""
Utility module for extracting and caching video frames.

This module provides the VideoFrameExtractor class, which uses FFmpeg to extract
the first and last frames of a video file. These frames are cached as JPEG images
and used by the playback engine to facilitate seamless transitions between images
and videos (the "First/Last Frame Sandwich" pattern).
"""

import json
import logging
import os
import subprocess
import tempfile
import threading
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import Any

from PIL import Image, ImageFilter, ImageOps

from picframe.core.services.resource_paths import PICFRAME_DATA_TOKEN, ResourcePaths
from picframe.mat_image import MatImage

_image_file_lock = threading.Lock()
VIDEO_TRANSITION_FRAME_PROCESSING_VERSION = 4
VIDEO_TRANSITION_FRAME_COORDINATE_SPACE = "frame_pixels"


class _FrameExtractionTimeout(Exception):
    """Internal signal that ffmpeg frame extraction exceeded the playback budget."""


@dataclass(frozen=True)
class VideoFrameMattingConfig:
    """Matting settings used to generate video transition frames."""

    mat_images: Any = 0.01
    mat_type: str | None = None
    outer_mat_color: Any = None
    inner_mat_color: Any = None
    outer_mat_border: int = 75
    inner_mat_border: int = 40
    outer_mat_use_texture: bool = True
    inner_mat_use_texture: bool = False
    mat_resource_folder: str = f"{PICFRAME_DATA_TOKEN}/mat"

    @classmethod
    def from_config(cls, config: Any) -> "VideoFrameMattingConfig | None":
        if config is None:
            return None

        def value(name: str, default: Any) -> Any:
            if isinstance(config, dict):
                return config.get(name, default)
            return getattr(config, name, default)

        return cls(
            mat_images=value("mat_images", 0.01),
            mat_type=value("mat_type", None),
            outer_mat_color=value("outer_mat_color", None),
            inner_mat_color=value("inner_mat_color", None),
            outer_mat_border=int(value("outer_mat_border", 75)),
            inner_mat_border=int(value("inner_mat_border", 40)),
            outer_mat_use_texture=VideoFrameExtractor._as_bool(
                value("outer_mat_use_texture", True)
            ),
            inner_mat_use_texture=VideoFrameExtractor._as_bool(
                value("inner_mat_use_texture", False)
            ),
            mat_resource_folder=str(
                value("mat_resource_folder", f"{PICFRAME_DATA_TOKEN}/mat")
            ),
        )


@dataclass(frozen=True)
class VideoFrameEdgeConfig:
    """Edge-fill settings used to generate video transition frames."""

    blur_edges: bool = False
    blur_amount: int = 12
    blur_zoom: float = 1.0
    edge_alpha: float = 0.5

    @classmethod
    def from_config(cls, config: Any) -> "VideoFrameEdgeConfig | None":
        if config is None:
            return None

        def value(name: str, default: Any) -> Any:
            if isinstance(config, dict):
                return config.get(name, default)
            return getattr(config, name, default)

        return cls(
            blur_edges=VideoFrameExtractor._as_bool(value("blur_edges", False)),
            blur_amount=max(0, int(value("blur_amount", 12))),
            blur_zoom=max(1.0, float(value("blur_zoom", 1.0))),
            edge_alpha=max(0.0, min(1.0, float(value("edge_alpha", 0.5)))),
        )


@dataclass(frozen=True)
class VideoTransitionFrameMetadata:
    """Metadata persisted next to video first/last transition-frame cache files."""

    version: int = VIDEO_TRANSITION_FRAME_PROCESSING_VERSION
    frame_size: tuple[int, int] | None = None
    coordinate_space: str = VIDEO_TRANSITION_FRAME_COORDINATE_SPACE
    matted: bool = False
    content_rect: tuple[int, int, int, int] | None = None
    layout_spec: dict[str, Any] | None = None
    backdrop: bool = False
    processing_signature: str | None = None
    backdrop_path: str | None = None

    def with_backdrop_path(self, backdrop_path: str | None) -> "VideoTransitionFrameMetadata":
        return VideoTransitionFrameMetadata(
            version=self.version,
            frame_size=self.frame_size,
            coordinate_space=self.coordinate_space,
            matted=self.matted,
            content_rect=self.content_rect,
            layout_spec=self.layout_spec,
            backdrop=self.backdrop,
            processing_signature=self.processing_signature,
            backdrop_path=backdrop_path,
        )


@dataclass(frozen=True)
class _ProcessedVideoFrame:
    image: Image.Image
    content_rect: tuple[int, int, int, int]


class VideoFrameExtractor:
    """
    A utility class to extract, process, and cache the first and last frames of a video.
    
    This class uses FFmpeg to extract specific frames from a video file, applies
    scaling and aspect ratio corrections, and caches the results as JPEG images
    to facilitate seamless transitions in the playback engine.
    """

    TAIL_DECODE_WINDOWS_SECONDS = (2.0, 5.0, 10.0)
    FFMPEG_FRAME_TIMEOUT_SECONDS = 8.0

    def __init__(
        self,
        video_path: str,
        display_width: int,
        display_height: int,
        fit_display: bool = False,
        cache_dir: str | None = None,
        background: Any = None,
        matting_config: Any = None,
        edge_config: Any = None,
    ) -> None:
        """
        Initialize the VideoFrameExtractor.

        Args:
            video_path: The absolute path to the video file.
            display_width: The target width of the display in pixels.
            display_height: The target height of the display in pixels.
            fit_display: If True, scales the image to fit within the display dimensions
                         while maintaining aspect ratio. If False, fills the display.
            cache_dir: Optional directory for generated frame cache files. If omitted,
                       legacy sidecar frame paths are used next to the video.
            background: Optional RGBA/RGB float color used for letterbox/pillarbox bars.
            matting_config: Optional renderer matting settings for matted handoff frames.
            edge_config: Optional renderer edge-fill settings for generated bars.
        """
        self.video_path: str = video_path
        self.display_width: int = display_width
        self.display_height: int = display_height
        self.fit_display: bool = fit_display
        self.cache_dir: str | None = cache_dir
        self.background: Any = background
        self.matting_config: VideoFrameMattingConfig | None = (
            matting_config
            if isinstance(matting_config, VideoFrameMattingConfig)
            else VideoFrameMattingConfig.from_config(matting_config)
        )
        self.edge_config: VideoFrameEdgeConfig | None = (
            edge_config
            if isinstance(edge_config, VideoFrameEdgeConfig)
            else VideoFrameEdgeConfig.from_config(edge_config)
        )
        self._background_rgb = self._normalize_background_rgb(background)
        self.last_transition_metadata: VideoTransitionFrameMetadata | None = None
        self.logger: logging.Logger = logging.getLogger("VideoFrameExtractor")

    @staticmethod
    def _source_fingerprint(video_path: str) -> tuple[int, int]:
        try:
            stat = os.stat(video_path)
            mtime_ns = getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))
            return int(stat.st_size), int(mtime_ns)
        except OSError:
            return 0, 0

    @staticmethod
    def get_cached_frame_path(
        video_path: str,
        width: int,
        height: int,
        fit_display: bool,
        role: str,
        cache_dir: str | None = None,
        background: Any = None,
        matting_config: Any = None,
        edge_config: Any = None,
    ) -> str:
        """Return the deterministic path for a cached transition frame."""
        role_suffix = {"first": "1", "last": "2"}.get(role)
        if role_suffix is None:
            raise ValueError(f"Unknown frame role: {role}")

        if not cache_dir:
            base, _ = os.path.splitext(video_path)
            return f"{base}.{role_suffix}.frame"

        digest = VideoFrameExtractor.processing_signature(
            video_path,
            width,
            height,
            fit_display,
            background=background,
            matting_config=matting_config,
            edge_config=edge_config,
            role=role,
        )
        safe_stem = Path(video_path).stem[:48] or "video"
        return str(Path(cache_dir).expanduser() / f"{safe_stem}-{digest}.{role_suffix}.frame")

    def get_frame_path(self, role: str) -> str:
        """Return the cached frame path for this extractor instance."""
        return self.get_cached_frame_path(
            self.video_path,
            self.display_width,
            self.display_height,
            self.fit_display,
            role,
            self.cache_dir,
            background=self.background,
            matting_config=self.matting_config,
            edge_config=self.edge_config,
        )

    def get_metadata_path(self) -> str:
        """Return the sidecar metadata path for this cached transition-frame pair."""
        return self.get_cached_metadata_path(
            self.video_path,
            self.display_width,
            self.display_height,
            self.fit_display,
            self.cache_dir,
            background=self.background,
            matting_config=self.matting_config,
            edge_config=self.edge_config,
        )

    @staticmethod
    def get_cached_metadata_path(
        video_path: str,
        width: int,
        height: int,
        fit_display: bool,
        cache_dir: str | None = None,
        background: Any = None,
        matting_config: Any = None,
        edge_config: Any = None,
    ) -> str:
        """Return the metadata sidecar path for a cached transition-frame pair."""
        first_path = VideoFrameExtractor.get_cached_frame_path(
            video_path,
            width,
            height,
            fit_display,
            "first",
            cache_dir,
            background=background,
            matting_config=matting_config,
            edge_config=edge_config,
        )
        return f"{first_path}.meta.json"

    @staticmethod
    def processing_signature(
        video_path: str,
        width: int,
        height: int,
        fit_display: bool,
        *,
        background: Any = None,
        matting_config: Any = None,
        edge_config: Any = None,
        role: str = "pair",
    ) -> str:
        """Return a short digest for the source and visual processing inputs."""
        payload = VideoFrameExtractor.processing_signature_payload(
            video_path,
            width,
            height,
            fit_display,
            background=background,
            matting_config=matting_config,
            edge_config=edge_config,
            role=role,
        )
        encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        return sha256(encoded).hexdigest()[:24]

    @staticmethod
    def processing_signature_payload(
        video_path: str,
        width: int,
        height: int,
        fit_display: bool,
        *,
        background: Any = None,
        matting_config: Any = None,
        edge_config: Any = None,
        role: str = "pair",
    ) -> dict[str, Any]:
        """Return normalized inputs that affect cached transition-frame pixels."""
        file_size, mtime_ns = VideoFrameExtractor._source_fingerprint(video_path)
        return {
            "path": os.path.abspath(os.path.expanduser(video_path)),
            "size": file_size,
            "mtime_ns": mtime_ns,
            "processing_version": VIDEO_TRANSITION_FRAME_PROCESSING_VERSION,
            "display": [int(width), int(height)],
            "fit_display": bool(fit_display),
            "background": VideoFrameExtractor._normalize_background_rgb(background),
            "matting": VideoFrameExtractor._matting_cache_signature(matting_config),
            "edges": VideoFrameExtractor._edge_cache_signature(edge_config),
            "role": role,
        }

    @staticmethod
    def _normalize_background_rgb(background: Any) -> tuple[int, int, int]:
        try:
            if background is None or len(background) < 3:
                return (0, 0, 0)
            rgb = tuple(float(background[index]) for index in range(3))
        except (TypeError, ValueError, IndexError):
            return (0, 0, 0)
        return tuple(round(max(0.0, min(1.0, value)) * 255) for value in rgb)

    @staticmethod
    def _background_cache_signature(background: Any) -> str:
        red, green, blue = VideoFrameExtractor._normalize_background_rgb(background)
        return f"{red},{green},{blue}"

    @staticmethod
    def _edge_cache_signature(edge_config: Any) -> str:
        config = (
            edge_config
            if isinstance(edge_config, VideoFrameEdgeConfig)
            else VideoFrameEdgeConfig.from_config(edge_config)
        )
        if config is None:
            return "edge:none"
        payload = {
            "blur_edges": config.blur_edges,
            "blur_amount": config.blur_amount,
            "blur_zoom": config.blur_zoom,
            "edge_alpha": config.edge_alpha,
        }
        return json.dumps(payload, sort_keys=True, default=str)

    @staticmethod
    def _as_bool(value: Any) -> bool:
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on", "t", "y"}
        return bool(value)

    @staticmethod
    def _normalize_config_color(value: Any) -> tuple[int, int, int] | None:
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
            value = [part for part in text.replace(",", " ").split() if part]
        try:
            if len(value) < 3:
                return None
            return tuple(
                max(0, min(255, int(float(value[index])))) for index in range(3)
            )
        except (TypeError, ValueError, IndexError):
            return None

    @staticmethod
    def _matting_cache_signature(matting_config: Any) -> str:
        config = (
            matting_config
            if isinstance(matting_config, VideoFrameMattingConfig)
            else VideoFrameMattingConfig.from_config(matting_config)
        )
        if config is None:
            return "mat:none"

        matting_enabled, matting_threshold = VideoFrameExtractor._matting_control(
            config.mat_images
        )
        payload = {
            "matting_control": {
                "enabled": matting_enabled,
                "threshold": matting_threshold,
            },
        }
        if not matting_enabled:
            return json.dumps(payload, sort_keys=True, default=str)

        payload.update(
            {
                "mat_type": config.mat_type,
                "outer_mat_color": VideoFrameExtractor._normalize_config_color(
                    config.outer_mat_color
                ),
                "inner_mat_color": VideoFrameExtractor._normalize_config_color(
                    config.inner_mat_color
                ),
                "outer_mat_border": config.outer_mat_border,
                "inner_mat_border": config.inner_mat_border,
                "outer_mat_use_texture": config.outer_mat_use_texture,
                "inner_mat_use_texture": config.inner_mat_use_texture,
                "mat_resource_signature": VideoFrameExtractor._mat_resource_signature(
                    config.mat_resource_folder
                ),
            }
        )
        return json.dumps(payload, sort_keys=True, default=str)

    @staticmethod
    def _resolved_mat_resource_folder(value: Any) -> str:
        text = "" if value is None else str(value).strip()
        if text == PICFRAME_DATA_TOKEN:
            return str(ResourcePaths.packaged_data_dir())
        if text.startswith(f"{PICFRAME_DATA_TOKEN}/"):
            return str(
                ResourcePaths.packaged_data_dir()
                / text[len(PICFRAME_DATA_TOKEN) + 1:]
            )
        return os.path.expanduser(text)

    @staticmethod
    def _mat_resource_signature(value: Any) -> str:
        folder = Path(VideoFrameExtractor._resolved_mat_resource_folder(value))
        names = (
            "mat_texture.jpg",
            "9_patch_bevel.png",
            "9_patch_drop_shadow.png",
            "9_patch_inner_shadow.png",
            "9_patch_highlight.png",
        )
        parts = []
        for name in names:
            path = folder / name
            try:
                stat = path.stat()
                digest = sha256(path.read_bytes()).hexdigest()[:16]
                parts.append(f"{name}:{stat.st_size}:{digest}")
            except OSError:
                parts.append(f"{name}:missing")
        return "|".join(parts)

    @staticmethod
    def _matting_control(raw_value: Any) -> tuple[bool, float]:
        value = str(raw_value).strip().lower()
        if value in {"true", "yes", "on"}:
            return True, -1.0
        if value in {"false", "no", "off"}:
            return False, 0.01
        try:
            threshold = float(value)
            if threshold == 0.0:
                return False, 0.01
            return True, threshold
        except (TypeError, ValueError):
            return True, 0.01

    @staticmethod
    def _aspect_difference(
        screen_size: tuple[int, int],
        image_size: tuple[int, int],
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

    def _should_mat_frame(self, frame: Image.Image) -> bool:
        config = self.matting_config
        if config is None:
            return False
        enabled, threshold = self._matting_control(config.mat_images)
        if not enabled:
            return False
        if threshold < 0:
            return True
        return (
            self._aspect_difference(
                (self.display_width, self.display_height),
                frame.size,
            )
            > threshold
        )

    def _create_matter(self) -> MatImage:
        config = self.matting_config
        if config is None:
            raise ValueError("matting_config is required")
        return MatImage(
            display_size=(self.display_width, self.display_height),
            resource_folder=self._resolved_mat_resource_folder(config.mat_resource_folder),
            mat_type=config.mat_type,
            outer_mat_color=self._normalize_config_color(config.outer_mat_color),
            inner_mat_color=self._normalize_config_color(config.inner_mat_color),
            outer_mat_border=config.outer_mat_border,
            inner_mat_border=config.inner_mat_border,
            outer_mat_use_texture=config.outer_mat_use_texture,
            inner_mat_use_texture=config.inner_mat_use_texture,
        )

    def _process_transition_frame_pair(
        self,
        first_image: Image.Image,
        last_image: Image.Image,
    ) -> tuple[Image.Image, Image.Image, VideoTransitionFrameMetadata]:
        """Process first/last frames together so video matting can share one layout."""
        if self.fit_display:
            first_frame = self._fit_display_frame(first_image)
            last_frame = self._fit_display_frame(last_image)
            metadata = VideoTransitionFrameMetadata(
                frame_size=first_frame.image.size,
                content_rect=first_frame.content_rect,
            )
            return (
                first_frame.image,
                last_frame.image,
                metadata,
            )

        if self._should_mat_frame(first_image):
            try:
                matter = self._create_matter()
                first_result = matter.mat_image_with_layout((first_image,))
                last_result = matter.mat_image_with_layout(
                    (last_image,),
                    layout_spec=first_result.layout_spec,
                )
                content_rect = (
                    first_result.content_rects[0]
                    if first_result.content_rects
                    else None
                )
                first_frame = first_result.image.convert("RGB")
                content_rect = content_rect or self._full_frame_rect(first_frame)
                metadata = VideoTransitionFrameMetadata(
                    frame_size=first_frame.size,
                    matted=True,
                    content_rect=content_rect,
                    layout_spec=first_result.layout_spec.to_dict(),
                    backdrop=True,
                )
                return (
                    first_frame,
                    last_result.image.convert("RGB"),
                    metadata,
                )
            except Exception as exc:
                self.logger.warning(
                    "Video frame matting failed; using unmatted transition frames: %s",
                    exc,
                )

        first_frame = self._process_video_frame_with_rect(first_image)
        last_frame = self._process_video_frame_with_rect(last_image)
        metadata = VideoTransitionFrameMetadata(
            frame_size=first_frame.image.size,
            content_rect=first_frame.content_rect,
            matted=False,
            backdrop=self._edge_backdrop_enabled(),
        )
        return (
            first_frame.image,
            last_frame.image,
            metadata,
        )

    def _write_transition_metadata(
        self,
        metadata: VideoTransitionFrameMetadata,
    ) -> None:
        metadata = replace(
            metadata,
            processing_signature=self._processing_signature(),
        )
        path = self.get_metadata_path()
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as metadata_file:
                json.dump(asdict(metadata), metadata_file, sort_keys=True)
        except OSError as exc:
            self.logger.debug("Could not write video transition metadata: %s", exc)

    def _load_transition_metadata(self) -> VideoTransitionFrameMetadata | None:
        path = self.get_metadata_path()
        try:
            with open(path, encoding="utf-8") as metadata_file:
                data = json.load(metadata_file)
            content_rect = self._int_tuple(data.get("content_rect"), 4)
            frame_size = self._int_tuple(data.get("frame_size"), 2)
            return VideoTransitionFrameMetadata(
                version=int(data.get("version", 1)),
                frame_size=frame_size,
                coordinate_space=str(
                    data.get(
                        "coordinate_space",
                        VIDEO_TRANSITION_FRAME_COORDINATE_SPACE,
                    )
                ),
                matted=bool(data.get("matted", False)),
                content_rect=content_rect,
                layout_spec=data.get("layout_spec"),
                backdrop=bool(data.get("backdrop", data.get("matted", False))),
                processing_signature=data.get("processing_signature"),
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            self.logger.debug("Could not load video transition metadata: %s", exc)
            return None

    @staticmethod
    def _int_tuple(value: Any, length: int) -> tuple[int, ...] | None:
        try:
            if value is None or len(value) != length:
                return None
            return tuple(int(item) for item in value)
        except (TypeError, ValueError):
            return None

    def _processing_signature(self) -> str:
        return self.processing_signature(
            self.video_path,
            self.display_width,
            self.display_height,
            self.fit_display,
            background=self.background,
            matting_config=self.matting_config,
            edge_config=self.edge_config,
            role="pair",
        )

    def _metadata_matches_current_signature(
        self,
        metadata: VideoTransitionFrameMetadata | None,
    ) -> bool:
        if metadata is None:
            return False
        return (
            metadata.processing_signature == self._processing_signature()
            and self._metadata_has_current_geometry(metadata)
        )

    def _metadata_has_current_geometry(
        self,
        metadata: VideoTransitionFrameMetadata,
    ) -> bool:
        if metadata.version != VIDEO_TRANSITION_FRAME_PROCESSING_VERSION:
            return False
        if metadata.coordinate_space != VIDEO_TRANSITION_FRAME_COORDINATE_SPACE:
            return False
        if metadata.frame_size != (self.display_width, self.display_height):
            return False
        return self._rect_within_frame(metadata.content_rect, metadata.frame_size)

    @staticmethod
    def _rect_within_frame(
        rect: tuple[int, int, int, int] | None,
        frame_size: tuple[int, int] | None,
    ) -> bool:
        if rect is None or frame_size is None:
            return False
        x, y, w, h = rect
        frame_w, frame_h = frame_size
        return (
            frame_w > 0
            and frame_h > 0
            and w > 0
            and h > 0
            and x >= 0
            and y >= 0
            and x + w <= frame_w
            and y + h <= frame_h
        )

    def _metadata_required_for_cache_validation(self) -> bool:
        return True

    def cached_transition_frames_valid(self) -> bool:
        """Return whether cached first/last frames match current processing inputs."""
        if not (
            os.path.exists(self.get_frame_path("first"))
            and os.path.exists(self.get_frame_path("last"))
        ):
            return False
        if not self._metadata_required_for_cache_validation():
            return True
        return self._metadata_matches_current_signature(
            self._load_transition_metadata()
        )

    @staticmethod
    def _full_frame_rect(frame: Image.Image) -> tuple[int, int, int, int]:
        return (0, 0, frame.width, frame.height)

    def _fit_display_frame(self, frame: Image.Image) -> _ProcessedVideoFrame:
        frame = self._as_rgb(frame)
        if self.display_width <= 0 or self.display_height <= 0:
            return _ProcessedVideoFrame(frame, self._full_frame_rect(frame))
        resized = frame.resize(
            (self.display_width, self.display_height),
            resample=Image.Resampling.BICUBIC,
        )
        return _ProcessedVideoFrame(
            resized,
            (0, 0, self.display_width, self.display_height),
        )

    def _scale_frame_with_rect(self, frame: Image.Image) -> _ProcessedVideoFrame:
        """
        Scale a frame to fit or fill the display dimensions.

        Args:
            frame: The Pillow Image object representing the video frame.

        Returns:
            A new Pillow Image object scaled and padded to match the display dimensions.
        """
        frame = self._as_rgb(frame)
        frame_width, frame_height = frame.size
        aspect_ratio_frame = frame_width / frame_height
        aspect_ratio_display = self.display_width / self.display_height

        if aspect_ratio_frame > aspect_ratio_display:
            new_width = self.display_width
            new_height = int(self.display_width / aspect_ratio_frame)
        else:
            new_height = self.display_height
            new_width = int(self.display_height * aspect_ratio_frame)

        resized_frame = frame.resize((new_width, new_height), resample=Image.Resampling.BICUBIC)
        canvas = Image.new("RGB", (self.display_width, self.display_height), self._background_rgb)
        x_offset = (self.display_width - new_width) // 2
        y_offset = (self.display_height - new_height) // 2
        canvas.paste(resized_frame, (x_offset, y_offset))

        return _ProcessedVideoFrame(
            canvas,
            (x_offset, y_offset, new_width, new_height),
        )

    def _scale_frame(self, frame: Image.Image) -> Image.Image:
        return self._scale_frame_with_rect(frame).image

    def _edge_backdrop_enabled(self) -> bool:
        if self.fit_display or self.edge_config is None:
            return False
        return self.edge_config.blur_edges or self.edge_config.edge_alpha > 0.0

    def _process_edge_frame_with_rect(self, frame: Image.Image) -> _ProcessedVideoFrame:
        frame = self._as_rgb(frame)
        if self.display_width <= 0 or self.display_height <= 0:
            return _ProcessedVideoFrame(frame, self._full_frame_rect(frame))
        if self.edge_config is not None and self.edge_config.blur_edges:
            return self._blur_fill_frame_with_rect(frame)
        return self._edge_alpha_frame_with_rect(frame)

    def _process_edge_frame(self, frame: Image.Image) -> Image.Image:
        return self._process_edge_frame_with_rect(frame).image

    def _blur_fill_frame_with_rect(self, frame: Image.Image) -> _ProcessedVideoFrame:
        edge_config = self.edge_config or VideoFrameEdgeConfig()
        display_size = (self.display_width, self.display_height)
        background_size = (
            max(self.display_width, int(self.display_width * edge_config.blur_zoom)),
            max(self.display_height, int(self.display_height * edge_config.blur_zoom)),
        )
        background = ImageOps.fit(
            frame,
            background_size,
            method=Image.Resampling.BICUBIC,
            centering=(0.5, 0.5),
        )
        if edge_config.blur_amount > 0:
            background = background.filter(ImageFilter.GaussianBlur(edge_config.blur_amount))
        background = ImageOps.fit(
            background,
            display_size,
            method=Image.Resampling.BICUBIC,
            centering=(0.5, 0.5),
        )
        content_rect = self._paste_contained_frame(background, frame)
        return _ProcessedVideoFrame(background, content_rect)

    def _blur_fill_frame(self, frame: Image.Image) -> Image.Image:
        return self._blur_fill_frame_with_rect(frame).image

    def _edge_alpha_frame_with_rect(self, frame: Image.Image) -> _ProcessedVideoFrame:
        display_size = (self.display_width, self.display_height)
        background = Image.new("RGB", display_size, self._background_rgb)
        edge_alpha = self.edge_config.edge_alpha if self.edge_config is not None else 0.0
        if edge_alpha > 0.0:
            edge_fill = ImageOps.fit(
                frame,
                display_size,
                method=Image.Resampling.BICUBIC,
                centering=(0.5, 0.5),
            )
            background = Image.blend(background, edge_fill, edge_alpha)
        content_rect = self._paste_contained_frame(background, frame)
        return _ProcessedVideoFrame(background, content_rect)

    def _edge_alpha_frame(self, frame: Image.Image) -> Image.Image:
        return self._edge_alpha_frame_with_rect(frame).image

    def _paste_contained_frame(
        self,
        background: Image.Image,
        frame: Image.Image,
    ) -> tuple[int, int, int, int]:
        foreground = frame.copy()
        foreground.thumbnail(
            (self.display_width, self.display_height),
            resample=Image.Resampling.LANCZOS,
        )
        x_offset = (self.display_width - foreground.width) // 2
        y_offset = (self.display_height - foreground.height) // 2
        background.paste(foreground, (x_offset, y_offset))
        return (x_offset, y_offset, foreground.width, foreground.height)

    @staticmethod
    def _as_rgb(frame: Image.Image) -> Image.Image:
        if frame.mode == "RGB":
            return frame.copy()
        return frame.convert("RGB")

    def _process_video_frame_with_rect(self, frame: Image.Image) -> _ProcessedVideoFrame:
        """
        Process a video frame according to the display configuration.

        Args:
            frame: The Pillow Image object to process.

        Returns:
            The processed Pillow Image object.
        """
        if self.fit_display:
            return self._fit_display_frame(frame)
        if self.edge_config is not None:
            return self._process_edge_frame_with_rect(frame)
        return self._scale_frame_with_rect(frame)

    def _process_video_frame(self, frame: Image.Image) -> Image.Image:
        return self._process_video_frame_with_rect(frame).image

    def _get_frame_as_image(self, seek_time: float) -> Image.Image | None:
        """
        Extract a single frame from the video at the specified time using FFmpeg.

        Args:
            seek_time: The time in seconds to seek to before extracting the frame.

        Returns:
            A Pillow Image object representing the frame, or None if extraction fails.
        """
        try:
            cmd = [
                "ffmpeg",
                "-ss", str(seek_time) if seek_time else "0",
                "-i", self.video_path,
                "-vframes", "1",
                "-f", "image2pipe",
                "-vcodec", "mjpeg",
                "-"
            ]
            process = subprocess.run(
                cmd,
                capture_output=True,
                check=True,
                timeout=self.FFMPEG_FRAME_TIMEOUT_SECONDS,
            )
            import io
            image = Image.open(io.BytesIO(process.stdout))
            image.load()
            return image
        except subprocess.TimeoutExpired as e:
            self.logger.warning(
                "Timed out retrieving video frame at %.3fs after %.1fs: %s",
                seek_time,
                self.FFMPEG_FRAME_TIMEOUT_SECONDS,
                e,
            )
            raise _FrameExtractionTimeout() from e
        except subprocess.CalledProcessError as e:
            stderr = e.stderr.decode(errors="replace") if isinstance(e.stderr, bytes) else e.stderr
            self.logger.warning("Failed to retrieve video frame: %s", stderr or e)
            return None
        except (OSError, ValueError) as e:
            self.logger.warning("Failed to retrieve video frame: %s", e)
            return None

    def _get_final_decoded_frame_as_image(self, duration: float) -> Image.Image | None:
        """Extract the actual final decoded frame by decoding a short tail window."""
        for tail_window in self.TAIL_DECODE_WINDOWS_SECONDS:
            if duration > 0 and duration < tail_window:
                seek_time = 0.0
            else:
                seek_time = max(0.0, duration - tail_window)
            try:
                image = self._decode_tail_last_frame(seek_time, tail_window)
            except _FrameExtractionTimeout:
                self.logger.warning(
                    "Tail-decoded final frame extraction timed out for %s; "
                    "falling back to direct playback without cached final frame.",
                    self.video_path,
                )
                raise
            if image is not None:
                return image

        self.logger.warning(
            "Tail-decoded final frame extraction failed for %s; falling back to "
            "duration-offset extraction.",
            self.video_path,
        )
        try:
            return self._get_duration_offset_last_frame_as_image(duration)
        except _FrameExtractionTimeout:
            self.logger.warning(
                "Duration-offset final frame extraction timed out for %s.",
                self.video_path,
            )
            return None

    def _decode_tail_last_frame(
        self,
        seek_time: float,
        tail_window: float,
    ) -> Image.Image | None:
        """Seek near EOS, decode to the end, and return the final emitted frame."""
        try:
            with tempfile.TemporaryDirectory(prefix="picframe-video-tail-") as tmpdir:
                output_pattern = str(Path(tmpdir) / "frame-%06d.jpg")
                cmd = [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-ss",
                    f"{seek_time:.6f}",
                    "-i",
                    self.video_path,
                    "-an",
                    "-vsync",
                    "0",
                    "-q:v",
                    "2",
                    output_pattern,
                ]
                process = subprocess.run(
                    cmd,
                    capture_output=True,
                    check=True,
                    timeout=self.FFMPEG_FRAME_TIMEOUT_SECONDS,
                )
                frame_paths = sorted(Path(tmpdir).glob("frame-*.jpg"))
                if not frame_paths:
                    stderr = (
                        process.stderr.decode(errors="replace")
                        if isinstance(process.stderr, bytes)
                        else process.stderr
                    )
                    self.logger.warning(
                        "Tail decode produced no frames from %.3fs over %.3fs: %s",
                        seek_time,
                        tail_window,
                        stderr or "no stderr",
                    )
                    return None

                image = Image.open(frame_paths[-1])
                image.load()
                return image.copy()
        except subprocess.TimeoutExpired as e:
            self.logger.warning(
                "Tail decode timed out from %.3fs over %.3fs after %.1fs: %s",
                seek_time,
                tail_window,
                self.FFMPEG_FRAME_TIMEOUT_SECONDS,
                e,
            )
            raise _FrameExtractionTimeout() from e
        except subprocess.CalledProcessError as e:
            stderr = e.stderr.decode(errors="replace") if isinstance(e.stderr, bytes) else e.stderr
            self.logger.warning(
                "Tail decode failed from %.3fs over %.3fs: %s",
                seek_time,
                tail_window,
                stderr or e,
            )
            return None
        except (OSError, ValueError) as e:
            self.logger.warning(
                "Tail decode failed from %.3fs over %.3fs: %s",
                seek_time,
                tail_window,
                e,
            )
            return None

    def _get_duration_offset_last_frame_as_image(self, duration: float) -> Image.Image | None:
        """Legacy fallback: sample a frame near the end using fixed offsets."""
        for offset in [0.1, 0.5, 1.0, 2.0]:
            if duration > offset:
                last_image = self._get_frame_as_image(duration - offset)
                if last_image is not None:
                    return last_image
        return None

    def _apply_sample_aspect_ratio(self, image: Image.Image, sar: str) -> Image.Image:
        """
        Apply the Sample Aspect Ratio (SAR) to correct the image dimensions.

        Args:
            image: The Pillow Image object to correct.
            sar: The Sample Aspect Ratio string (e.g., "1:1", "16:9").

        Returns:
            The corrected Pillow Image object.
        """
        if sar and sar != "1:1":
            try:
                num_str, den_str = sar.split(":")
                num = float(num_str)
                den = float(den_str)
                if num > 0 and den > 0 and num != den:
                    width, height = image.size
                    new_width = int(round(width * num / den))
                    image = image.resize((new_width, height), resample=Image.Resampling.BICUBIC)
            except (ValueError, AttributeError, TypeError) as e:
                self.logger.warning("Could not apply sample_aspect_ratio %s: %s", sar, e)
        return image

    @staticmethod
    def extract_and_save_frames(
        video_path: str,
        duration: float,
        width: int,
        height: int,
        sar: str = "1:1",
        fit_display: bool = False,
        cache_dir: str | None = None,
        background: Any = None,
        matting_config: Any = None,
        edge_config: Any = None,
    ) -> bool:
        """
        Extract and save the first and last frames of the video to disk.

        This method is designed to be called statically, often during the initial
        media indexing phase, to pre-cache frames for seamless playback transitions.

        Args:
            video_path: The absolute path to the video file.
            duration: The total duration of the video in seconds.
            width: The width of the video in pixels.
            height: The height of the video in pixels.
            sar: The Sample Aspect Ratio string (default: "1:1").
            fit_display: Whether frames are cached for fit-display mode.
            cache_dir: Optional directory for generated frame cache files.
            background: Optional RGBA/RGB float color used for generated bars.
            matting_config: Optional renderer matting settings for generated frames.
            edge_config: Optional renderer edge-fill settings for generated bars.

        Returns:
            True if both frames were successfully extracted and saved (or already exist),
            False otherwise.
        """
        logger = logging.getLogger("VideoFrameExtractor")
        extractor = VideoFrameExtractor(
            video_path,
            width,
            height,
            fit_display=fit_display,
            cache_dir=cache_dir,
            background=background,
            matting_config=matting_config,
            edge_config=edge_config,
        )
        first_path = extractor.get_frame_path("first")
        last_path = extractor.get_frame_path("last")

        if extractor.cached_transition_frames_valid():
            return True

        if width == 0 or height == 0 or duration == 0:
            logger.error("Error: Invalid video dimensions or duration.")
            return False

        if cache_dir:
            Path(cache_dir).expanduser().mkdir(parents=True, exist_ok=True)

        try:
            first_image = extractor._get_frame_as_image(0)
            last_image = extractor._get_final_decoded_frame_as_image(duration)
        except _FrameExtractionTimeout:
            logger.warning(
                "Timed out extracting transition frames for %s; video will play directly.",
                video_path,
            )
            return False
                    
        if last_image is None and first_image is not None:
            last_image = first_image.copy()

        if first_image is not None and last_image is not None:
            first_image = extractor._apply_sample_aspect_ratio(first_image, sar)
            last_image = extractor._apply_sample_aspect_ratio(last_image, sar)
            first_image, last_image, metadata = extractor._process_transition_frame_pair(
                first_image,
                last_image,
            )
            
            try:
                with _image_file_lock:
                    first_image.save(first_path, format="JPEG")
                    last_image.save(last_path, format="JPEG")
                    extractor._write_transition_metadata(metadata)
                return True
            except (OSError, ValueError) as e:
                logger.warning("Could not save frames: %s", e)
                return False

        logger.error("Failed to retrieve frames")
        return False

    def get_first_and_last_frames(
        self,
        duration: float,
        width: int,
        height: int,
        sar: str = "1:1",
        *,
        extract_missing: bool = True,
    ) -> tuple[Image.Image, Image.Image] | None:
        """
        Retrieve the first and last frames of the video as Pillow Image objects.
        
        This method will attempt to load cached frames from disk (.1.frame and .2.frame).
        If they do not exist and extract_missing is true, it will extract them, save
        them to disk, and then return them.

        Args:
            duration: The total duration of the video in seconds.
            width: The width of the video in pixels.
            height: The height of the video in pixels.
            sar: The Sample Aspect Ratio string (default: "1:1").
            extract_missing: Whether missing cached frames should be generated.

        Returns:
            A tuple containing the first and last frames as Pillow Image objects,
            or None if extraction or loading fails.
        """
        first_path = self.get_frame_path("first")
        last_path = self.get_frame_path("last")

        if extract_missing:
            self.extract_and_save_frames(
                self.video_path,
                duration,
                width,
                height,
                sar,
                fit_display=self.fit_display,
                cache_dir=self.cache_dir,
                background=self.background,
                matting_config=self.matting_config,
                edge_config=self.edge_config,
            )

        if self.cached_transition_frames_valid():
            try:
                with _image_file_lock:
                    with Image.open(first_path) as first_file:
                        first_image = self._as_rgb(first_file)
                    with Image.open(last_path) as last_file:
                        last_image = self._as_rgb(last_file)
                metadata = self._load_transition_metadata()
                self.last_transition_metadata = (
                    metadata.with_backdrop_path(first_path) if metadata else None
                )
                return first_image, last_image
            except (OSError, ValueError) as e:
                self.logger.warning("Could not load cached frames: %s", e)

        return None

    @staticmethod
    def get_first_frame_as_image(
        video_path: str,
        width: int = 0,
        height: int = 0,
        fit_display: bool = False,
        cache_dir: str | None = None,
        background: Any = None,
        matting_config: Any = None,
        edge_config: Any = None,
    ) -> Image.Image | None:
        """
        Retrieve the cached first frame of a video as a Pillow Image object.

        This method only attempts to load an existing cached frame from disk.
        It does not attempt to extract the frame if it is missing.

        Args:
            video_path: The absolute path to the video file.
            width: The display width used for cached-frame keying.
            height: The display height used for cached-frame keying.
            fit_display: Whether fit-display mode is part of the cache key.
            cache_dir: Optional managed cache directory.
            background: Optional RGBA/RGB float color used for cache keying.
            matting_config: Optional renderer matting settings used for cache keying.
            edge_config: Optional renderer edge-fill settings used for cache keying.

        Returns:
            The first frame as a Pillow Image object, or None if the cached file
            does not exist or cannot be loaded.
        """
        extractor = VideoFrameExtractor(
            video_path,
            width,
            height,
            fit_display=fit_display,
            cache_dir=cache_dir,
            background=background,
            matting_config=matting_config,
            edge_config=edge_config,
        )
        if not extractor.cached_transition_frames_valid():
            return None

        path = extractor.get_frame_path("first")

        if os.path.exists(path):
            try:
                with _image_file_lock:
                    with Image.open(path) as image:
                        return extractor._as_rgb(image)
            except (OSError, ValueError) as e:
                logger = logging.getLogger("VideoFrameExtractor")
                logger.warning("Could not load cached frame: %s", e)
        return None
