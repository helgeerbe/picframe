import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI

from picframe.api.app import create_app, system_error_websocket_message
from picframe.core.events.dto import SystemErrorEvent
from picframe.core.repositories.sqlite_config import SQLiteConfigRepository
from picframe.core.repositories.sqlite_media import SQLiteMediaRepository
from picframe.core.services.basic_auth import BasicAuthStore
from picframe.core.services.resource_paths import ResourcePaths


class ASGITestClient:
    """Small sync wrapper around httpx ASGITransport for integration tests."""

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


class FakeImageProcessingService:
    def __init__(self) -> None:
        self.clear_cache_calls = 0

    def clear_cache(self) -> None:
        self.clear_cache_calls += 1


def test_api_config_media_and_maintenance_with_temp_repositories(tmp_path: Path) -> None:
    pictures_dir = tmp_path / "Pictures"
    pictures_dir.mkdir()
    image_path = pictures_dir / "image.jpg"
    image_path.write_bytes(b"fake")

    config_repo = SQLiteConfigRepository(str(tmp_path / "config.db3"))
    media_repo = SQLiteMediaRepository(str(tmp_path / "media_cache.db3"))
    image_service = FakeImageProcessingService()
    try:
        config_repo.set_app_config("model.pic_dir", str(pictures_dir))
        media_repo.add_media_item(
            {
                "filepath": str(image_path),
                "filename": image_path.name,
                "directory_id": 1,
                "media_type": "image",
                "file_size": image_path.stat().st_size,
                "last_modified": image_path.stat().st_mtime,
                "tags": "family",
                "location": "Berlin",
            }
        )

        resource_paths = ResourcePaths.from_base_dir(tmp_path / "picframe-runtime")
        app = create_app(
            cors_allowed_origins=["*"],
            config_repository=config_repo,
            media_repository=media_repo,
            image_processing_service=image_service,
            html_dir=str(tmp_path / "missing-html"),
            resource_paths=resource_paths,
            auth_store=BasicAuthStore(resource_paths),
        )
        client = ASGITestClient(app)

        config_response = client.get("/api/config")
        assert config_response.status_code == 200
        assert config_response.json()["model"]["pic_dir"] == str(pictures_dir)

        count_response = client.post(
            "/api/media/selection-count",
            json={"tags_filter": "family", "location_filter": "Berlin"},
        )
        assert count_response.status_code == 200
        assert count_response.json()["selected_count"] == 1

        cache_response = client.post("/api/maintenance/clear-cache")
        assert cache_response.status_code == 200
        assert cache_response.json() == {"status": "cache cleared"}
        assert image_service.clear_cache_calls == 1
    finally:
        media_repo.close()
        config_repo.close()


def test_websocket_system_error_payload_shape() -> None:
    payload = json.loads(
        system_error_websocket_message(
            SystemErrorEvent(message="boom", component="integration")
        )
    )
    assert payload == {
        "type": "SystemErrorEvent",
        "message": "boom",
        "component": "integration",
        "sticky": False,
        "code": None,
    }
