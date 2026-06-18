import json
import os
import subprocess
from collections.abc import Generator
from hashlib import sha256
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PIL import Image

from picframe.core.utils.video_frame_extractor import (
    VIDEO_TRANSITION_FRAME_COORDINATE_SPACE,
    VIDEO_TRANSITION_FRAME_PROCESSING_VERSION,
    VideoFrameEdgeConfig,
    VideoFrameExtractor,
    VideoFrameMattingConfig,
    VideoTransitionFrameMetadata,
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


def _color_bbox(
    image: Image.Image,
    color: tuple[int, int, int],
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

def test_get_first_frame_as_image_success(tmp_path: Path) -> None:
    video_path = tmp_path / "test.mp4"
    cache_dir = tmp_path / "cache"
    video_path.write_bytes(b"video")
    extractor = VideoFrameExtractor(str(video_path), 10, 10, cache_dir=str(cache_dir))
    first_path = Path(extractor.get_frame_path("first"))
    last_path = Path(extractor.get_frame_path("last"))
    first_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (10, 10), "red").save(first_path, format="JPEG")
    Image.new("RGB", (10, 10), "blue").save(last_path, format="JPEG")
    extractor._write_transition_metadata(
        VideoTransitionFrameMetadata(
            frame_size=(10, 10),
            content_rect=(0, 0, 10, 10),
        )
    )

    result = VideoFrameExtractor.get_first_frame_as_image(
        str(video_path),
        10,
        10,
        cache_dir=str(cache_dir),
    )

    assert result is not None
    assert result.size == (10, 10)

def test_get_first_frame_as_image_not_found() -> None:
    with patch("picframe.core.utils.video_frame_extractor.os.path.exists", return_value=False):
        result = VideoFrameExtractor.get_first_frame_as_image("test.mp4")
    
    assert result is None


def test_get_first_frame_as_image_rejects_stale_legacy_sidecar(tmp_path: Path) -> None:
    video_path = tmp_path / "test.mp4"
    video_path.write_bytes(b"video")
    Image.new("RGB", (10, 10), "red").save(tmp_path / "test.1.frame", format="JPEG")
    Image.new("RGB", (10, 10), "blue").save(tmp_path / "test.2.frame", format="JPEG")

    result = VideoFrameExtractor.get_first_frame_as_image(
        str(video_path),
        10,
        10,
        edge_config=VideoFrameEdgeConfig(edge_alpha=0.5),
    )

    assert result is None

@patch("picframe.core.utils.video_frame_extractor.Image.open")
def test_extract_and_save_frames_success(
    mock_image_open: MagicMock,
    mock_subprocess_run: MagicMock,
    mock_image_fromarray: MagicMock,
    tmp_path: Path,
) -> None:
    video_path = tmp_path / "test.mp4"
    video_path.write_bytes(b"video")
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
                    result = VideoFrameExtractor.extract_and_save_frames(
                        str(video_path),
                        10.0,
                        1920,
                        1080,
                    )
            
    assert result is True
    assert mock_subprocess_run.call_count == 1
    mock_final_frame.assert_called_once_with(10.0)
    assert mock_save.call_count == 2

def test_extract_and_save_frames_already_exists() -> None:
    with patch.object(
        VideoFrameExtractor,
        "cached_transition_frames_valid",
        return_value=True,
    ):
        result = VideoFrameExtractor.extract_and_save_frames(
            "test.mp4",
            10.0,
            1920,
            1080,
            cache_dir="/tmp/picframe-cache",
        )
        
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
    background_path = VideoFrameExtractor.get_cached_frame_path(
        str(video_path),
        1920,
        1080,
        False,
        "first",
        str(cache_dir),
        background=(0.2, 0.2, 0.3, 1.0),
    )
    matted_path = VideoFrameExtractor.get_cached_frame_path(
        str(video_path),
        1920,
        1080,
        False,
        "first",
        str(cache_dir),
        background=(0.2, 0.2, 0.3, 1.0),
        matting_config=VideoFrameMattingConfig(mat_images="on", mat_type="double_flat"),
    )
    edge_path = VideoFrameExtractor.get_cached_frame_path(
        str(video_path),
        1920,
        1080,
        False,
        "first",
        str(cache_dir),
        background=(0.2, 0.2, 0.3, 1.0),
        edge_config=VideoFrameEdgeConfig(edge_alpha=0.5),
    )

    assert first_path == repeated_path
    assert Path(first_path).parent == cache_dir
    assert Path(first_path).name.startswith("holiday clip-")
    assert first_path.endswith(".1.frame")
    assert last_path.endswith(".2.frame")
    assert first_path != last_path
    assert first_path != fit_path
    assert first_path != resized_path
    assert first_path != background_path
    assert background_path != matted_path
    assert background_path != edge_path
    assert first_path != str(video_path.with_suffix(".1.frame"))

    video_path.write_bytes(b"second version")
    os.utime(video_path, ns=(2_000_000_000, 2_000_000_000))
    changed_path = VideoFrameExtractor.get_cached_frame_path(
        str(video_path), 1920, 1080, False, "first", str(cache_dir)
    )

    assert changed_path != first_path


def test_cached_frame_path_ignores_background_for_legacy_sidecar_path() -> None:
    assert VideoFrameExtractor.get_cached_frame_path(
        "test.mp4",
        1920,
        1080,
        False,
        "first",
        background=(0.2, 0.2, 0.3, 1.0),
        matting_config=VideoFrameMattingConfig(mat_images="on"),
    ) == "test.1.frame"


def test_matting_cache_signature_normalizes_mat_images_control() -> None:
    disabled = VideoFrameExtractor._matting_cache_signature(
        {
            "mat_images": False,
            "mat_type": "double_flat",
            "mat_resource_folder": "/missing-one",
        }
    )
    disabled_string = VideoFrameExtractor._matting_cache_signature(
        {
            "mat_images": "off",
            "mat_type": "float",
            "mat_resource_folder": "/missing-two",
        }
    )
    disabled_zero = VideoFrameExtractor._matting_cache_signature(
        {"mat_images": 0.0}
    )
    always = VideoFrameExtractor._matting_cache_signature({"mat_images": True})
    always_string = VideoFrameExtractor._matting_cache_signature({"mat_images": "on"})

    assert disabled == disabled_string == disabled_zero
    assert always == always_string
    assert disabled != always


def test_transition_cache_signature_includes_processing_version() -> None:
    payload = VideoFrameExtractor.processing_signature_payload(
        "test.mp4",
        1920,
        1080,
        False,
        matting_config=VideoFrameMattingConfig(mat_images="on"),
    )

    assert payload["processing_version"] == VIDEO_TRANSITION_FRAME_PROCESSING_VERSION


def test_cached_transition_frames_reject_old_processing_signature(tmp_path: Path) -> None:
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"video")
    extractor = VideoFrameExtractor(
        str(video_path),
        400,
        300,
        cache_dir=str(tmp_path / "cache"),
        matting_config=VideoFrameMattingConfig(mat_images="on", mat_type="double_bevel"),
    )
    first_path = Path(extractor.get_frame_path("first"))
    last_path = Path(extractor.get_frame_path("last"))
    first_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (10, 10), "red").save(first_path, format="JPEG")
    Image.new("RGB", (10, 10), "blue").save(last_path, format="JPEG")

    old_payload = VideoFrameExtractor.processing_signature_payload(
        str(video_path),
        400,
        300,
        False,
        matting_config=VideoFrameMattingConfig(mat_images="on", mat_type="double_bevel"),
        role="pair",
    )
    old_payload.pop("processing_version")
    old_signature = sha256(
        json.dumps(old_payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:24]
    Path(extractor.get_metadata_path()).write_text(
        json.dumps(
            {
                "version": 1,
                "matted": True,
                "content_rect": [10, 20, 300, 200],
                "processing_signature": old_signature,
            }
        ),
        encoding="utf-8",
    )

    assert not extractor.cached_transition_frames_valid()


def test_cached_transition_frames_reject_current_signature_without_geometry(
    tmp_path: Path,
) -> None:
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"video")
    extractor = VideoFrameExtractor(
        str(video_path),
        400,
        300,
        cache_dir=str(tmp_path / "cache"),
    )
    first_path = Path(extractor.get_frame_path("first"))
    last_path = Path(extractor.get_frame_path("last"))
    first_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (400, 300), "red").save(first_path, format="JPEG")
    Image.new("RGB", (400, 300), "blue").save(last_path, format="JPEG")
    Path(extractor.get_metadata_path()).write_text(
        json.dumps(
            {
                "version": VIDEO_TRANSITION_FRAME_PROCESSING_VERSION,
                "processing_signature": extractor._processing_signature(),
            }
        ),
        encoding="utf-8",
    )

    assert not extractor.cached_transition_frames_valid()


