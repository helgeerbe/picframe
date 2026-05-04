import requests
from fastapi.testclient import TestClient
from picframe.api.app import create_app
from unittest.mock import MagicMock

mock_repo = MagicMock()
mock_publisher = MagicMock()
app = create_app(config_repository=mock_repo, event_publisher=mock_publisher)
client = TestClient(app)

payload = {
    "viewer": {"fps": 60},
    "model": {"pic_dir": "/new/path"}
}

response = client.put("/api/config", json=payload)
print(response.status_code)
print(response.json())
