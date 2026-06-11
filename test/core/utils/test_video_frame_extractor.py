import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PIL import Image
from typing import Any, Generator

from picframe.core.utils.video_frame_extractor import (
    VideoFrameExtractor,
    _FrameExtractionTimeout,
)

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
    mock_subprocess_run.return_value = MagicMock(returncode=0, stdout=b"fake_jpeg_data_1")
    
    mock_img = Image.new("RGB", (1920, 1080), "black")
    mock_image_open.return_value = mock_img
    
    with patch("picframe.core.utils.video_frame_extractor.os.path.exists", return_value=False):
        with patch("picframe.core.utils.video_frame_extractor._image_file_lock", create=True):
            with patch.object(Image.Image, "save") as mock_save:
                with patch.object(
                    VideoFrameExtractor,
                    "_get_final_decoded_frame_as_image",
                    return_value=mock_img,
                ) as mock_final_frame:
                    result = VideoFrameExtractor.extract_and_save_frames("test.mp4", 10.0, 1920, 1080)
            
    assert result is True
    assert mock_subprocess_run.call_count == 1
    mock_final_frame.assert_called_once_with(10.0)
    assert mock_save.call_count == 2

def test_extract_and_save_frames_already_exists() -> None:
    with patch("picframe.core.utils.video_frame_extractor.os.path.exists", return_value=True):
        with patch("picframe.core.utils.video_frame_extractor.Image.open") as mock_open:
            mock_img = MagicMock()
            mock_img.size = (1920, 1080)
            mock_open.return_value.__enter__.return_value = mock_img
            result = VideoFrameExtractor.extract_and_save_frames("test.mp4", 10.0, 1920, 1080)
        
    assert result is True


def test_cached_frame_path_uses_managed_cache_and_media_freshness(tmp_path: Path) -> None:
    video_path = tmp_path / "holiday clip.mp4"
    cache_dir = tmp_path / "cache"
    video_path.write_bytes(b"first version")
    os.utime(video_path, ns=(1_000_000_000, 1_000_000_000))

    first_path = VideoFrameExtractor.get_cached_frame_path(
        str(video_path), 1920, 1080, False, "first", str(cache_dir)
    )
    repeated_path = VideoFrameExtractor.get_cached_frame_path(
        str(video_path), 1920, 1080, False, "first", str(cache_dir)
    )
    last_path = VideoFrameExtractor.get_cached_frame_path(
        str(video_path), 1920, 1080, False, "last", str(cache_dir)
    )
    fit_path = VideoFrameExtractor.get_cached_frame_path(
        str(video_path), 1920, 1080, True, "first", str(cache_dir)
    )
    resized_path = VideoFrameExtractor.get_cached_frame_path(
        str(video_path), 1280, 720, False, "first", str(cache_dir)
    )

    assert first_path == repeated_path
    assert Path(first_path).parent == cache_dir
    assert Path(first_path).name.startswith("holiday clip-")
    assert first_path.endswith(".1.frame")
    assert last_path.endswith(".2.frame")
    assert first_path != last_path
    assert first_path != fit_path
    assert first_path != resized_path
    assert first_path != str(video_path.with_suffix(".1.frame"))

    video_path.write_bytes(b"second version")
    os.utime(video_path, ns=(2_000_000_000, 2_000_000_000))
    changed_path = VideoFrameExtractor.get_cached_frame_path(
        str(video_path), 1920, 1080, False, "first", str(cache_dir)
    )

    assert changed_path != first_path


def test_get_first_and_last_frames_cache_only_does_not_extract_missing_frames(
    tmp_path: Path,
) -> None:
    extractor = VideoFrameExtractor(
        str(tmp_path / "missing.mp4"),
        1920,
        1080,
        cache_dir=str(tmp_path / "cache"),
    )

    with patch.object(VideoFrameExtractor, "extract_and_save_frames") as mock_extract:
        frames = extractor.get_first_and_last_frames(
            10.0,
            1920,
            1080,
            extract_missing=False,
        )

    assert frames is None
    mock_extract.assert_not_called()


