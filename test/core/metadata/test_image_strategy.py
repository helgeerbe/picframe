"""
Unit tests for the ImageMetadataStrategy.

This module verifies the extraction of metadata from image files, including
dimensions, orientation, and EXIF data.
"""

from unittest.mock import MagicMock, patch

import pytest

from picframe.core.metadata.image_strategy import ImageMetadataStrategy
from picframe.core.models.media import MediaType


@pytest.fixture
def strategy() -> ImageMetadataStrategy:
    """Provide an ImageMetadataStrategy instance for testing."""
    return ImageMetadataStrategy()


@patch("os.path.isfile")
def test_extract_file_not_found(mock_isfile: MagicMock, strategy: ImageMetadataStrategy) -> None:
    """Test that extraction returns None if the file does not exist."""
    mock_isfile.return_value = False
    result = strategy.extract("/invalid/path.jpg", 1)
    assert result is None


@patch("os.path.isfile")
@patch("os.stat")
@patch("picframe.core.metadata.image_strategy.ImageMetadataStrategy._get_dimensions")
@patch("picframe.core.metadata.image_strategy.ImageMetadataStrategy._get_all_exif")
@patch("picframe.core.metadata.image_strategy.ImageMetadataStrategy._get_iptc_data")
@patch("picframe.core.metadata.image_strategy.ImageMetadataStrategy._get_xmp_data")
def test_extract_success(
    mock_get_xmp: MagicMock,
    mock_get_iptc: MagicMock,
    mock_get_exif: MagicMock,
    mock_get_dimensions: MagicMock,
    mock_stat: MagicMock,
    mock_isfile: MagicMock,
    strategy: ImageMetadataStrategy,
) -> None:
    """Test successful extraction of image metadata."""
    mock_isfile.return_value = True

    mock_stat_result = MagicMock()
    mock_stat_result.st_size = 1024
    mock_stat_result.st_mtime = 1678886400.0
    mock_stat.return_value = mock_stat_result

    mock_get_dimensions.return_value = (1920, 1080)
    mock_get_exif.return_value = {
        "orientation": 6,
        "exif_datetime": 1678880000.0,
        "f_number": 2.8,
        "iso": 100,
    }
    mock_get_iptc.return_value = {"title": "Test Title", "tags": "test, image"}
    mock_get_xmp.return_value = {"caption": "Test Caption"}

    result = strategy.extract("/path/to/image.jpg", 1)

    assert result is not None
    assert result.filepath == "/path/to/image.jpg"
    assert result.filename == "image.jpg"
    assert result.directory_id == 1
    assert result.media_type == MediaType.IMAGE
    assert result.file_size == 1024
    assert result.last_modified == 1678886400.0
    assert result.width == 1920
    assert result.height == 1080
    assert result.orientation == 6
    assert result.exif_datetime == 1678880000.0
    assert result.f_number == 2.8
    assert result.iso == 100
    assert result.title == "Test Title"
    assert result.caption == "Test Caption"
    assert result.tags == "test, image"
    assert result.is_portrait is True


@patch("os.path.isfile")
@patch("os.stat")
@patch("picframe.core.metadata.image_strategy.ImageMetadataStrategy._get_dimensions")
@patch("picframe.core.metadata.image_strategy.ImageMetadataStrategy._get_all_exif")
@patch("picframe.core.metadata.image_strategy.ImageMetadataStrategy._get_iptc_data")
@patch("picframe.core.metadata.image_strategy.ImageMetadataStrategy._get_xmp_data")
def test_extract_falls_back_to_last_modified_when_no_exif_datetime(
    mock_get_xmp: MagicMock,
    mock_get_iptc: MagicMock,
    mock_get_exif: MagicMock,
    mock_get_dimensions: MagicMock,
    mock_stat: MagicMock,
    mock_isfile: MagicMock,
    strategy: ImageMetadataStrategy,
) -> None:
    """When EXIF datetime is absent, exif_datetime should fall back to last_modified (#719)."""
    mock_isfile.return_value = True
    mock_stat_result = MagicMock()
    mock_stat_result.st_size = 1024
    mock_stat_result.st_mtime = 1678886400.0
    mock_stat.return_value = mock_stat_result
    mock_get_dimensions.return_value = (1920, 1080)
    # No "exif_datetime" key — simulates missing EXIF date
    mock_get_exif.return_value = {"orientation": 1}
    mock_get_iptc.return_value = {}
    mock_get_xmp.return_value = {}

    result = strategy.extract("/path/to/image.jpg", 1)

    assert result is not None
    assert result.exif_datetime == 1678886400.0
    assert result.last_modified == 1678886400.0