def test_extract_and_save_frames_regenerates_stale_legacy_sidecars(
    tmp_path: Path,
) -> None:
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"video")
    first_path = tmp_path / "video.1.frame"
    last_path = tmp_path / "video.2.frame"
    Image.new("RGB", (10, 10), "purple").save(first_path, format="JPEG")
    Image.new("RGB", (10, 10), "purple").save(last_path, format="JPEG")

    with (
        patch.object(
            VideoFrameExtractor,
            "_get_frame_as_image",
            return_value=Image.new("RGB", (50, 100), "red"),
        ) as mock_first,
        patch.object(
            VideoFrameExtractor,
            "_get_final_decoded_frame_as_image",
            return_value=Image.new("RGB", (50, 100), "blue"),
        ),
    ):
        result = VideoFrameExtractor.extract_and_save_frames(
            str(video_path),
            10.0,
            200,
            100,
            background=(0.0, 0.0, 0.0, 1.0),
            edge_config=VideoFrameEdgeConfig(edge_alpha=0.5),
        )

    metadata_path = Path(f"{first_path}.meta.json")
    assert result is True
    mock_first.assert_called_once_with(0)
    assert metadata_path.exists()
    assert "processing_signature" in metadata_path.read_text(encoding="utf-8")


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


def test_get_first_and_last_frames_loads_cached_generated_frames_without_reprocessing(
    tmp_path: Path,
) -> None:
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"video")
    extractor = VideoFrameExtractor(
        str(video_path),
        200,
        100,
        cache_dir=str(tmp_path / "cache"),
        edge_config=VideoFrameEdgeConfig(edge_alpha=0.5),
    )
    first_path = Path(extractor.get_frame_path("first"))
    last_path = Path(extractor.get_frame_path("last"))
    first_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (200, 100), "red").save(first_path, format="JPEG")
    Image.new("RGB", (200, 100), "blue").save(last_path, format="JPEG")
    extractor._write_transition_metadata(
        VideoTransitionFrameMetadata(
            frame_size=(200, 100),
            content_rect=(75, 0, 50, 100),
            backdrop=True,
        )
    )

    with patch.object(extractor, "_process_video_frame") as mock_process:
        frames = extractor.get_first_and_last_frames(
            10.0,
            50,
            100,
            extract_missing=False,
        )

    assert frames is not None
    assert frames[0].size == (200, 100)
    assert frames[1].size == (200, 100)
    assert extractor.last_transition_metadata is not None
    assert extractor.last_transition_metadata.content_rect == (75, 0, 50, 100)
    assert extractor.last_transition_metadata.backdrop_path == str(first_path)
    mock_process.assert_not_called()


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

