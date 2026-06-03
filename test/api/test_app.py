import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import FastAPI

from picframe.api.app import create_app


@pytest.fixture
def client() -> "ASGITestClient":
    app = create_app(cors_allowed_origins=["*"])
    return ASGITestClient(app)


class ASGITestClient:
    """Small sync wrapper around httpx ASGITransport for local API tests.

    Starlette's TestClient currently hangs in this environment when running on
    Python 3.14, while httpx's ASGITransport exercises the same ASGI app without
    the thread-portal deadlock.
    """

    def __init__(self, app: FastAPI) -> None:
        self._app = app

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        async def _request() -> httpx.Response:
            transport = httpx.ASGITransport(app=self._app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://testserver",
            ) as async_client:
                return await async_client.request(method, url, **kwargs)

        return asyncio.run(_request())

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("PUT", url, **kwargs)

    def options(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("OPTIONS", url, **kwargs)


def test_health_check(client: ASGITestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_cors_headers(client: ASGITestClient) -> None:
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:8080",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    # FastAPI's CORSMiddleware echoes back the Origin if allow_origins=["*"]
    # and allow_credentials=True are used together, or it just echoes it back
    # when a specific origin is requested.
    assert response.headers["access-control-allow-origin"] == "http://localhost:8080"

def test_spa_routing_with_html_dir(tmp_path: Path) -> None:
    # Create a mock html directory structure
    html_dir = tmp_path / "html"
    html_dir.mkdir()
    (html_dir / "index.html").write_text("<h1>Index</h1>")
    
    assets_dir = html_dir / "assets"
    assets_dir.mkdir()
    (assets_dir / "app.js").write_text("console.log('app');")

    app = create_app(cors_allowed_origins=["*"], html_dir=str(html_dir))
    client = ASGITestClient(app)
    
    # Test root route returns index.html
    response = client.get("/")
    assert response.status_code == 200
    assert response.text == "<h1>Index</h1>"
    
    # Test non-existent route falls back to index.html
    response = client.get("/some/vue/route")
    assert response.status_code == 200
    assert response.text == "<h1>Index</h1>"
    
    # Test assets route
    response = client.get("/assets/app.js")
    assert response.status_code == 200
    assert response.text == "console.log('app');"

def test_api_get_config(client: ASGITestClient) -> None:
    # Test without config repository
    response = client.get("/api/config")
    assert response.status_code == 200
    assert response.json() == {}

def test_api_get_config_with_repo() -> None:
    mock_repo = MagicMock()
    mock_repo.get_all_app_config.return_value = {
        "viewer.fps": 60,
        "model.pic_dir": "/tmp",
        "model.date_from": "2024-01-01",
        "model.date_to": "2024-02-01",
        "mqtt.use_mqtt": False,
        
        "peripherals.enable": True,
    }

    app = create_app(cors_allowed_origins=["*"], config_repository=mock_repo)
    client = ASGITestClient(app)
    
    response = client.get("/api/config")
    assert response.status_code == 200
    data = response.json()
    assert data["viewer"]["fps"] == 60
    assert data["model"]["pic_dir"] == "/tmp"
    assert data["model"]["date_from"] == "2024-01-01"
    assert data["model"]["date_to"] == "2024-02-01"
    assert data["mqtt"]["use_mqtt"] is False
    
    assert data["peripherals"]["enable"] is True

def test_api_put_config() -> None:
    mock_repo = MagicMock()
    mock_publisher = MagicMock()
    
    # Setup mock to return existing config
    mock_repo.get_app_config.return_value = {"fps": 30, "blur_amount": 12}

    app = create_app(
        cors_allowed_origins=["*"],
        config_repository=mock_repo,
        event_publisher=mock_publisher,
    )
    client = ASGITestClient(app)
    
    payload = {
        "viewer": {"fps": 60},
        "model": {"pic_dir": "/new/path", "date_from": "2024-01-01"}
    }
    
    response = client.put("/api/config", json=payload)
    assert response.status_code == 200
    assert response.json() == {"status": "success"}
    
    # Verify repository was updated
    assert mock_repo.set_app_config.call_count == 3
    mock_repo.set_app_config.assert_any_call("model.date_from", "2024-01-01")
    
    # Verify event was published
    mock_publisher.publish.assert_called_once()
    event = mock_publisher.publish.call_args[0][0]
    assert event.command.name == "SET_CONFIG"
    assert event.payload == payload


def test_api_media_filter_options() -> None:
    mock_config_repo = MagicMock()
    mock_config_repo.get_app_config.return_value = "/pictures"
    mock_media_repo = MagicMock()
    mock_media_repo.get_filter_options.return_value = {
        "subdirectories": ["holiday"],
        "locations": ["Berlin"],
        "tags": ["family"],
        "sort_columns": [{"key": "fname", "label": "File name"}],
    }

    app = create_app(
        cors_allowed_origins=["*"],
        config_repository=mock_config_repo,
        media_repository=mock_media_repo,
    )
    client = ASGITestClient(app)

    response = client.get("/api/media/filter-options")

    assert response.status_code == 200
    assert response.json()["subdirectories"] == ["holiday"]
    mock_media_repo.get_filter_options.assert_called_once_with("/pictures")


def test_api_media_selection_count_uses_config_pic_dir() -> None:
    mock_config_repo = MagicMock()
    mock_config_repo.get_app_config.return_value = "/pictures"
    mock_media_repo = MagicMock()
    mock_media_repo.count_media.return_value = {
        "selected_count": 8,
        "total_count": 10000,
        "scope": "subdirectory",
        "scope_label": "holiday",
    }

    app = create_app(
        cors_allowed_origins=["*"],
        config_repository=mock_config_repo,
        media_repository=mock_media_repo,
    )
    client = ASGITestClient(app)

    response = client.post(
        "/api/media/selection-count",
        json={
            "subdirectory": "holiday",
            "date_from": "2024-01-01",
            "date_to": "2024-02-01",
            "location_filter": "Berlin OR Hamburg",
            "tags_filter": "family AND beach",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "selected_count": 8,
        "total_count": 10000,
        "scope": "subdirectory",
        "scope_label": "holiday",
    }
    criteria = mock_media_repo.count_media.call_args.args[0]
    assert criteria.pic_dir == "/pictures"
    assert criteria.subdirectory == "holiday"
    assert criteria.date_from == "2024-01-01"
    assert criteria.date_to == "2024-02-01"
    assert criteria.location_filter == "Berlin OR Hamburg"
    assert criteria.tags_filter == "family AND beach"
    assert criteria.shuffle is False
    assert criteria.recent_n == 0


def test_api_media_selection_count_without_media_repo() -> None:
    app = create_app(cors_allowed_origins=["*"])
    client = ASGITestClient(app)

    response = client.post(
        "/api/media/selection-count",
        json={"subdirectory": "holiday"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "selected_count": 0,
        "total_count": 0,
        "scope": "subdirectory",
        "scope_label": "holiday",
    }


def test_api_clear_cache_calls_image_processing_service() -> None:
    mock_image_processing_service = MagicMock()
    app = create_app(
        cors_allowed_origins=["*"],
        image_processing_service=mock_image_processing_service,
    )
    client = ASGITestClient(app)

    response = client.post("/api/maintenance/clear-cache")

    assert response.status_code == 200
    assert response.json() == {"status": "cache cleared"}
    mock_image_processing_service.clear_cache.assert_called_once_with()


def test_api_import_yaml() -> None:
    mock_repo = MagicMock()
    mock_publisher = MagicMock()
    
    app = create_app(
        cors_allowed_origins=["*"],
        config_repository=mock_repo,
        event_publisher=mock_publisher,
    )
    client = ASGITestClient(app)
    
    yaml_content = """
viewer:
  fps: 45
  blur_amount: 15
  unknown_field: "should be ignored"
model:
  pic_dir: "/new/yaml/path"
"""
    
    response = client.post(
        "/api/config/import-yaml",
        files={"file": ("config.yaml", yaml_content, "application/x-yaml")}
    )
    
    assert response.status_code == 200
    assert response.json() == {
        "status": "success",
        "message": "Legacy YAML configuration imported successfully",
    }
    
    # Verify repository was updated
    assert mock_repo.set_app_config.call_count > 0
    
    # Verify event was published
    mock_publisher.publish.assert_called_once()
    event = mock_publisher.publish.call_args[0][0]
    assert event.command.name == "SET_CONFIG"
    assert event.payload["viewer"]["fps"] == 45
    assert event.payload["viewer"]["blur_amount"] == 15
    assert event.payload["model"]["pic_dir"] == "/new/yaml/path"
    assert "unknown_field" not in event.payload["viewer"]


def test_api_import_yaml_maps_legacy_show_text() -> None:
    mock_repo = MagicMock()
    mock_publisher = MagicMock()

    app = create_app(
        cors_allowed_origins=["*"],
        config_repository=mock_repo,
        event_publisher=mock_publisher,
    )
    client = ASGITestClient(app)

    yaml_content = """
viewer:
  show_text: "name location"
"""

    response = client.post(
        "/api/config/import-yaml",
        files={"file": ("config.yaml", yaml_content, "application/x-yaml")},
    )

    assert response.status_code == 200
    event = mock_publisher.publish.call_args[0][0]
    assert event.payload["viewer"]["text_overlay_format"] == "name location"
    assert event.payload["viewer"]["show_text_enabled"] is True
    assert "show_text" not in event.payload["viewer"]


def test_api_import_yaml_maps_empty_legacy_show_text_to_disabled() -> None:
    mock_repo = MagicMock()
    mock_publisher = MagicMock()

    app = create_app(
        cors_allowed_origins=["*"],
        config_repository=mock_repo,
        event_publisher=mock_publisher,
    )
    client = ASGITestClient(app)

    yaml_content = """
viewer:
  show_text: "  "
"""

    response = client.post(
        "/api/config/import-yaml",
        files={"file": ("config.yaml", yaml_content, "application/x-yaml")},
    )

    assert response.status_code == 200
    event = mock_publisher.publish.call_args[0][0]
    assert event.payload["viewer"]["text_overlay_format"] == ""
    assert event.payload["viewer"]["show_text_enabled"] is False


def test_api_import_yaml_preserves_explicit_next_gen_text_keys() -> None:
    mock_repo = MagicMock()
    mock_publisher = MagicMock()

    app = create_app(
        cors_allowed_origins=["*"],
        config_repository=mock_repo,
        event_publisher=mock_publisher,
    )
    client = ASGITestClient(app)

    yaml_content = """
viewer:
  show_text: "name location"
  text_overlay_format: "title caption"
  show_text_enabled: false
"""

    response = client.post(
        "/api/config/import-yaml",
        files={"file": ("config.yaml", yaml_content, "application/x-yaml")},
    )

    assert response.status_code == 200
    event = mock_publisher.publish.call_args[0][0]
    assert event.payload["viewer"]["text_overlay_format"] == "title caption"
    assert event.payload["viewer"]["show_text_enabled"] is False
    assert "show_text" not in event.payload["viewer"]


def test_api_import_yaml_imports_mqtt_port_and_ignores_startup_only_http_keys() -> None:
    mock_repo = MagicMock()
    mock_publisher = MagicMock()

    app = create_app(
        cors_allowed_origins=["*"],
        config_repository=mock_repo,
        event_publisher=mock_publisher,
    )
    client = ASGITestClient(app)

    yaml_content = """
mqtt:
  port: 8883
http:
  use_http: true
  path: "/tmp/picframe-html"
  port: 9001
  password: null
"""

    response = client.post(
        "/api/config/import-yaml",
        files={"file": ("config.yaml", yaml_content, "application/x-yaml")},
    )

    assert response.status_code == 200
    event = mock_publisher.publish.call_args[0][0]
    assert event.payload["mqtt"]["port"] == 8883
    assert event.payload["http"]["password"] == ""
    assert "use_http" not in event.payload["http"]
    assert "path" not in event.payload["http"]
    assert "port" not in event.payload["http"]


def test_api_import_yaml_example_file() -> None:
    mock_repo = MagicMock()
    mock_publisher = MagicMock()
    
    app = create_app(
        cors_allowed_origins=["*"],
        config_repository=mock_repo,
        event_publisher=mock_publisher,
    )
    client = ASGITestClient(app)
    
    example_yaml_path = (
        Path(__file__).parent.parent.parent
        / "src"
        / "picframe"
        / "config"
        / "configuration_example.yaml"
    )
    
    with open(example_yaml_path, "rb") as f:
        response = client.post(
            "/api/config/import-yaml",
            files={"file": ("configuration_example.yaml", f, "application/x-yaml")}
        )
        
    assert response.status_code == 200
    assert response.json() == {
        "status": "success",
        "message": "Legacy YAML configuration imported successfully",
    }
    
    # Verify repository was updated
    assert mock_repo.set_app_config.call_count > 0
    
    # Verify event was published
    mock_publisher.publish.assert_called_once()
    event = mock_publisher.publish.call_args[0][0]
    assert event.command.name == "SET_CONFIG"
    
    # Verify some specific fields from the example file
    assert event.payload["viewer"]["blur_amount"] == 12
    assert event.payload["viewer"]["display_w"] is None
    assert event.payload["viewer"]["display_h"] is None
    assert event.payload["model"]["pic_dir"] == "~/Pictures"
    assert event.payload["http"]["password"] == ""

def test_api_import_yaml_invalid_format() -> None:
    mock_repo = MagicMock()
    app = create_app(cors_allowed_origins=["*"], config_repository=mock_repo)
    client = ASGITestClient(app)
    
    yaml_content = """
- just a list
- not a dict
"""
    
    response = client.post(
        "/api/config/import-yaml",
        files={"file": ("config.yaml", yaml_content, "application/x-yaml")}
    )
    
    assert response.status_code == 500
    assert "Error importing configuration" in response.json()["detail"]

def test_spa_routing_without_html_dir(tmp_path: Path) -> None:
    app = create_app(cors_allowed_origins=["*"], html_dir=str(tmp_path / "nonexistent"))
    client = ASGITestClient(app)
    
    # Test root route returns 404 since SPA is not mounted
    response = client.get("/")
    assert response.status_code == 404
