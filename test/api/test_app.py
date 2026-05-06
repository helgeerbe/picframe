from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from picframe.api.app import create_app


@pytest.fixture
def client() -> TestClient:
    app = create_app(cors_allowed_origins=["*"])
    return TestClient(app)

def test_health_check(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_cors_headers(client: TestClient) -> None:
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
    client = TestClient(app)
    
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

def test_api_get_config(client: TestClient) -> None:
    # Test without config repository
    response = client.get("/api/config")
    assert response.status_code == 200
    assert response.json() == {}

def test_api_get_config_with_repo() -> None:
    mock_repo = MagicMock()
    mock_repo.get_all_app_config.return_value = {
        "viewer.fps": 60,
        "model.pic_dir": "/tmp",
        "mqtt.use_mqtt": False,
        
        "peripherals.enable": True,
    }

    app = create_app(cors_allowed_origins=["*"], config_repository=mock_repo)
    client = TestClient(app)
    
    response = client.get("/api/config")
    assert response.status_code == 200
    data = response.json()
    assert data["viewer"]["fps"] == 60
    assert data["model"]["pic_dir"] == "/tmp"
    assert data["mqtt"]["use_mqtt"] is False
    
    assert data["peripherals"]["enable"] is True

def test_api_put_config() -> None:
    mock_repo = MagicMock()
    mock_publisher = MagicMock()
    
    # Setup mock to return existing config
    mock_repo.get_app_config.return_value = {"fps": 30, "blur_amount": 12}

    app = create_app(cors_allowed_origins=["*"], config_repository=mock_repo, event_publisher=mock_publisher)
    client = TestClient(app)
    
    payload = {
        "viewer": {"fps": 60},
        "model": {"pic_dir": "/new/path"}
    }
    
    response = client.put("/api/config", json=payload)
    assert response.status_code == 200
    assert response.json() == {"status": "success"}
    
    # Verify repository was updated
    assert mock_repo.set_app_config.call_count == 2
    
    # Verify event was published
    mock_publisher.publish.assert_called_once()
    event = mock_publisher.publish.call_args[0][0]
    assert event.command.name == "SET_CONFIG"
    assert event.payload == payload

def test_api_import_yaml() -> None:
    mock_repo = MagicMock()
    mock_publisher = MagicMock()
    
    app = create_app(cors_allowed_origins=["*"], config_repository=mock_repo, event_publisher=mock_publisher)
    client = TestClient(app)
    
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
    assert response.json() == {"status": "success", "message": "Legacy YAML configuration imported successfully"}
    
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

def test_api_import_yaml_example_file() -> None:
    mock_repo = MagicMock()
    mock_publisher = MagicMock()
    
    app = create_app(cors_allowed_origins=["*"], config_repository=mock_repo, event_publisher=mock_publisher)
    client = TestClient(app)
    
    example_yaml_path = Path(__file__).parent.parent.parent / "src" / "picframe" / "config" / "configuration_example.yaml"
    
    with open(example_yaml_path, "rb") as f:
        response = client.post(
            "/api/config/import-yaml",
            files={"file": ("configuration_example.yaml", f, "application/x-yaml")}
        )
        
    assert response.status_code == 200
    assert response.json() == {"status": "success", "message": "Legacy YAML configuration imported successfully"}
    
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
    client = TestClient(app)
    
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
    client = TestClient(app)
    
    # Test root route returns 404 since SPA is not mounted
    response = client.get("/")
    assert response.status_code == 404