@patch("picframe.core.utils.video_frame_extractor.Image.open")
def test_extract_and_save_frames_writes_managed_cache_paths(
    mock_image_open: MagicMock,
    mock_subprocess_run: MagicMock,
    tmp_path: Path,
) -> None:
    video_path = tmp_path / "video.mp4"
    cache_dir = tmp_path / "cache"
    video_path.write_bytes(b"video")
    mock_subprocess_run.return_value = MagicMock(returncode=0, stdout=b"fake_jpeg_data_1")
    mock_image_open.return_value = Image.new("RGB", (1920, 1080), "black")

    with patch.object(Image.Image, "save") as mock_save:
        with patch.object(
            VideoFrameExtractor,
            "_get_final_decoded_frame_as_image",
            return_value=Image.new("RGB", (1920, 1080), "black"),
        ):
            result = VideoFrameExtractor.extract_and_save_frames(
                str(video_path), 10.0, 1920, 1080, cache_dir=str(cache_dir)
            )

    saved_paths = [Path(call.args[0]) for call in mock_save.call_args_list]
    assert result is True
    assert cache_dir.exists()
    assert len(saved_paths) == 2
    assert all(path.parent == cache_dir for path in saved_paths)
    assert {path.suffix for path in saved_paths} == {".frame"}
    assert str(video_path.with_suffix(".1.frame")) not in {str(path) for path in saved_paths}


def test_final_decoded_frame_uses_tail_decode_window(
    mock_subprocess_run: MagicMock,
    tmp_path: Path,
) -> None:
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"video")

    def fake_run(cmd: list[str], **kwargs: Any) -> MagicMock:
        output_pattern = Path(cmd[-1])
        Image.new("RGB", (10, 10), "red").save(output_pattern.parent / "frame-000001.jpg")
        Image.new("RGB", (10, 10), "blue").save(output_pattern.parent / "frame-000002.jpg")
        return MagicMock(returncode=0, stderr=b"")

    mock_subprocess_run.side_effect = fake_run
    extractor = VideoFrameExtractor(str(video_path), 10, 10, fit_display=True)

    image = extractor._get_final_decoded_frame_as_image(10.0)

    assert image is not None
    assert image.getpixel((0, 0)) == (0, 0, 254)
    cmd = mock_subprocess_run.call_args.args[0]
    assert cmd[cmd.index("-ss") + 1] == "8.000000"
    assert mock_subprocess_run.call_args.kwargs["timeout"] == (
        VideoFrameExtractor.FFMPEG_FRAME_TIMEOUT_SECONDS
    )


def test_final_decoded_frame_tries_fallback_tail_windows(
    mock_subprocess_run: MagicMock,
    tmp_path: Path,
) -> None:
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"video")
    calls = 0

    def fake_run(cmd: list[str], **kwargs: Any) -> MagicMock:
        nonlocal calls
        calls += 1
        if calls == 2:
            output_pattern = Path(cmd[-1])
            Image.new("RGB", (10, 10), "green").save(output_pattern.parent / "frame-000001.jpg")
        return MagicMock(returncode=0, stderr=b"")

    mock_subprocess_run.side_effect = fake_run
    extractor = VideoFrameExtractor(str(video_path), 10, 10, fit_display=True)

    image = extractor._get_final_decoded_frame_as_image(10.0)

    assert image is not None
    assert image.getpixel((0, 0)) == (0, 128, 1)
    seek_times = [
        call.args[0][call.args[0].index("-ss") + 1]
        for call in mock_subprocess_run.call_args_list
    ]
    assert seek_times == ["8.000000", "5.000000"]


def test_final_decoded_frame_falls_back_to_duration_offsets() -> None:
    extractor = VideoFrameExtractor("test.mp4", 10, 10, fit_display=True)
    fallback_frame = Image.new("RGB", (10, 10), "purple")

    with patch.object(extractor, "_decode_tail_last_frame", return_value=None):
        with patch.object(
            extractor,
            "_get_frame_as_image",
            side_effect=[None, fallback_frame],
        ) as mock_get_frame:
            image = extractor._get_final_decoded_frame_as_image(10.0)

    assert image is fallback_frame
    assert [call.args[0] for call in mock_get_frame.call_args_list] == [9.9, 9.5]


def test_extract_and_save_frames_returns_false_on_first_frame_timeout(
    mock_subprocess_run: MagicMock,
) -> None:
    mock_subprocess_run.side_effect = subprocess.TimeoutExpired(
        cmd=["ffmpeg"],
        timeout=VideoFrameExtractor.FFMPEG_FRAME_TIMEOUT_SECONDS,
    )

    with patch("picframe.core.utils.video_frame_extractor.os.path.exists", return_value=False):
        result = VideoFrameExtractor.extract_and_save_frames("test.mp4", 10.0, 1920, 1080)

    assert result is False


def test_final_decoded_frame_aborts_on_tail_decode_timeout(
    mock_subprocess_run: MagicMock,
) -> None:
    mock_subprocess_run.side_effect = subprocess.TimeoutExpired(
        cmd=["ffmpeg"],
        timeout=VideoFrameExtractor.FFMPEG_FRAME_TIMEOUT_SECONDS,
    )
    extractor = VideoFrameExtractor("test.mp4", 10, 10, fit_display=True)

    with pytest.raises(_FrameExtractionTimeout):
        extractor._get_final_decoded_frame_as_image(10.0)

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
