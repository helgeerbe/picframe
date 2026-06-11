"""
Utility module for extracting and caching video frames.

This module provides the VideoFrameExtractor class, which uses FFmpeg to extract
the first and last frames of a video file. These frames are cached as JPEG images
and used by the playback engine to facilitate seamless transitions between images
and videos (the "First/Last Frame Sandwich" pattern).
"""

import logging
import os
import subprocess
import tempfile
import threading
from hashlib import sha256
from pathlib import Path
from typing import cast

from PIL import Image

_image_file_lock = threading.Lock()

class VideoFrameExtractor:
    """
    A utility class to extract, process, and cache the first and last frames of a video.
    
    This class uses FFmpeg to extract specific frames from a video file, applies
    scaling and aspect ratio corrections, and caches the results as JPEG images
    to facilitate seamless transitions in the playback engine.
    """

    TAIL_DECODE_WINDOWS_SECONDS = (2.0, 5.0, 10.0)

    def __init__(
        self,
        video_path: str,
        display_width: int,
        display_height: int,
        fit_display: bool = False,
        cache_dir: str | None = None,
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
        """
        self.video_path: str = video_path
        self.display_width: int = display_width
        self.display_height: int = display_height
        self.fit_display: bool = fit_display
        self.cache_dir: str | None = cache_dir
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
    ) -> str:
        """Return the deterministic path for a cached transition frame."""
        role_suffix = {"first": "1", "last": "2"}.get(role)
        if role_suffix is None:
            raise ValueError(f"Unknown frame role: {role}")

        if not cache_dir:
            base, _ = os.path.splitext(video_path)
            return f"{base}.{role_suffix}.frame"

        file_size, mtime_ns = VideoFrameExtractor._source_fingerprint(video_path)
        absolute_path = os.path.abspath(os.path.expanduser(video_path))
        signature = "|".join(
            [
                absolute_path,
                str(file_size),
                str(mtime_ns),
                str(width),
                str(height),
                str(bool(fit_display)),
                role,
            ]
        )
        digest = sha256(signature.encode("utf-8")).hexdigest()[:24]
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
        )

    def _scale_frame(self, frame: Image.Image) -> Image.Image:
        """
        Scale a frame to fit or fill the display dimensions.

        Args:
            frame: The Pillow Image object representing the video frame.

        Returns:
            A new Pillow Image object scaled and padded to match the display dimensions.
        """
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
        canvas = Image.new("RGB", (self.display_width, self.display_height), "black")
        x_offset = (self.display_width - new_width) // 2
        y_offset = (self.display_height - new_height) // 2
        canvas.paste(resized_frame, (x_offset, y_offset))

        return canvas

    def _process_video_frame(self, frame: Image.Image) -> Image.Image:
        """
        Process a video frame according to the display configuration.

        Args:
            frame: The Pillow Image object to process.

        Returns:
            The processed Pillow Image object.
        """
        if not self.fit_display:
            return self._scale_frame(frame)
        return frame

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
            process = subprocess.run(cmd, capture_output=True, check=True)
            import io
            image = Image.open(io.BytesIO(process.stdout))
            image.load()
            return image
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
            image = self._decode_tail_last_frame(seek_time, tail_window)
            if image is not None:
                return image

        self.logger.warning(
            "Tail-decoded final frame extraction failed for %s; falling back to "
            "duration-offset extraction.",
            self.video_path,
        )
        return self._get_duration_offset_last_frame_as_image(duration)

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
                process = subprocess.run(cmd, capture_output=True, check=True)
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

        Returns:
            True if both frames were successfully extracted and saved (or already exist),
            False otherwise.
        """
        logger = logging.getLogger("VideoFrameExtractor")
        first_path = VideoFrameExtractor.get_cached_frame_path(
            video_path, width, height, fit_display, "first", cache_dir
        )
        last_path = VideoFrameExtractor.get_cached_frame_path(
            video_path, width, height, fit_display, "last", cache_dir
        )

        if os.path.exists(first_path) and os.path.exists(last_path):
            return True

        if width == 0 or height == 0 or duration == 0:
            logger.error("Error: Invalid video dimensions or duration.")
            return False

        if cache_dir:
            Path(cache_dir).expanduser().mkdir(parents=True, exist_ok=True)

        # Create a temporary instance just to use the extraction methods
        extractor = VideoFrameExtractor(video_path, width, height, fit_display=fit_display, cache_dir=cache_dir)
        
        first_image = extractor._get_frame_as_image(0)
        last_image = extractor._get_final_decoded_frame_as_image(duration)
                    
        if last_image is None and first_image is not None:
            last_image = first_image.copy()

        if first_image is not None and last_image is not None:
            first_image = extractor._apply_sample_aspect_ratio(first_image, sar)
            last_image = extractor._apply_sample_aspect_ratio(last_image, sar)
            
            try:
                with _image_file_lock:
                    first_image.save(first_path, format="JPEG")
                    last_image.save(last_path, format="JPEG")
                return True
            except (OSError, ValueError) as e:
                logger.warning("Could not save frames: %s", e)
                return False

        logger.error("Failed to retrieve frames")
        return False

    def get_first_and_last_frames(
        self, duration: float, width: int, height: int, sar: str = "1:1"
    ) -> tuple[Image.Image, Image.Image] | None:
        """
        Retrieve the first and last frames of the video as Pillow Image objects.
        
        This method will attempt to load cached frames from disk (.1.frame and .2.frame).
        If they do not exist, it will extract them, save them to disk, and then return them.

        Args:
            duration: The total duration of the video in seconds.
            width: The width of the video in pixels.
            height: The height of the video in pixels.
            sar: The Sample Aspect Ratio string (default: "1:1").

        Returns:
            A tuple containing the first and last frames as Pillow Image objects,
            or None if extraction or loading fails.
        """
        first_path = self.get_frame_path("first")
        last_path = self.get_frame_path("last")

        # Ensure frames exist
        self.extract_and_save_frames(
            self.video_path,
            duration,
            width,
            height,
            sar,
            fit_display=self.fit_display,
            cache_dir=self.cache_dir,
        )

        if os.path.exists(first_path) and os.path.exists(last_path):
            try:
                with _image_file_lock:
                    first_image = cast(Image.Image, Image.open(first_path))
                    last_image = cast(Image.Image, Image.open(last_path))
                first_image = self._process_video_frame(first_image)
                last_image = self._process_video_frame(last_image)
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

        Returns:
            The first frame as a Pillow Image object, or None if the cached file
            does not exist or cannot be loaded.
        """
        path = VideoFrameExtractor.get_cached_frame_path(
            video_path, width, height, fit_display, "first", cache_dir
        )

        if os.path.exists(path):
            try:
                with _image_file_lock:
                    image = cast(Image.Image, Image.open(path))
                return image
            except (OSError, ValueError) as e:
                logger = logging.getLogger("VideoFrameExtractor")
                logger.warning("Could not load cached frame: %s", e)
        return None