@patch("os.path.isfile")
@patch("os.stat")
@patch("picframe.core.metadata.image_strategy.ImageMetadataStrategy._get_dimensions")
@patch("picframe.core.metadata.image_strategy.ImageMetadataStrategy._get_all_exif")
@patch("picframe.core.metadata.image_strategy.ImageMetadataStrategy._get_iptc_data")
@patch("picframe.core.metadata.image_strategy.ImageMetadataStrategy._get_xmp_data")
def test_extract_prefers_exif_datetime_over_last_modified(
    mock_get_xmp: MagicMock,
    mock_get_iptc: MagicMock,
    mock_get_exif: MagicMock,
    mock_get_dimensions: MagicMock,
    mock_stat: MagicMock,
    mock_isfile: MagicMock,
    strategy: ImageMetadataStrategy,
) -> None:
    """When EXIF datetime is present, it should be used instead of last_modified (#719)."""
    mock_isfile.return_value = True
    mock_stat_result = MagicMock()
    mock_stat_result.st_size = 1024
    mock_stat_result.st_mtime = 1678886400.0
    mock_stat.return_value = mock_stat_result
    mock_get_dimensions.return_value = (1920, 1080)
    mock_get_exif.return_value = {
        "orientation": 1,
        "exif_datetime": 1678880000.0,
    }
    mock_get_iptc.return_value = {}
    mock_get_xmp.return_value = {}

    result = strategy.extract("/path/to/image.jpg", 1)

    assert result is not None
    assert result.exif_datetime == 1678880000.0
    assert result.last_modified == 1678886400.0


def _extract_with_dimensions(
    strategy: ImageMetadataStrategy,
    dimensions: tuple[int, int],
    orientation: int,
):
    with (
        patch("os.path.isfile", return_value=True),
        patch("os.stat") as mock_stat,
        patch.object(strategy, "_get_dimensions", return_value=dimensions),
        patch.object(strategy, "_get_all_exif", return_value={"orientation": orientation}),
        patch.object(strategy, "_get_iptc_data", return_value={}),
        patch.object(strategy, "_get_xmp_data", return_value={}),
    ):
        mock_stat_result = MagicMock()
        mock_stat_result.st_size = 1024
        mock_stat_result.st_mtime = 1678886400.0
        mock_stat.return_value = mock_stat_result

        return strategy.extract("/path/to/image.jpg", 1)


@pytest.mark.parametrize(
    ("dimensions", "orientation", "expected_is_portrait"),
    [
        ((1920, 1080), 1, False),
        ((1080, 1920), 1, True),
        ((1920, 1080), 6, True),
    ],
)
def test_extract_sets_orientation_aware_is_portrait(
    strategy: ImageMetadataStrategy,
    dimensions: tuple[int, int],
    orientation: int,
    expected_is_portrait: bool,
) -> None:
    """Test that images are marked portrait based on display orientation."""
    result = _extract_with_dimensions(strategy, dimensions, orientation)

    assert result is not None
    assert result.is_portrait is expected_is_portrait


@patch("os.path.isfile")
@patch("os.stat")
def test_extract_exception_handling(
    mock_stat: MagicMock,
    mock_isfile: MagicMock,
    strategy: ImageMetadataStrategy,
) -> None:
    """Test that extraction returns fallback MediaItem if an unexpected exception occurs."""
    mock_isfile.return_value = True

    mock_stat_result = MagicMock()
    mock_stat_result.st_size = 1024
    mock_stat_result.st_mtime = 1678886400.0
    mock_stat.return_value = mock_stat_result

    with patch.object(strategy, "_get_dimensions", side_effect=Exception("Test error")):
        result = strategy.extract("/path/to/image.jpg", 1)

    assert result is not None
    assert result.file_size == 1024
    assert result.last_modified == 1678886400.0
