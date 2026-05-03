import os
from pathlib import Path

import pytest
from PIL import Image

from picframe.core.models.media import MediaItem, MediaType
from picframe.core.services.image_processing import ImageProcessingService


@pytest.fixture
def temp_cache_dir(tmp_path: Path) -> str:
    cache_dir = tmp_path / "picframe_cache"
    return str(cache_dir)


@pytest.fixture
def sample_image(tmp_path: Path) -> str:
    img_path = tmp_path / "test_image.jpg"
    # Create a simple 100x100 red image
    img = Image.new("RGB", (100, 100), color="red")
    img.save(img_path)
    return str(img_path)


@pytest.fixture
def sample_media_item(sample_image: str) -> MediaItem:
    return MediaItem(
        filepath=sample_image,
        filename="test_image.jpg",
        directory_id=1,
        media_type=MediaType.IMAGE,
        file_size=1024,
        last_modified=1234567890.0,
    )


def test_ensure_cache_dir(temp_cache_dir: str) -> None:
    ImageProcessingService(cache_dir=temp_cache_dir)
    assert os.path.exists(temp_cache_dir)
    assert os.path.isdir(temp_cache_dir)


def test_process_image_fit(temp_cache_dir: str, sample_media_item: MediaItem) -> None:
    service = ImageProcessingService(cache_dir=temp_cache_dir)
    
    # Process image to fit within 50x50
    cached_path = service.process_image(
        sample_media_item, target_width=50, target_height=50, fit=True
    )
    
    assert cached_path is not None
    assert os.path.exists(cached_path)
    
    # Verify dimensions
    with Image.open(cached_path) as img:
        assert img.size == (50, 50)


def test_process_image_crop(temp_cache_dir: str, sample_media_item: MediaItem) -> None:
    service = ImageProcessingService(cache_dir=temp_cache_dir)
    
    # Process image to fill 50x25 (should crop)
    cached_path = service.process_image(
        sample_media_item, target_width=50, target_height=25, fit=False
    )
    
    assert cached_path is not None
    assert os.path.exists(cached_path)
    
    # Verify dimensions
    with Image.open(cached_path) as img:
        assert img.size == (50, 25)


def test_process_image_not_found(temp_cache_dir: str) -> None:
    service = ImageProcessingService(cache_dir=temp_cache_dir)
    
    bad_item = MediaItem(
        filepath="/path/to/nowhere.jpg",
        filename="nowhere.jpg",
        directory_id=1,
        media_type=MediaType.IMAGE,
        file_size=0,
        last_modified=0.0,
    )
    
    cached_path = service.process_image(
        bad_item, target_width=50, target_height=50
    )
    
    assert cached_path is None


def test_extract_metadata_async(temp_cache_dir: str, sample_media_item: MediaItem) -> None:
    service = ImageProcessingService(cache_dir=temp_cache_dir)
    
    class MockStrategy:
        def extract(self, filepath: str, directory_id: int) -> MediaItem:
            return sample_media_item
            
    strategy = MockStrategy()
    
    # Test without callback
    future = service.extract_metadata_async(
        filepath=sample_media_item.filepath,
        directory_id=1,
        strategy=strategy
    )
    
    result = future.result(timeout=2.0)
    assert result == sample_media_item
    
    # Test with callback
    callback_result = None
    def callback(item: MediaItem | None) -> None:
        nonlocal callback_result
        callback_result = item
        
    future = service.extract_metadata_async(
        filepath=sample_media_item.filepath,
        directory_id=1,
        strategy=strategy,
        callback=callback
    )
    
    future.result(timeout=2.0)
    assert callback_result == sample_media_item
    
    service.shutdown()


def test_clear_cache(temp_cache_dir: str, sample_media_item: MediaItem) -> None:
    service = ImageProcessingService(cache_dir=temp_cache_dir)
    
    # Create a cached image
    cached_path = service.process_image(
        sample_media_item, target_width=50, target_height=50
    )
    assert cached_path is not None
    assert os.path.exists(cached_path)
    
    # Clear cache
    service.clear_cache()
    
    # Verify cache is empty
    assert not os.path.exists(cached_path)
    assert len(os.listdir(temp_cache_dir)) == 0
