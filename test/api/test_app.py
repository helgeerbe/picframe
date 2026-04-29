import pytest
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
