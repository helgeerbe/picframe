import pytest
from unittest.mock import patch, MagicMock
from PIL import Image
import numpy as np
from typing import Any, Generator

from picframe.core.utils.video_frame_extractor import VideoFrameExtractor

@pytest.fixture
def mock_subprocess_run() -> Generator[MagicMock, None, None]:
    with patch("picframe.core.utils.video_frame_extractor.subprocess.run") as mock_run:
        yield mock_run

@pytest.fixture
def mock_image_fromarray() -> Generator[MagicMock, None, None]:
    with patch("picframe.core.utils.video_frame_extractor.Image.fromarray") as mock_fromarray:
        yield mock_fromarray

def test_get_first_frame_as_image_success() -> None:
    mock_img = MagicMock(spec=Image.Image)
    
    with patch("picframe.core.utils.video_frame_extractor.os.path.exists", return_value=True):
        with patch("picframe.core.utils.video_frame_extractor.Image.open", return_value=mock_img):
            with patch("picframe.core.utils.video_frame_extractor._image_file_lock", create=True):
                result = VideoFrameExtractor.get_first_frame_as_image("test.mp4")
    
    assert result is mock_img

def test_get_first_frame_as_image_not_found() -> None:
    with patch("picframe.core.utils.video_frame_extractor.os.path.exists", return_value=False):
        result = VideoFrameExtractor.get_first_frame_as_image("test.mp4")
    
    assert result is None

@patch("picframe.core.utils.video_frame_extractor.Image.open")
def test_extract_and_save_frames_success(mock_image_open: MagicMock, mock_subprocess_run: MagicMock, mock_image_fromarray: MagicMock) -> None:
    mock_subprocess_run.side_effect = [
        MagicMock(returncode=0, stdout=b"fake_jpeg_data_1"),
        MagicMock(returncode=0, stdout=b"fake_jpeg_data_2")
    ]
    
    mock_img = Image.new("RGB", (1920, 1080), "black")
    mock_image_open.return_value = mock_img
    
    with patch("picframe.core.utils.video_frame_extractor.os.path.exists", return_value=False):
        with patch("picframe.core.utils.video_frame_extractor._image_file_lock", create=True):
            with patch.object(Image.Image, "save") as mock_save:
                result = VideoFrameExtractor.extract_and_save_frames("test.mp4", 10.0, 1920, 1080)
            
    assert result is True
    assert mock_subprocess_run.call_count == 2
    assert mock_save.call_count == 2

def test_extract_and_save_frames_already_exists() -> None:
    with patch("picframe.core.utils.video_frame_extractor.os.path.exists", return_value=True):
        with patch("picframe.core.utils.video_frame_extractor.Image.open") as mock_open:
            mock_img = MagicMock()
            mock_img.size = (1920, 1080)
            mock_open.return_value.__enter__.return_value = mock_img
            result = VideoFrameExtractor.extract_and_save_frames("test.mp4", 10.0, 1920, 1080)
        
    assert result is True

def test_scale_frame_portrait() -> None:
    extractor = VideoFrameExtractor("test.mp4", 1920, 1080, fit_display=False)
    # Portrait image (e.g., 1080x1920)
    portrait_img = Image.new("RGB", (1080, 1920), "red")
    
    scaled_img = extractor._scale_frame(portrait_img)
    
    # Should be padded to 1920x1080
    assert scaled_img.size == (1920, 1080)
    
    # The actual image should be scaled to fit height (1080)
    # New width = 1080 * (1080/1920) = 607.5 -> 607
    # So the center 607 pixels should be red, the rest black
    
    # Check a pixel in the black pillarbox (left)
    assert scaled_img.getpixel((10, 540)) == (0, 0, 0)
    # Check a pixel in the red image (center)
    assert scaled_img.getpixel((960, 540)) == (255, 0, 0)
    # Check a pixel in the black pillarbox (right)
    assert scaled_img.getpixel((1910, 540)) == (0, 0, 0)

def test_scale_frame_landscape() -> None:
    extractor = VideoFrameExtractor("test.mp4", 1920, 1080, fit_display=False)
    # Extremely wide landscape image (e.g., 3840x1080)
    landscape_img = Image.new("RGB", (3840, 1080), "blue")
    
    scaled_img = extractor._scale_frame(landscape_img)
    
    # Should be padded to 1920x1080
    assert scaled_img.size == (1920, 1080)
    
    # The actual image should be scaled to fit width (1920)
    # New height = 1920 / (3840/1080) = 540
    # So the center 540 pixels should be blue, the rest black
    
    # Check a pixel in the black letterbox (top)
    assert scaled_img.getpixel((960, 10)) == (0, 0, 0)
    # Check a pixel in the blue image (center)
    assert scaled_img.getpixel((960, 540)) == (0, 0, 255)
    # Check a pixel in the black letterbox (bottom)
    assert scaled_img.getpixel((960, 1070)) == (0, 0, 0)

def test_process_video_frame_scaling() -> None:
    """Test that _process_video_frame scales the image when fit_display is False."""
    extractor = VideoFrameExtractor("test.mp4", 1920, 1080, fit_display=False)
    frame = Image.new("RGB", (800, 600))

    processed = extractor._process_video_frame(frame)

    # Should return a scaled frame
    assert processed is not frame
    assert processed.size == (1920, 1080)

def test_process_video_frame_no_scaling() -> None:
    """Test that _process_video_frame does not scale the image when fit_display is True."""
    extractor = VideoFrameExtractor("test.mp4", 1920, 1080, fit_display=True)
    frame = Image.new("RGB", (800, 600))

    processed = extractor._process_video_frame(frame)

    # Should return the original frame without scaling
    assert processed is frame
    assert processed.size == (800, 600)