def test_scale_frame_uses_configured_background_color() -> None:
    extractor = VideoFrameExtractor(
        "test.mp4",
        1920,
        1080,
        fit_display=False,
        background=(0.2, 0.2, 0.3, 1.0),
    )
    portrait_img = Image.new("RGB", (1080, 1920), "red")

    scaled_img = extractor._scale_frame(portrait_img)

    assert scaled_img.getpixel((10, 540)) == (51, 51, 76)
    assert scaled_img.getpixel((960, 540)) == (255, 0, 0)


def test_process_transition_frame_pair_edge_alpha_zero_uses_background() -> None:
    extractor = VideoFrameExtractor(
        "test.mp4",
        200,
        100,
        fit_display=False,
        background=(0.2, 0.2, 0.3, 1.0),
        edge_config=VideoFrameEdgeConfig(edge_alpha=0.0),
    )

    first, _last, metadata = extractor._process_transition_frame_pair(
        Image.new("RGB", (50, 100), "red"),
        Image.new("RGB", (50, 100), "blue"),
    )

    assert first.size == (200, 100)
    assert first.getpixel((10, 50)) == (51, 51, 76)
    assert first.getpixel((100, 50)) == (255, 0, 0)
    assert metadata.frame_size == (200, 100)
    assert metadata.coordinate_space == VIDEO_TRANSITION_FRAME_COORDINATE_SPACE
    assert metadata.content_rect == (75, 0, 50, 100)
    assert metadata.backdrop is False


