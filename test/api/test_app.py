import asyncio
import base64
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI

from picframe.api.app import create_app, media_event_to_response_dto, _send_websocket_text
from picframe.core.events.dto import Command
from picframe.core.services.basic_auth import AUTH_COOKIE_NAME, BasicAuthStore
from picframe.core.services.resource_paths import ResourcePaths


@pytest.fixture
def client() -> "ASGITestClient":
    app = create_app(cors_allowed_origins=["*"])
    return ASGITestClient(app)


@pytest.fixture(autouse=True)
def isolate_default_resource_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "default-home"
    home.mkdir()
    monkeypatch.setattr("picframe.api.app._path_picker_root", lambda: home.resolve())


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


def basic_auth(username: str = "admin", password: str = "secret") -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def test_health_check(client: ASGITestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_documents_rest_response_models(client: ASGITestClient) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    paths = schema["paths"]

    expected_refs = {
        ("/health", "get"): "HealthResponse",
        ("/api/system/reboot", "post"): "StatusResponse",
        ("/api/system/shutdown", "post"): "StatusResponse",
        ("/api/system/locales", "get"): "LocaleOptionsResponse",
        ("/api/maintenance/purge-db", "post"): "StatusResponse",
        ("/api/maintenance/clear-cache", "post"): "StatusMessageResponse",
        ("/api/filesystem/browse", "get"): "FilesystemBrowseResponse",
        ("/api/filesystem/validate", "post"): "FilesystemValidateResponse",
        ("/api/media/filter-options", "get"): "MediaFilterOptionsResponse",
        ("/api/media/location-options", "get"): "MediaLocationOptionsResponse",
        ("/api/media/selection-count", "post"): "MediaSelectionCountResponse",
        ("/api/hardware-inputs", "get"): "HardwareInputsConfig",
        ("/api/hardware-inputs", "put"): "HardwareInputsUpdateResponse",
        ("/api/auth/config", "get"): "BasicAuthConfigResponse",
        ("/api/auth/config", "put"): "BasicAuthConfigResponse",
        ("/api/config/import-yaml", "post"): "StatusMessageResponse",
        ("/api/config", "put"): "StatusMessageResponse",
    }
    for (path, method), model_name in expected_refs.items():
        operation = paths[path][method]
        assert operation["summary"]
        response_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
        assert response_schema["$ref"] == f"#/components/schemas/{model_name}"

    config_response_schema = (
        paths["/api/config"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    )
    assert {"$ref": "#/components/schemas/AppConfig"} in config_response_schema["anyOf"]
    assert {"$ref": "#/components/schemas/EmptyConfigResponse"} in config_response_schema["anyOf"]


def test_openapi_documents_expected_error_responses(client: ASGITestClient) -> None:
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]

    browse_responses = paths["/api/filesystem/browse"]["get"]["responses"]
    for status_code in ("400", "403", "404", "422"):
        assert (
            browse_responses[status_code]["content"]["application/json"]["schema"]["$ref"]
            == "#/components/schemas/APIErrorResponse"
        )

    media_responses = paths["/media"]["get"]["responses"]
    assert (
        media_responses["403"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/APIErrorResponse"
    )
    assert (
        media_responses["404"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/APIErrorResponse"
    )

    import_responses = paths["/api/config/import-yaml"]["post"]["responses"]
    assert "500" in import_responses
    assert (
        import_responses["500"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/APIErrorResponse"
    )


def test_openapi_documents_websocket_contract(client: ASGITestClient) -> None:
    schema = client.get("/openapi.json").json()

    assert "/ws/state" not in schema["paths"]
    assert "/ws/logs" not in schema["paths"]
    assert "/ws/state" in schema["info"]["description"]
    websocket_contract = schema["x-websocket-contracts"]["/ws/state"]
    assert websocket_contract["incoming"] == [
        {"$ref": "#/components/schemas/WebSocketCommandMessage"}
    ]
    assert websocket_contract["outgoing"] == [
        {"$ref": "#/components/schemas/MediaChangedWebSocketMessage"},
        {"$ref": "#/components/schemas/StateWebSocketMessage"},
        {"$ref": "#/components/schemas/SystemErrorWebSocketMessage"},
    ]

    components = schema["components"]["schemas"]
    assert "WebSocketCommandMessage" in components
    assert "MediaChangedWebSocketMessage" in components
    assert "StateWebSocketMessage" in components
    assert "SystemErrorWebSocketMessage" in components
    assert "LogEventMessage" in components
    assert "LogSnapshotMessage" in components
    assert schema["x-websocket-contracts"]["/ws/logs"]["outgoing"] == [
        {"$ref": "#/components/schemas/LogSnapshotMessage"},
        {"$ref": "#/components/schemas/LogEventMessage"},
    ]


def test_websocket_send_helper_treats_closed_socket_as_disconnect() -> None:
    websocket = MagicMock()
    websocket.send_text = AsyncMock(
        side_effect=RuntimeError(
            "Unexpected ASGI message 'websocket.send', after sending 'websocket.close'"
        )
    )

    assert asyncio.run(_send_websocket_text(websocket, '{"type":"StateEvent"}')) is False


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


def test_basic_auth_protects_settings_logs_and_admin_routes(tmp_path: Path) -> None:
    base_dir = tmp_path / "picframe"
    html_dir = base_dir / "html"
    html_dir.mkdir(parents=True)
    (html_dir / "index.html").write_text("<h1>Index</h1>")
    resource_paths = ResourcePaths.from_base_dir(base_dir)
    auth_store = BasicAuthStore(resource_paths)

    app = create_app(
        cors_allowed_origins=["*"],
        html_dir=str(html_dir),
        resource_paths=resource_paths,
        auth_store=auth_store,
    )
    client = ASGITestClient(app)

    assert client.get("/settings").status_code == 200
    response = client.put(
        "/api/auth/config",
        json={"scope": "settings", "username": "admin", "password": "secret"},
    )
    assert response.status_code == 200
    assert response.json()["enabled"] is True
    assert response.json()["scope"] == "settings"
    assert response.json()["password_set"] is True
    assert response.json()["password"] == "secret"

    assert client.get("/settings").status_code == 401
    assert client.get("/logs").status_code == 401
    assert client.get("/api/config").status_code == 401
    assert client.post("/api/system/reboot").status_code == 401

    assert client.get("/").status_code == 200
    assert client.get("/api/workflow-config").status_code == 200
    assert client.get("/api/media/filter-options").status_code == 200

    assert client.get("/settings", headers=basic_auth()).status_code == 200
    assert client.get("/logs", headers=basic_auth()).status_code == 200
    assert client.get("/api/config", headers=basic_auth()).status_code == 200
    response = client.get("/api/auth/config", headers=basic_auth())
    assert response.status_code == 200
    assert response.json()["password"] == "secret"

    response = client.put(
        "/api/auth/config",
        headers=basic_auth(),
        json={"scope": "none", "username": "admin", "password": ""},
    )
    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert response.json()["scope"] == "none"
    assert "password" not in response.json()
    assert client.get("/settings").status_code == 200
    response = client.get("/api/auth/config")
    assert response.status_code == 200
    assert "password" not in response.json()


def test_basic_auth_sets_cookie_for_protected_routes(tmp_path: Path) -> None:
    base_dir = tmp_path / "picframe"
    html_dir = base_dir / "html"
    html_dir.mkdir(parents=True)
    (html_dir / "index.html").write_text("<h1>Index</h1>")
    resource_paths = ResourcePaths.from_base_dir(base_dir)
    auth_store = BasicAuthStore(resource_paths)

    app = create_app(
        cors_allowed_origins=["*"],
        html_dir=str(html_dir),
        resource_paths=resource_paths,
        auth_store=auth_store,
    )
    client = ASGITestClient(app)

    response = client.put(
        "/api/auth/config",
        json={"scope": "settings", "username": "admin", "password": "secret"},
    )
    assert response.status_code == 200

    response = client.get("/logs", headers=basic_auth())
    assert response.status_code == 200
    token = response.cookies.get(AUTH_COOKIE_NAME)
    assert token

    cookie_header = {"Cookie": f"{AUTH_COOKIE_NAME}={token}"}
    assert client.get("/logs", headers=cookie_header).status_code == 200
    assert client.get("/api/config", headers=cookie_header).status_code == 200
    assert client.get("/logs", headers={"Cookie": f"{AUTH_COOKIE_NAME}=bad"}).status_code == 401


def test_basic_auth_can_protect_complete_site(tmp_path: Path) -> None:
    base_dir = tmp_path / "picframe"
    html_dir = base_dir / "html"
    assets_dir = html_dir / "assets"
    assets_dir.mkdir(parents=True)
    (html_dir / "index.html").write_text("<h1>Index</h1>")
    (assets_dir / "app.js").write_text("console.log('app');")
    resource_paths = ResourcePaths.from_base_dir(base_dir)
    auth_store = BasicAuthStore(resource_paths)

    app = create_app(
        cors_allowed_origins=["*"],
        html_dir=str(html_dir),
        resource_paths=resource_paths,
        auth_store=auth_store,
    )
    client = ASGITestClient(app)

    response = client.put(
        "/api/auth/config",
        json={"scope": "site", "username": "admin", "password": "secret"},
    )
    assert response.status_code == 200
    assert response.json()["enabled"] is True
    assert response.json()["scope"] == "site"

    assert client.get("/").status_code == 401
    assert client.get("/assets/app.js").status_code == 401
    assert client.get("/api/workflow-config").status_code == 401
    assert client.get("/api/media/filter-options").status_code == 401
    assert client.get("/api/auth/config").status_code == 401

    assert client.get("/", headers=basic_auth()).status_code == 200
    assert client.get("/assets/app.js", headers=basic_auth()).status_code == 200
    assert client.get("/api/workflow-config", headers=basic_auth()).status_code == 200
    assert client.get("/api/media/filter-options", headers=basic_auth()).status_code == 200
    assert client.get("/api/auth/config", headers=basic_auth()).status_code == 200


def test_basic_auth_scope_matrix_for_http_routes(tmp_path: Path) -> None:
    base_dir = tmp_path / "picframe"
    html_dir = base_dir / "html"
    assets_dir = html_dir / "assets"
    assets_dir.mkdir(parents=True)
    (html_dir / "index.html").write_text("<h1>Index</h1>")
    (assets_dir / "app.js").write_text("console.log('app');")
    media_path = tmp_path / "photo.jpg"
    media_path.write_text("jpg")
    resource_paths = ResourcePaths.from_base_dir(base_dir)
    auth_store = BasicAuthStore(resource_paths)

    app = create_app(
        cors_allowed_origins=["*"],
        html_dir=str(html_dir),
        resource_paths=resource_paths,
        auth_store=auth_store,
    )
    client = ASGITestClient(app)

    response = client.put(
        "/api/auth/config",
        json={"scope": "settings", "username": "admin", "password": "secret"},
    )
    assert response.status_code == 200

    settings_protected = [
        ("GET", "/api/auth/config", {}),
        ("GET", "/api/config", {}),
        ("PUT", "/api/config", {"json": {}}),
        ("POST", "/api/config/import-yaml", {}),
        ("GET", "/api/filesystem/browse", {}),
        ("POST", "/api/filesystem/validate", {"json": {}}),
        ("GET", "/api/hardware-inputs", {}),
        ("PUT", "/api/hardware-inputs", {"json": {}}),
        ("POST", "/api/maintenance/purge-db", {}),
        ("POST", "/api/maintenance/clear-cache", {}),
        ("POST", "/api/system/reboot", {}),
        ("POST", "/api/system/shutdown", {}),
        ("GET", "/logs", {}),
        ("GET", "/settings", {}),
    ]
    for method, url, kwargs in settings_protected:
        assert client.request(method, url, **kwargs).status_code == 401, url

    settings_public = [
        ("GET", "/", {}),
        ("GET", "/assets/app.js", {}),
        ("GET", "/health", {}),
        ("GET", "/openapi.json", {}),
        ("GET", "/api/system/locales", {}),
        ("GET", "/api/workflow-config", {}),
        ("PUT", "/api/workflow-config", {"json": {}}),
        ("GET", "/api/media/filter-options", {}),
        ("GET", "/api/media/location-options?q=ber", {}),
        ("POST", "/api/media/selection-count", {"json": {}}),
        ("GET", f"/media?path={media_path}", {}),
    ]
    for method, url, kwargs in settings_public:
        assert client.request(method, url, **kwargs).status_code != 401, url

    response = client.put(
        "/api/auth/config",
        headers=basic_auth(),
        json={"scope": "site", "username": "admin", "password": ""},
    )
    assert response.status_code == 200

    site_protected = [
        *settings_protected,
        *settings_public,
        ("GET", "/docs", {}),
    ]
    for method, url, kwargs in site_protected:
        assert client.request(method, url, **kwargs).status_code == 401, url

    assert client.options("/api/config").status_code != 401


def test_basic_auth_legacy_enabled_request_maps_to_settings_scope(tmp_path: Path) -> None:
    resource_paths = ResourcePaths.from_base_dir(tmp_path / "picframe")
    app = create_app(
        cors_allowed_origins=["*"],
        resource_paths=resource_paths,
        auth_store=BasicAuthStore(resource_paths),
    )
    client = ASGITestClient(app)

    response = client.put(
        "/api/auth/config",
        json={"enabled": True, "username": "admin", "password": "secret"},
    )

    assert response.status_code == 200
    assert response.json()["scope"] == "settings"


def test_basic_auth_requires_password_when_enabled(tmp_path: Path) -> None:
    resource_paths = ResourcePaths.from_base_dir(tmp_path / "picframe")
    app = create_app(
        cors_allowed_origins=["*"],
        resource_paths=resource_paths,
        auth_store=BasicAuthStore(resource_paths),
    )
    client = ASGITestClient(app)

    response = client.put(
        "/api/auth/config",
        json={"scope": "settings", "username": "admin", "password": ""},
    )

    assert response.status_code == 400
    assert "Password is required" in response.json()["detail"]


def test_api_filesystem_browse_lists_home_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / "Pictures").mkdir()
    (home / "notes.txt").write_text("hello")
    monkeypatch.setattr("picframe.api.app._path_picker_root", lambda: home.resolve())

    app = create_app(cors_allowed_origins=["*"])
    client = ASGITestClient(app)

    response = client.get("/api/filesystem/browse")

    assert response.status_code == 200
    data = response.json()
    assert data["root"] == "~"
    assert data["path"] == "~"
    assert data["parent"] is None
    assert [entry["name"] for entry in data["entries"]] == ["Pictures", "notes.txt"]


def test_api_filesystem_browse_filters_files_by_extension(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / "nested").mkdir()
    (home / "photo.jpg").write_text("jpg")
    (home / "movie.mov").write_text("mov")
    monkeypatch.setattr("picframe.api.app._path_picker_root", lambda: home.resolve())

    app = create_app(cors_allowed_origins=["*"])
    client = ASGITestClient(app)

    response = client.get("/api/filesystem/browse?kind=file&extensions=.jpg")

    assert response.status_code == 200
    assert [entry["name"] for entry in response.json()["entries"]] == ["nested", "photo.jpg"]


def test_api_filesystem_browse_rejects_traversal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("picframe.api.app._path_picker_root", lambda: home.resolve())

    app = create_app(cors_allowed_origins=["*"])
    client = ASGITestClient(app)

    response = client.get("/api/filesystem/browse?path=../")

    assert response.status_code == 403


def test_api_filesystem_validate_rejects_symlink_escape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    outside = tmp_path / "outside"
    home.mkdir()
    outside.mkdir()
    (home / "escape").symlink_to(outside)
    monkeypatch.setattr("picframe.api.app._path_picker_root", lambda: home.resolve())

    app = create_app(cors_allowed_origins=["*"])
    client = ASGITestClient(app)

    response = client.post(
        "/api/filesystem/validate",
        json={"path": "~/escape", "kind": "directory"},
    )

    assert response.status_code == 403


def test_api_filesystem_validate_allows_missing_mount_with_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("picframe.api.app._path_picker_root", lambda: home.resolve())

    app = create_app(cors_allowed_origins=["*"])
    client = ASGITestClient(app)

    response = client.post(
        "/api/filesystem/validate",
        json={
            "path": "~/PicturesOnNas",
            "kind": "directory",
            "allow_missing": True,
            "field": "model.pic_dir",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is True
    assert data["exists"] is False
    assert data["warnings"] == ["Path does not exist yet"]


def test_api_filesystem_validate_resolves_picframe_data_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    base_dir = home / ".picframe-dev"
    shader_dir = base_dir / "data" / "shaders"
    shader_dir.mkdir(parents=True)
    (shader_dir / "blend_new.fs").write_text("fragment")
    monkeypatch.setattr("picframe.api.app._path_picker_root", lambda: home.resolve())

    app = create_app(
        cors_allowed_origins=["*"],
        resource_paths=ResourcePaths.from_base_dir(base_dir),
    )
    client = ASGITestClient(app)

    response = client.post(
        "/api/filesystem/validate",
        json={
            "path": "${PICFRAME_DATA}/shaders/blend_new.fs",
            "kind": "file",
            "extensions": [".fs"],
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is True
    assert data["path"] == "${PICFRAME_DATA}/shaders/blend_new.fs"


def test_media_event_dto_uses_payload_location_name_before_repository() -> None:
    mock_media_repo = MagicMock()

    dto = media_event_to_response_dto(
        {
            "filepath": "/photos/a.jpg",
            "latitude": 52.5,
            "longitude": 13.4,
            "location": "Berlin",
        },
        media_repository=mock_media_repo,
    )

    assert dto.exif["location_name"] == "Berlin"
    mock_media_repo.get_location.assert_not_called()


def test_media_event_dto_uses_exif_location_before_repository() -> None:
    mock_media_repo = MagicMock()

    dto = media_event_to_response_dto(
        {
            "filepath": "/photos/a.jpg",
            "latitude": 52.5,
            "longitude": 13.4,
            "exif": {"location": "Hamburg"},
        },
        media_repository=mock_media_repo,
    )

    assert dto.exif["location_name"] == "Hamburg"
    mock_media_repo.get_location.assert_not_called()


def test_media_event_dto_uses_injected_repository_for_location_fallback() -> None:
    mock_media_repo = MagicMock()
    mock_media_repo.get_location.return_value = "Repository Berlin"

    dto = media_event_to_response_dto(
        {
            "filepath": "/photos/a.jpg",
            "latitude": 52.5,
            "longitude": 13.4,
            "exif": {"title": "A"},
        },
        media_repository=mock_media_repo,
    )

    assert dto.location == {"lat": 52.5, "lon": 13.4}
    assert dto.exif["location_name"] == "Repository Berlin"
    mock_media_repo.get_location.assert_called_once_with(52.5, 13.4)


def test_media_event_dto_without_repository_does_not_guess_location_path() -> None:
    dto = media_event_to_response_dto(
        {
            "filepath": "/photos/a.jpg",
            "latitude": 52.5,
            "longitude": 13.4,
            "exif": {"title": "A"},
        },
        media_repository=None,
    )

    assert dto.location == {"lat": 52.5, "lon": 13.4}
    assert "location_name" not in dto.exif

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


def test_workflow_config_is_public_and_allowlisted() -> None:
    mock_repo = MagicMock()
    mock_repo.get_all_app_config.return_value = {
        "model.shuffle": True,
        "model.shuffle_mode": "standard",
        "model.subdirectory": "holiday",
        "model.date_from": "",
        "model.date_to": "",
        "model.location_filter": "",
        "model.tags_filter": "",
        "model.time_delay": 20.0,
        "model.fade_time": 2.0,
        "viewer.show_clock": False,
        "viewer.show_text_enabled": True,
        "viewer.text_overlay_format": "title location",
    }
    mock_publisher = MagicMock()
    app = create_app(
        cors_allowed_origins=["*"],
        config_repository=mock_repo,
        event_publisher=mock_publisher,
    )
    client = ASGITestClient(app)

    response = client.get("/api/workflow-config")

    assert response.status_code == 200
    data = response.json()
    assert data["model"]["subdirectory"] == "holiday"
    assert "log_level" not in data["model"]
    assert data["viewer"]["text_overlay_format"] == "title location"

    update = {"model": {"shuffle": False}, "viewer": {"show_clock": True}}
    response = client.put("/api/workflow-config", json=update)

    assert response.status_code == 200
    mock_repo.set_app_config.assert_any_call("model.shuffle", False)
    mock_repo.set_app_config.assert_any_call("viewer.show_clock", True)
    event = mock_publisher.publish.call_args[0][0]
    assert event.command is Command.SET_CONFIG
    assert event.payload == update


def test_workflow_config_rejects_non_workflow_keys() -> None:
    mock_repo = MagicMock()
    app = create_app(cors_allowed_origins=["*"], config_repository=mock_repo)
    client = ASGITestClient(app)

    response = client.put("/api/workflow-config", json={"model": {"log_level": "DEBUG"}})

    assert response.status_code == 403
    mock_repo.set_app_config.assert_not_called()


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


def test_api_system_locales_lists_installed_locales(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completed = MagicMock()
    completed.stdout = "C\nPOSIX\nen_US.utf8\n"
    run = MagicMock(return_value=completed)
    monkeypatch.setattr("picframe.api.app.subprocess.run", run)

    app = create_app(cors_allowed_origins=["*"])
    client = ASGITestClient(app)

    response = client.get("/api/system/locales")

    assert response.status_code == 200
    assert response.json() == {"locales": ["C", "en_US.utf8", "POSIX"]}
    run.assert_called_once()


def test_api_media_location_options_searches_repository() -> None:
    mock_media_repo = MagicMock()
    mock_media_repo.search_location_options.return_value = [
        {"value": "Berlin", "count": 4},
        {"value": "Bern", "count": 1},
    ]

    app = create_app(cors_allowed_origins=["*"], media_repository=mock_media_repo)
    client = ASGITestClient(app)

    response = client.get("/api/media/location-options?q=ber&limit=10")

    assert response.status_code == 200
    assert response.json() == {
        "locations": [
            {"value": "Berlin", "count": 4},
            {"value": "Bern", "count": 1},
        ]
    }
    mock_media_repo.search_location_options.assert_called_once_with("ber", 10)


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


def test_api_get_hardware_inputs_returns_validated_config() -> None:
    mock_repo = MagicMock()
    mock_repo.get_all_app_config.return_value = {
        "hardware_inputs.enabled": True,
        "hardware_inputs.inputs.next_button.type": "button",
        "hardware_inputs.inputs.next_button.pin": 17,
        "hardware_inputs.inputs.next_button.actions.pressed": "NEXT",
    }
    app = create_app(cors_allowed_origins=["*"], config_repository=mock_repo)
    client = ASGITestClient(app)

    response = client.get("/api/hardware-inputs")

    assert response.status_code == 200
    assert response.json() == {
        "enabled": True,
        "inputs": {
            "next_button": {
                "label": "next_button",
                "type": "button",
                "pin": 17,
                "bounce_time": 0.1,
                "actions": {"pressed": "NEXT"},
            }
        },
    }


def test_api_get_hardware_inputs_returns_pir_no_motion_delay() -> None:
    mock_repo = MagicMock()
    mock_repo.get_all_app_config.return_value = {
        "hardware_inputs.enabled": True,
        "hardware_inputs.inputs.motion.type": "pir",
        "hardware_inputs.inputs.motion.pin": 27,
        "hardware_inputs.inputs.motion.no_motion_delay_seconds": 900,
        "hardware_inputs.inputs.motion.actions.motion_detected": "DISPLAY_ON",
        "hardware_inputs.inputs.motion.actions.no_motion": "DISPLAY_OFF",
    }
    app = create_app(cors_allowed_origins=["*"], config_repository=mock_repo)
    client = ASGITestClient(app)

    response = client.get("/api/hardware-inputs")

    assert response.status_code == 200
    assert response.json()["inputs"]["motion"] == {
        "label": "motion",
        "type": "pir",
        "pin": 27,
        "no_motion_delay_seconds": 900.0,
        "actions": {"motion_detected": "DISPLAY_ON", "no_motion": "DISPLAY_OFF"},
    }


def test_api_put_hardware_inputs_persists_and_publishes_config() -> None:
    mock_repo = MagicMock()
    mock_publisher = MagicMock()
    app = create_app(
        cors_allowed_origins=["*"],
        config_repository=mock_repo,
        event_publisher=mock_publisher,
    )
    client = ASGITestClient(app)

    response = client.put(
        "/api/hardware-inputs",
        json={
            "enabled": True,
            "inputs": {
                "next_button": {
                    "type": "button",
                    "pin": 17,
                    "actions": {"pressed": "NEXT"},
                }
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    mock_repo.set_app_config.assert_any_call("hardware_inputs.enabled", True)
    mock_repo.set_app_config.assert_any_call(
        "hardware_inputs.inputs.next_button.actions.pressed", "NEXT"
    )
    event = mock_publisher.publish.call_args[0][0]
    assert event.command.name == "SET_CONFIG"
    assert event.payload["hardware_inputs"]["inputs"]["next_button"]["pin"] == 17


def test_api_put_hardware_inputs_persists_pir_no_motion_delay() -> None:
    mock_repo = MagicMock()
    mock_publisher = MagicMock()
    app = create_app(
        cors_allowed_origins=["*"],
        config_repository=mock_repo,
        event_publisher=mock_publisher,
    )
    client = ASGITestClient(app)

    response = client.put(
        "/api/hardware-inputs",
        json={
            "enabled": True,
            "inputs": {
                "motion": {
                    "type": "pir",
                    "pin": 27,
                    "no_motion_delay_seconds": 900,
                    "actions": {
                        "motion_detected": "DISPLAY_ON",
                        "no_motion": "DISPLAY_OFF",
                    },
                }
            },
        },
    )

    assert response.status_code == 200
    mock_repo.set_app_config.assert_any_call(
        "hardware_inputs.inputs.motion.no_motion_delay_seconds", 900.0
    )
    event = mock_publisher.publish.call_args[0][0]
    assert (
        event.payload["hardware_inputs"]["inputs"]["motion"]["no_motion_delay_seconds"]
        == 900.0
    )


def test_api_put_hardware_inputs_rejects_duplicate_pins() -> None:
    app = create_app(cors_allowed_origins=["*"], config_repository=MagicMock())
    client = ASGITestClient(app)

    response = client.put(
        "/api/hardware-inputs",
        json={
            "enabled": True,
            "inputs": {
                "a": {"type": "button", "pin": 17, "actions": {"pressed": "NEXT"}},
                "b": {"type": "pir", "pin": 17, "actions": {"motion_detected": "DISPLAY_ON"}},
            },
        },
    )

    assert response.status_code == 422


def test_api_put_hardware_inputs_rejects_invalid_no_motion_delay() -> None:
    app = create_app(cors_allowed_origins=["*"], config_repository=MagicMock())
    client = ASGITestClient(app)

    response = client.put(
        "/api/hardware-inputs",
        json={
            "enabled": True,
            "inputs": {
                "motion": {
                    "type": "pir",
                    "pin": 27,
                    "no_motion_delay_seconds": -1,
                    "actions": {"no_motion": "DISPLAY_OFF"},
                }
            },
        },
    )

    assert response.status_code == 422


def test_api_put_config_rejects_invalid_hardware_inputs() -> None:
    app = create_app(cors_allowed_origins=["*"], config_repository=MagicMock())
    client = ASGITestClient(app)

    response = client.put(
        "/api/config",
        json={
            "hardware_inputs": {
                "enabled": True,
                "inputs": {
                    "bad": {
                        "type": "button",
                        "pin": 17,
                        "actions": {"pressed": "SET_BRIGHTNESS"},
                    }
                },
            }
        },
    )

    assert response.status_code == 422


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
