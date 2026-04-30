import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from fastapi.testclient import TestClient
from picframe.api.app import create_app

@pytest.fixture
def client() -> TestClient:
    app = create_app()
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
    
    # Patch the Path object in app.py to point to our tmp_path
    with patch("picframe.api.app.Path") as mock_path:
        # Setup the mock to return our tmp_path when __file__ is resolved
        mock_file_path = MagicMock()
        mock_parent1 = MagicMock()
        mock_parent2 = MagicMock()
        
        mock_path.return_value = mock_file_path
        mock_file_path.parent = mock_parent1
        mock_parent1.parent = mock_parent2
        mock_parent2.__truediv__.return_value = html_dir
        
        app = create_app()
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

def test_spa_routing_without_html_dir(tmp_path: Path) -> None:
    # Patch the Path object to point to an empty directory
    with patch("picframe.api.app.Path") as mock_path:
        mock_file_path = MagicMock()
        mock_parent1 = MagicMock()
        mock_parent2 = MagicMock()
        
        mock_path.return_value = mock_file_path
        mock_file_path.parent = mock_parent1
        mock_parent1.parent = mock_parent2
        mock_parent2.__truediv__.return_value = tmp_path / "nonexistent"
        
        app = create_app()
        client = TestClient(app)
        
        # Test root route returns 404 since SPA is not mounted
        response = client.get("/")
        assert response.status_code == 404