def test_process_transition_frame_pair_solid_bars_records_foreground_rect() -> None:
    extractor = VideoFrameExtractor(
        "test.mp4",
        200,
        100,
        fit_display=False,
        background=(0.2, 0.2, 0.3, 1.0),
    )

    first, _last, metadata = extractor._process_transition_frame_pair(
        Image.new("RGB", (50, 100), "red"),
        Image.new("RGB", (50, 100), "blue"),
    )

    assert first.size == (200, 100)
    assert first.getpixel((10, 50)) == (51, 51, 76)
    assert first.getpixel((100, 50)) == (255, 0, 0)
    assert metadata.frame_size == (200, 100)
    assert metadata.coordinate_space == VIDEO_TRANSITION_FRAME_COORDINATE_SPACE
    assert metadata.content_rect == (75, 0, 50, 100)
    assert metadata.backdrop is False


def test_process_transition_frame_pair_edge_alpha_blends_image_edges() -> None:
    extractor = VideoFrameExtractor(
        "test.mp4",
        200,
        100,
        fit_display=False,
        background=(0.0, 0.0, 0.0, 1.0),
        edge_config=VideoFrameEdgeConfig(edge_alpha=0.5),
    )

    first, _last, metadata = extractor._process_transition_frame_pair(
        Image.new("RGB", (50, 100), "red"),
        Image.new("RGB", (50, 100), "blue"),
    )

    assert first.size == (200, 100)
    assert first.getpixel((10, 50)) in {(127, 0, 0), (128, 0, 0)}
    assert first.getpixel((100, 50)) == (255, 0, 0)
    assert metadata.frame_size == (200, 100)
    assert metadata.coordinate_space == VIDEO_TRANSITION_FRAME_COORDINATE_SPACE
    assert metadata.content_rect == (75, 0, 50, 100)
    assert metadata.backdrop is True


def test_process_transition_frame_pair_blur_edges_uses_image_fill() -> None:
    extractor = VideoFrameExtractor(
        "test.mp4",
        200,
        100,
        fit_display=False,
        background=(0.0, 0.0, 0.0, 1.0),
        edge_config=VideoFrameEdgeConfig(
            blur_edges=True,
            blur_amount=0,
            edge_alpha=0.0,
        ),
    )

    first, _last, metadata = extractor._process_transition_frame_pair(
        Image.new("RGB", (50, 100), "red"),
        Image.new("RGB", (50, 100), "blue"),
    )

    assert first.size == (200, 100)
    assert first.getpixel((10, 50)) == (255, 0, 0)
    assert metadata.frame_size == (200, 100)
    assert metadata.coordinate_space == VIDEO_TRANSITION_FRAME_COORDINATE_SPACE
    assert metadata.content_rect == (75, 0, 50, 100)
    assert metadata.backdrop is True


def test_process_transition_frame_pair_fit_display_records_full_frame_rect() -> None:
    extractor = VideoFrameExtractor(
        "test.mp4",
        200,
        100,
        fit_display=True,
        edge_config=VideoFrameEdgeConfig(edge_alpha=0.5),
    )

    first, _last, metadata = extractor._process_transition_frame_pair(
        Image.new("RGB", (50, 100), "red"),
        Image.new("RGB", (50, 100), "blue"),
    )

    assert first.size == (200, 100)
    assert metadata.frame_size == (200, 100)
    assert metadata.coordinate_space == VIDEO_TRANSITION_FRAME_COORDINATE_SPACE
    assert metadata.content_rect == (0, 0, 200, 100)
    assert metadata.backdrop is False


def test_scale_frame_defaults_invalid_background_to_black() -> None:
    extractor = VideoFrameExtractor(
        "test.mp4",
        1920,
        1080,
        fit_display=False,
        background=("bad", 0.2, 0.3),
    )
    portrait_img = Image.new("RGB", (1080, 1920), "red")

    scaled_img = extractor._scale_frame(portrait_img)

    assert scaled_img.getpixel((10, 540)) == (0, 0, 0)


