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
def test_extract_file_not_found(
    mock_isfile: MagicMock, strategy: ImageMetadataStrategy
) -> None:
    """Test that extraction returns None if the file does not exist."""
    mock_isfile.return_value = False
    result = strategy.extract("/invalid/path.jpg", 1)
    assert result is None


@patch("os.path.isfile")
@patch("os.stat")
@patch(
    "picframe.core.metadata.image_strategy."
    "ImageMetadataStrategy._get_dimensions"
)
@patch(
    "picframe.core.metadata.image_strategy."
    "ImageMetadataStrategy._get_orientation"
)
@patch(
    "picframe.core.metadata.image_strategy."
    "ImageMetadataStrategy._get_exif_datetime"
)
def test_extract_success(
    mock_get_exif: MagicMock,
    mock_get_orientation: MagicMock,
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
    mock_get_orientation.return_value = 6
    mock_get_exif.return_value = 1678880000.0

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

    with patch.object(strategy, '_get_dimensions', side_effect=Exception("Test error")):
        result = strategy.extract("/path/to/image.jpg", 1)
        
    assert result is not None
    assert result.file_size == 1024
    assert result.last_modified == 1678886400.0
