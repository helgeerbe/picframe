"""
Video metadata extraction strategy.
"""

import json
import logging
import os
import subprocess

from picframe.core.metadata.interfaces import IMetadataStrategy
from picframe.core.models.media import MediaItem, MediaType

logger = logging.getLogger(__name__)


class VideoMetadataStrategy(IMetadataStrategy):
    """
    Strategy for extracting metadata from video files.
    
    This strategy uses the legacy get_video_meta function to extract
    duration, dimensions, and rotation, and maps them to the unified
    MediaItem model.
    """

    def __init__(
        self,
        display_w: int = 0,
        display_h: int = 0,
        config_repository=None,
        cache_dir: str | None = None,
    ):
        self.display_w = display_w
        self.display_h = display_h
        self._config_repository = config_repository
        self.cache_dir = cache_dir

    def extract(self, filepath: str, directory_id: int) -> MediaItem | None:
        """
        Extract metadata from a video file.

        Args:
            filepath: The absolute path to the video file.
            directory_id: The ID of the directory containing the file.

        Returns:
            A populated MediaItem object, or None if extraction fails.
        """
        try:
            # Get basic file stats
            stat = os.stat(filepath)
            file_size = stat.st_size
            modified_time = stat.st_mtime
            filename = os.path.basename(filepath)

            width = None
            height = None
            duration = 0.0
            orientation = 1 # Default orientation
            codec = None
            pixel_format = None
            framerate = None
            bitrate = None
            
            # Additional fields for parity with image EXIF
            exif_datetime = None
            latitude = None
            longitude = None
            make = None
            model = None
            title = None
            caption = None
            tags_str = None

            try:
                # Extract video metadata using ffprobe
                cmd = [
                    "ffprobe",
                    "-v", "quiet",
                    "-print_format", "json",
                    "-show_format",
                    "-show_streams",
                    filepath
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, check=True)
                probe_data = json.loads(result.stdout)

                # Extract format-level metadata
                if "format" in probe_data:
                    fmt = probe_data["format"]
                    if "duration" in fmt:
                        duration = float(fmt["duration"])
                    if "bit_rate" in fmt:
                        bitrate = int(fmt["bit_rate"])
                    
                    format_tags = fmt.get("tags", {})
                    
                    # Creation date
                    creation_time = format_tags.get("creation_time")
                    if creation_time:
                        try:
                            from datetime import datetime
                            # ffprobe usually returns ISO 8601: 2023-10-27T15:30:00.000000Z
                            dt = datetime.fromisoformat(creation_time.replace('Z', '+00:00'))
                            exif_datetime = dt.timestamp()
                        except ValueError:
                            pass
                            
                    # GPS Coordinates (often in format tags for mp4/mov)
                    location = format_tags.get("location")
                    if location:
                        # Example format: +37.7749-122.4194/
                        import re
                        match = re.match(r'([+-]\d+\.\d+)([+-]\d+\.\d+)', location)
                        if match:
                            latitude = float(match.group(1))
                            longitude = float(match.group(2))
                            
                    # Make and Model
                    make = format_tags.get("make")
                    model = format_tags.get("model")
                    
                    # Title and Caption
                    title = format_tags.get("title")
                    caption = format_tags.get("comment") or format_tags.get("description")
                    
                    # Tags/Keywords
                    keywords = format_tags.get("keywords")
                    if keywords:
                        tags_str = keywords

                # Extract video stream details
                for stream in probe_data.get("streams", []):
                    if stream.get("codec_type") == "video":
                        width = int(stream.get("width", 0)) or None
                        height = int(stream.get("height", 0)) or None
                        codec = stream.get("codec_name")
                        pixel_format = stream.get("pix_fmt")
                        
                        # Extract framerate
                        r_frame_rate = stream.get("r_frame_rate")
                        if r_frame_rate and "/" in r_frame_rate:
                            num, den = r_frame_rate.split("/")
                            if int(den) > 0:
                                framerate = float(num) / float(den)
                        
                        # Handle rotation/orientation if present in stream tags
                        stream_tags = stream.get("tags", {})
                        if "rotate" in stream_tags:
                            rotation = int(stream_tags["rotate"])
                            if rotation == 90:
                                orientation = 6
                            elif rotation == 180:
                                orientation = 3
                            elif rotation == 270:
                                orientation = 8
                        break

            except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError) as e:
                logger.warning(f"ffprobe failed for {filepath}: {e}. Falling back to basic stats.")

            # Extract and cache first/last frames
            if width and height and duration > 0:
                from picframe.core.utils.video_frame_extractor import VideoFrameExtractor
                # We don't have sample_aspect_ratio easily available here, default to 1:1
                # It could be extracted from ffprobe output if needed
                target_w = self.display_w if self.display_w > 0 else width
                target_h = self.display_h if self.display_h > 0 else height
                fit_display = False
                if self._config_repository is not None:
                    fit_display = self._config_repository.get_app_config_bool(
                        "viewer.fit", False
                    )
                frame_cache_kwargs = {}
                if fit_display:
                    frame_cache_kwargs["fit_display"] = fit_display
                if self.cache_dir is not None:
                    frame_cache_kwargs["cache_dir"] = self.cache_dir
                VideoFrameExtractor.extract_and_save_frames(
                    filepath,
                    duration,
                    target_w,
                    target_h,
                    **frame_cache_kwargs,
                )

            return MediaItem(
                filepath=filepath,
                directory_id=directory_id,
                filename=filename,
                media_type=MediaType.VIDEO,
                file_size=file_size,
                last_modified=modified_time,
                width=width,
                height=height,
                orientation=orientation,
                duration=duration,
                codec=codec,
                pixel_format=pixel_format,
                framerate=framerate,
                bitrate=bitrate,
                exif_datetime=exif_datetime,
                latitude=latitude,
                longitude=longitude,
                make=make,
                model=model,
                title=title,
                caption=caption,
                tags=tags_str,
            )

        except Exception as e:
            logger.error(f"Error extracting video metadata for {filepath}: {e}")
            # Fallback to basic file stats if extraction fails
            try:
                stat = os.stat(filepath)
                return MediaItem(
                    filepath=filepath,
                    directory_id=directory_id,
                    filename=os.path.basename(filepath),
                    media_type=MediaType.VIDEO,
                    file_size=stat.st_size,
                    last_modified=stat.st_mtime,
                )
            except OSError:
                return None
