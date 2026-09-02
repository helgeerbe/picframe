import json
from pathlib import Path

from picframe.api.models import AppConfig


def test_viewer_mat_images_preserves_boolean_disabled() -> None:
    config = AppConfig(viewer={"mat_images": False})

    assert config.viewer.mat_images is False


def test_viewer_mat_images_preserves_boolean_always() -> None:
    config = AppConfig(viewer={"mat_images": True})

    assert config.viewer.mat_images is True


def test_viewer_mat_images_accepts_threshold_and_legacy_strings() -> None:
    threshold = AppConfig(viewer={"mat_images": 0.2})
    disabled = AppConfig(viewer={"mat_images": "off"})
    always = AppConfig(viewer={"mat_images": "on"})

    assert threshold.viewer.mat_images == 0.2
    assert disabled.viewer.mat_images == "off"
    assert always.viewer.mat_images == "on"


def test_frontend_config_schema_allows_boolean_mat_images() -> None:
    schema_path = Path(__file__).parents[2] / "frontend" / "src" / "configSchema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    mat_images = schema["viewer"]["mat_images"]
    assert mat_images["type"] == "float"
    assert "boolean" in mat_images["acceptedTypes"]
    assert "float" in mat_images["acceptedTypes"]
