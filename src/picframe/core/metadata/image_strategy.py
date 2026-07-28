"""
Image metadata extraction strategy.

This module implements the IMetadataStrategy for image files, utilizing
PIL (Pillow) and exifread to extract dimensions, orientation, and EXIF data.
"""

import logging
import os
from datetime import datetime
from typing import Any

import exifread
from PIL import Image, UnidentifiedImageError
from PIL.IptcImagePlugin import getiptcinfo

try:
    from pi_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    pass

from picframe.core.metadata.interfaces import IMetadataStrategy
from picframe.core.models.media import MediaItem, MediaType

logger = logging.getLogger(__name__)


class ImageMetadataStrategy(IMetadataStrategy):
    """
    Strategy for extracting metadata from image files.

    This class handles parsing image dimensions, orientation, and EXIF
    creation dates. It gracefully handles missing or corrupted EXIF data.
    """

    def extract(self, filepath: str, directory_id: int) -> MediaItem | None:
        """
        Extract metadata from an image file.

        Args:
            filepath: The absolute path to the image file.
            directory_id: The ID of the directory containing the file.

        Returns:
            A populated MediaItem object, or None if extraction fails.
        """
        if not os.path.isfile(filepath):
            logger.warning(f"File not found: {filepath}")
            return None

        try:
            file_stat = os.stat(filepath)
            file_size = file_stat.st_size
            last_modified = file_stat.st_mtime
            filename = os.path.basename(filepath)

            width, height = self._get_dimensions(filepath)

            # Extract all EXIF data in one pass
            exif_data = self._get_all_exif(filepath)

            # Extract IPTC data
            iptc_data = self._get_iptc_data(filepath)

            # Extract XMP data
            xmp_data = self._get_xmp_data(filepath)

            orientation = exif_data.get("orientation", 1)
            exif_datetime = exif_data.get("exif_datetime")
            # Legacy behavior: when no EXIF date is found, fall back to the file's
            # modification time so the DB always has a valid timestamp. This keeps
            # date-range SQL filters working on exif_datetime without runtime fallbacks.
            if exif_datetime is None:
                exif_datetime = last_modified
            f_number = exif_data.get("f_number")
            exposure_time = exif_data.get("exposure_time")
            iso = exif_data.get("iso")
            focal_length = exif_data.get("focal_length")
            make = exif_data.get("make")
            model = exif_data.get("model")
            lens = exif_data.get("lens")
            title = iptc_data.get("title") or xmp_data.get("title") or exif_data.get("title")
            caption = (
                iptc_data.get("caption") or xmp_data.get("caption") or exif_data.get("caption")
            )
            tags = iptc_data.get("tags") or xmp_data.get("tags") or exif_data.get("tags")
            latitude = exif_data.get("latitude")
            longitude = exif_data.get("longitude")

            # Round coordinates to 4 decimal places for proximity caching (~11m resolution)
            if latitude is not None:
                latitude = round(latitude, 4)
            if longitude is not None:
                longitude = round(longitude, 4)

            is_portrait = self._is_portrait(width, height, orientation)

            return MediaItem(
                filepath=filepath,
                filename=filename,
                directory_id=directory_id,
                media_type=MediaType.IMAGE,
                file_size=file_size,
                last_modified=last_modified,
                width=width,
                height=height,
                orientation=orientation,
                exif_datetime=exif_datetime,
                f_number=f_number,
                exposure_time=exposure_time,
                iso=iso,
                focal_length=focal_length,
                make=make,
                model=model,
                lens=lens,
                title=title,
                caption=caption,
                tags=tags,
                is_portrait=is_portrait,
                latitude=latitude,
                longitude=longitude,
            )
        except Exception as e:
            logger.error(f"Failed to extract metadata from {filepath}: {e}")
            # Fallback to basic file stats if extraction fails completely
            return MediaItem(
                filepath=filepath,
                filename=os.path.basename(filepath),
                directory_id=directory_id,
                media_type=MediaType.IMAGE,
                file_size=os.stat(filepath).st_size,
                last_modified=os.stat(filepath).st_mtime,
            )

    def _get_dimensions(self, filepath: str) -> tuple[int | None, int | None]:
        """
        Retrieve the width and height of the image using PIL.

        Args:
            filepath: The path to the image file.

        Returns:
            A tuple of (width, height), or (None, None) if parsing fails.
        """
        try:
            with Image.open(filepath) as img:
                return img.width, img.height
        except UnidentifiedImageError:
            logger.warning(f"Could not identify image format: {filepath}")
            return None, None
        except Exception as e:
            logger.warning(f"Error reading dimensions for {filepath}: {e}")
            return None, None

    @staticmethod
    def _is_portrait(
        width: int | None,
        height: int | None,
        orientation: int | None,
    ) -> bool | None:
        """Return display-orientation portrait status from dimensions and EXIF orientation."""
        if width is None or height is None:
            return None

        try:
            orientation_value = int(orientation or 1)
        except (TypeError, ValueError):
            orientation_value = 1

        display_width, display_height = width, height
        if orientation_value in {5, 6, 7, 8}:
            display_width, display_height = height, width

        return display_height > display_width

    def _get_all_exif(self, filepath: str) -> dict[str, Any]:
        """
        Retrieve all relevant EXIF tags in a single pass.

        Args:
            filepath: The path to the image file.

        Returns:
            A dictionary containing the extracted EXIF data.
        """
        exif_data: dict[str, Any] = {}
        try:
            with open(filepath, "rb") as f:
                tags = exifread.process_file(f, details=False)

                if "Image Orientation" in tags:
                    val = tags["Image Orientation"].values
                    if isinstance(val, list) and len(val) > 0:
                        exif_data["orientation"] = int(val[0])

                if "EXIF DateTimeOriginal" in tags:
                    try:
                        date_str = str(tags["EXIF DateTimeOriginal"])
                        dt = datetime.strptime(date_str, "%Y:%m:%d %H:%M:%S")
                        exif_data["exif_datetime"] = dt.timestamp()
                    except ValueError:
                        logger.debug(f"Invalid EXIF date format in {filepath}")

                if "EXIF FNumber" in tags:
                    val = tags["EXIF FNumber"].values
                    if isinstance(val, list) and len(val) > 0:
                        # exifread returns Ratio objects, convert to float
                        ratio = val[0]
                        if ratio.den != 0:
                            exif_data["f_number"] = float(ratio.num) / float(ratio.den)

                if "EXIF ExposureTime" in tags:
                    exif_data["exposure_time"] = str(tags["EXIF ExposureTime"])

                iso_keys = ["EXIF ISOSpeedRatings", "EXIF PhotographicSensitivity", "EXIF ISO"]
                for key in iso_keys:
                    if key in tags:
                        val = tags[key].values
                        if isinstance(val, list) and len(val) > 0:
                            exif_data["iso"] = int(val[0])
                            break

                if "EXIF FocalLength" in tags:
                    val = tags["EXIF FocalLength"].values
                    if isinstance(val, list) and len(val) > 0:
                        ratio = val[0]
                        if ratio.den != 0:
                            exif_data["focal_length"] = str(float(ratio.num) / float(ratio.den))

                if "Image Make" in tags:
                    exif_data["make"] = str(tags["Image Make"])

                if "Image Model" in tags:
                    exif_data["model"] = str(tags["Image Model"])

                if "EXIF LensModel" in tags:
                    exif_data["lens"] = str(tags["EXIF LensModel"])

                if "Image ImageDescription" in tags:
                    exif_data["caption"] = str(tags["Image ImageDescription"])

                # IPTC tags are not natively supported by exifread in a straightforward way,
                # but sometimes title/caption are stored in EXIF UserComment or XPTitle
                if "Image XPTitle" in tags:
                    # XPTitle is usually utf-16le encoded byte array
                    try:
                        val = tags["Image XPTitle"].values
                        if isinstance(val, list):
                            exif_data["title"] = bytes(val).decode("utf-16le").rstrip("\x00")
                    except Exception:
                        pass

                if "Image XPComment" in tags:
                    try:
                        val = tags["Image XPComment"].values
                        if isinstance(val, list):
                            exif_data["caption"] = bytes(val).decode("utf-16le").rstrip("\x00")
                    except Exception:
                        pass

                if "Image XPKeywords" in tags:
                    try:
                        val = tags["Image XPKeywords"].values
                        if isinstance(val, list):
                            exif_data["tags"] = bytes(val).decode("utf-16le").rstrip("\x00")
                    except Exception:
                        pass

                # GPS Data
                if (
                    "GPS GPSLatitude" in tags
                    and "GPS GPSLatitudeRef" in tags
                    and "GPS GPSLongitude" in tags
                    and "GPS GPSLongitudeRef" in tags
                ):
                    try:
                        lat_val = tags["GPS GPSLatitude"].values
                        lat_ref = tags["GPS GPSLatitudeRef"].values
                        lon_val = tags["GPS GPSLongitude"].values
                        lon_ref = tags["GPS GPSLongitudeRef"].values

                        if (
                            isinstance(lat_val, list)
                            and len(lat_val) == 3
                            and isinstance(lon_val, list)
                            and len(lon_val) == 3
                        ):
                            lat = (
                                float(lat_val[0].num) / float(lat_val[0].den)
                                + (float(lat_val[1].num) / float(lat_val[1].den)) / 60.0
                                + (float(lat_val[2].num) / float(lat_val[2].den)) / 3600.0
                            )
                            if lat_ref == "S":
                                lat = -lat

                            lon = (
                                float(lon_val[0].num) / float(lon_val[0].den)
                                + (float(lon_val[1].num) / float(lon_val[1].den)) / 60.0
                                + (float(lon_val[2].num) / float(lon_val[2].den)) / 3600.0
                            )
                            if lon_ref == "W":
                                lon = -lon

                            exif_data["latitude"] = lat
                            exif_data["longitude"] = lon
                    except Exception as e:
                        logger.debug(f"Error parsing GPS data for {filepath}: {e}")

        except Exception as e:
            logger.debug(f"Error reading EXIF data for {filepath}: {e}")

        return exif_data

    def _get_iptc_data(self, filepath: str) -> dict[str, Any]:
        """
        Retrieve IPTC tags using PIL.

        Args:
            filepath: The path to the image file.

        Returns:
            A dictionary containing the extracted IPTC data.
        """
        iptc_data: dict[str, Any] = {}
        try:
            with Image.open(filepath) as img:
                iptc = getiptcinfo(img)
                if iptc:
                    # (2, 5) Object Name / Title
                    # (2, 105) Headline
                    if (2, 5) in iptc:
                        val: Any = iptc[(2, 5)]
                        if isinstance(val, list) and len(val) > 0:
                            iptc_data["title"] = val[0].decode("utf-8", errors="ignore")
                        elif isinstance(val, bytes):
                            iptc_data["title"] = val.decode("utf-8", errors="ignore")
                    elif (2, 105) in iptc:
                        val: Any = iptc[(2, 105)]
                        if isinstance(val, list) and len(val) > 0:
                            iptc_data["title"] = val[0].decode("utf-8", errors="ignore")
                        elif isinstance(val, bytes):
                            iptc_data["title"] = val.decode("utf-8", errors="ignore")

                    # (2, 120) Caption/Abstract
                    if (2, 120) in iptc:
                        val: Any = iptc[(2, 120)]
                        if isinstance(val, list) and len(val) > 0:
                            iptc_data["caption"] = val[0].decode("utf-8", errors="ignore")
                        elif isinstance(val, bytes):
                            iptc_data["caption"] = val.decode("utf-8", errors="ignore")

                    # (2, 25) Keywords
                    if (2, 25) in iptc:
                        keywords: Any = iptc[(2, 25)]
                        if isinstance(keywords, list):
                            iptc_data["tags"] = ", ".join(
                                k.decode("utf-8", errors="ignore")
                                if isinstance(k, bytes)
                                else str(k)
                                for k in keywords
                            )
                        elif isinstance(keywords, bytes):
                            iptc_data["tags"] = keywords.decode("utf-8", errors="ignore")
        except Exception as e:
            logger.debug(f"Error reading IPTC data for {filepath}: {e}")

        return iptc_data

    def _find_xmp_key(self, key: str, dic: dict[str, Any]) -> Any:
        for k, v in dic.items():
            if key == k:
                return v
            elif isinstance(v, dict):
                val = self._find_xmp_key(key, v)
                if val:
                    return val
            elif isinstance(v, list):
                for x in v:
                    if isinstance(x, dict):
                        val = self._find_xmp_key(key, x)
                        if val:
                            return val
        return None

    def _get_xmp_data(self, filepath: str) -> dict[str, Any]:
        """
        Retrieve XMP tags using PIL.

        Args:
            filepath: The path to the image file.

        Returns:
            A dictionary containing the extracted XMP data.
        """
        xmp_data: dict[str, Any] = {}
        try:
            with Image.open(filepath) as img:
                if hasattr(img, "getxmp"):
                    xmp = img.getxmp()
                    if xmp:
                        # title
                        val = self._find_xmp_key("Headline", xmp)
                        if val and isinstance(val, str) and len(val) > 0:
                            xmp_data["title"] = val

                        # caption
                        val = self._find_xmp_key("description", xmp)
                        if (
                            val
                            and isinstance(val, dict)
                            and "Alt" in val
                            and "li" in val["Alt"]
                            and "text" in val["Alt"]["li"]
                        ):
                            text_val = val["Alt"]["li"]["text"]
                            if text_val and isinstance(text_val, str) and len(text_val) > 0:
                                xmp_data["caption"] = text_val

                        # tags
                        val = self._find_xmp_key("subject", xmp)
                        if val and isinstance(val, dict) and "Bag" in val and "li" in val["Bag"]:
                            li_val = val["Bag"]["li"]
                            if li_val and isinstance(li_val, list) and len(li_val) > 0:
                                xmp_data["tags"] = ", ".join(str(tag) for tag in li_val)
        except Exception as e:
            logger.debug(f"Error reading XMP data for {filepath}: {e}")

        return xmp_data