def test_normalize_background_rgb_clamps_channels() -> None:
    assert VideoFrameExtractor._normalize_background_rgb((-1.0, 0.5, 2.0, 0.0)) == (
        0,
        128,
        255,
    )


@pytest.mark.parametrize("raw_value", [False, "false", "off", "0", "0.0", 0, 0.0])
def test_video_matting_control_disables_zero_and_false(raw_value: Any) -> None:
    assert VideoFrameExtractor._matting_control(raw_value) == (False, 0.01)


@pytest.mark.parametrize("raw_value", [True, "true", "on"])
def test_video_matting_control_always_mats_true_values(raw_value: Any) -> None:
    assert VideoFrameExtractor._matting_control(raw_value) == (True, -1.0)


def test_process_transition_frame_pair_applies_identical_matted_layout() -> None:
    extractor = VideoFrameExtractor(
        "test.mp4",
        400,
        300,
        fit_display=False,
        matting_config=VideoFrameMattingConfig(
            mat_images="on",
            mat_type="double_flat",
            outer_mat_color=(10, 20, 30),
            inner_mat_color=(40, 50, 60),
            outer_mat_border=40,
            inner_mat_border=20,
            outer_mat_use_texture=False,
            inner_mat_use_texture=False,
        ),
    )

    first, last, metadata = extractor._process_transition_frame_pair(
        Image.new("RGB", (160, 90), "red"),
        Image.new("RGB", (160, 90), "blue"),
    )

    assert metadata.matted is True
    assert metadata.content_rect is not None
    assert metadata.frame_size == (400, 300)
    assert metadata.coordinate_space == VIDEO_TRANSITION_FRAME_COORDINATE_SPACE
    assert first.size == (400, 300)
    assert last.size == (400, 300)
    assert metadata.layout_spec is not None
    assert metadata.layout_spec["content_rects"][0] == metadata.content_rect


def test_process_transition_frame_pair_uses_measured_bevel_content_rect() -> None:
    extractor = VideoFrameExtractor(
        "test.mp4",
        400,
        300,
        fit_display=False,
        matting_config=VideoFrameMattingConfig(
            mat_images="on",
            mat_type="double_bevel",
            outer_mat_color=(10, 20, 30),
            inner_mat_color=(40, 50, 60),
            outer_mat_border=40,
            inner_mat_border=20,
            outer_mat_use_texture=False,
            inner_mat_use_texture=False,
        ),
    )

    first, _last, metadata = extractor._process_transition_frame_pair(
        Image.new("RGB", (160, 90), "red"),
        Image.new("RGB", (160, 90), "blue"),
    )

    assert metadata.content_rect == _color_bbox(first, (255, 0, 0))
    assert metadata.frame_size == (400, 300)
    assert metadata.coordinate_space == VIDEO_TRANSITION_FRAME_COORDINATE_SPACE


def test_transition_metadata_round_trips_with_backdrop_path(tmp_path: Path) -> None:
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"video")
    extractor = VideoFrameExtractor(
        str(video_path),
        400,
        300,
        cache_dir=str(tmp_path / "cache"),
        matting_config=VideoFrameMattingConfig(mat_images="on"),
    )
    Path(extractor.get_metadata_path()).parent.mkdir(parents=True, exist_ok=True)
    metadata = VideoTransitionFrameMetadata(
        frame_size=(400, 300),
        matted=True,
        content_rect=(10, 20, 300, 200),
        layout_spec={"mat_type": "double_flat"},
    )

    extractor._write_transition_metadata(metadata)

    loaded = extractor._load_transition_metadata()
    assert loaded is not None
    assert loaded.matted is True
    assert loaded.frame_size == (400, 300)
    assert loaded.coordinate_space == VIDEO_TRANSITION_FRAME_COORDINATE_SPACE
    assert loaded.content_rect == (10, 20, 300, 200)
    assert loaded.with_backdrop_path("first.frame").backdrop_path == "first.frame"

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

def test_process_video_frame_fit_display_scales_to_display() -> None:
    """Test that fit_display frame processing produces display-sized pixels."""
    extractor = VideoFrameExtractor("test.mp4", 1920, 1080, fit_display=True)
    frame = Image.new("RGB", (800, 600))

    processed = extractor._process_video_frame(frame)

    assert processed is not frame
    assert processed.size == (1920, 1080)
