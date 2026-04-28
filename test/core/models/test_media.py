"""
Unit tests for the MediaItem domain model.

This module verifies the initialization and serialization of the MediaItem
dataclass.
"""

from picframe.core.models.media import MediaItem, MediaType


def test_media_item_initialization() -> None:
    """Test that a MediaItem can be initialized with required fields."""
    item = MediaItem(
        filepath="/path/to/image.jpg",
        filename="image.jpg",
        directory_id=1,
        media_type=MediaType.IMAGE,
        file_size=1024,
        last_modified=1678886400.0,
    )

    assert item.filepath == "/path/to/image.jpg"
    assert item.filename == "image.jpg"
    assert item.directory_id == 1
    assert item.media_type == MediaType.IMAGE
    assert item.file_size == 1024
    assert item.last_modified == 1678886400.0
    assert item.width is None
    assert item.height is None
    assert item.orientation == 1
    assert item.exif_datetime is None
    assert item.f_number is None
    assert item.exposure_time is None
    assert item.iso is None
    assert item.focal_length is None
    assert item.make is None
    assert item.model is None
    assert item.lens is None
    assert item.rating is None
    assert item.latitude is None
    assert item.longitude is None
    assert item.title is None
    assert item.caption is None
    assert item.tags is None
    assert item.is_portrait is None
    assert item.location is None
    assert item.duration is None
    assert item.id is None
    assert item.is_deleted is False


def test_media_item_to_dict() -> None:
    """Test converting a MediaItem to a dictionary for database insertion."""
    item = MediaItem(
        filepath="/path/to/video.mp4",
        filename="video.mp4",
        directory_id=2,
        media_type=MediaType.VIDEO,
        file_size=2048,
        last_modified=1678886400.0,
        width=1920,
        height=1080,
        f_number=2.8,
        exposure_time="1/60",
        iso=400,
        focal_length="50mm",
        make="Canon",
        model="EOS 5D",
        lens="EF50mm f/1.8",
        rating=5,
        latitude=40.7128,
        longitude=-74.0060,
        title="New York",
        caption="City skyline",
        tags="city,skyline",
        is_portrait=False,
        location="New York, USA",
        duration=60.5,
        is_deleted=True,
    )

    data = item.to_dict()

    assert data["filepath"] == "/path/to/video.mp4"
    assert data["filename"] == "video.mp4"
    assert data["directory_id"] == 2
    assert data["media_type"] == "video"
    assert data["file_size"] == 2048
    assert data["last_modified"] == 1678886400.0
    assert data["width"] == 1920
    assert data["height"] == 1080
    assert data["orientation"] == 1
    assert data["exif_datetime"] is None
    assert data["f_number"] == 2.8
    assert data["exposure_time"] == "1/60"
    assert data["iso"] == 400
    assert data["focal_length"] == "50mm"
    assert data["make"] == "Canon"
    assert data["model"] == "EOS 5D"
    assert data["lens"] == "EF50mm f/1.8"
    assert data["rating"] == 5
    assert data["latitude"] == 40.7128
    assert data["longitude"] == -74.0060
    assert data["title"] == "New York"
    assert data["caption"] == "City skyline"
    assert data["tags"] == "city,skyline"
    assert data["is_portrait"] == 0
    assert data["location"] == "New York, USA"
    assert data["duration"] == 60.5
    assert data["is_deleted"] == 1  # Boolean converted to int
