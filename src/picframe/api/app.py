"""
FastAPI Application Setup.

This module initializes the FastAPI application, configures CORS,
and sets up the necessary dependencies for the web control plane.
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, cast

from fastapi import (
    Body,
    FastAPI,
    File,
    HTTPException,
    Query,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from picframe.api.models import (
    APIErrorResponse,
    AppConfig,
    EmptyConfigResponse,
    FilesystemBrowseResponse,
    FilesystemEntryDTO,
    FilesystemValidateRequest,
    FilesystemValidateResponse,
    HardwareInputsConfig,
    HardwareInputsUpdateResponse,
    HealthResponse,
    MediaChangedWebSocketMessage,
    MediaFilterOptionsResponse,
    MediaResponseDTO,
    MediaSelectionCountRequest,
    MediaSelectionCountResponse,
    StateWebSocketMessage,
    StatusMessageResponse,
    StatusResponse,
    SystemErrorWebSocketMessage,
    WebSocketCommandMessage,
)
from picframe.core.events.dto import Command, CommandEvent, CurrentMediaChangedEvent, StateEvent
from picframe.core.events.interfaces import IEventPublisher, IEventSubscriber
from picframe.core.models.playlist import PlaylistCriteria
from picframe.core.repositories.interfaces import IConfigRepository, IMediaRepository
from picframe.core.services.resource_paths import PICFRAME_DATA_TOKEN, ResourcePaths

logger = logging.getLogger(__name__)

STARTUP_ONLY_LEGACY_HTTP_KEYS = {"use_http", "path", "port"}
MEDIA_DTO_EXIF_KEYS = [
    "make", "model", "lens", "f_number", "exposure_time", "iso",
    "focal_length", "exif_datetime", "caption", "tags", "location",
    "title", "rating", "width", "height", "orientation",
    "duration", "codec", "pixel_format", "framerate", "bitrate",
    "displayed_count", "last_displayed"
]

FILESYSTEM_KIND_VALUES = {"any", "file", "directory"}
OPENAPI_DESCRIPTION = """
REST API for the Picframe web control plane.

The live playback channel is the `/ws/state` WebSocket. It accepts command
messages such as `{"command": "NEXT"}` and `{"command": "SET_BRIGHTNESS",
"value": 0.8}`, and emits `MediaChangedEvent`, `StateEvent`, and
`SystemErrorEvent` payloads. Their schemas are included in the OpenAPI
components as documentation-only WebSocket models.
"""
OPENAPI_TAGS = [
    {"name": "System", "description": "Health, host power, and maintenance actions."},
    {"name": "Filesystem", "description": "Safe path browsing and validation for settings."},
    {"name": "Configuration", "description": "Runtime Picframe configuration endpoints."},
    {"name": "Media", "description": "Media selection helpers and media file serving."},
    {"name": "Hardware Inputs", "description": "GPIO button and PIR sensor configuration."},
]
BAD_REQUEST_RESPONSE = {
    400: {"model": APIErrorResponse, "description": "Invalid request for the endpoint."},
}
FORBIDDEN_RESPONSE = {
    403: {"model": APIErrorResponse, "description": "Path or media access is not allowed."},
}
NOT_FOUND_RESPONSE = {
    404: {"model": APIErrorResponse, "description": "Requested path or media was not found."},
}
VALIDATION_RESPONSE = {
    422: {"model": APIErrorResponse, "description": "Request validation failed."},
}
SERVER_ERROR_RESPONSE = {
    500: {"model": APIErrorResponse, "description": "Unexpected server-side processing error."},
}
WEBSOCKET_DOCUMENTATION_MODELS = (
    WebSocketCommandMessage,
    MediaChangedWebSocketMessage,
    StateWebSocketMessage,
    SystemErrorWebSocketMessage,
)


def _path_picker_root() -> Path:
    return Path.home().expanduser().resolve()


def _display_path(path: Path, resource_paths: ResourcePaths | None = None) -> str:
    if resource_paths is not None:
        resolved = path.expanduser().resolve(strict=False)
        try:
            resolved.relative_to(resource_paths.data_dir)
            return resource_paths.tokenized(resolved)
        except ValueError:
            pass

    root = _path_picker_root()
    try:
        relative = path.resolve(strict=False).relative_to(root)
    except ValueError:
        return str(path)
    if str(relative) == ".":
        return "~"
    return f"~/{relative.as_posix()}"


def _resolve_home_path(
    path_value: str | None,
    resource_paths: ResourcePaths | None = None,
) -> Path:
    root = _path_picker_root()
    raw_path = (path_value or "").strip()
    if not raw_path or raw_path == "~":
        candidate = root
    elif resource_paths is not None and (
        raw_path == PICFRAME_DATA_TOKEN or raw_path.startswith(f"{PICFRAME_DATA_TOKEN}/")
    ):
        candidate = Path(resource_paths.resolve(raw_path))
    elif raw_path.startswith("~/"):
        candidate = root / raw_path[2:]
    else:
        raw_candidate = Path(raw_path).expanduser()
        candidate = raw_candidate if raw_candidate.is_absolute() else root / raw_candidate

    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise HTTPException(
            status_code=403,
            detail="Path must stay within the Picframe user's home directory",
        ) from exc
    return resolved


def _filesystem_shortcuts(resource_paths: ResourcePaths | None = None) -> list[FilesystemEntryDTO]:
    shortcuts = []
    raw_shortcuts = ["~", "~/Pictures", "~/DeletedPictures"]
    if resource_paths is not None:
        raw_shortcuts.append(_display_path(resource_paths.base_dir, resource_paths))
    else:
        raw_shortcuts.append("~/.picframe")

    for shortcut in dict.fromkeys(raw_shortcuts):
        try:
            path = _resolve_home_path(shortcut, resource_paths)
        except HTTPException:
            continue
        shortcuts.append(
            FilesystemEntryDTO(
                name=shortcut,
                path=shortcut,
                is_dir=path.is_dir(),
                is_file=path.is_file(),
                extension=path.suffix.lower(),
            )
        )
    return shortcuts


def _normalize_extensions(extensions: str | list[str] | None) -> set[str]:
    if extensions is None:
        return set()
    if isinstance(extensions, str):
        raw_values = [item.strip() for item in extensions.split(",")]
    else:
        raw_values = [str(item).strip() for item in extensions]
    return {
        value.lower() if value.startswith(".") else f".{value.lower()}"
        for value in raw_values
        if value
    }


def _filesystem_entry(
    path: Path,
    resource_paths: ResourcePaths | None = None,
) -> FilesystemEntryDTO:
    return FilesystemEntryDTO(
        name=path.name or _display_path(path, resource_paths),
        path=_display_path(path, resource_paths),
        is_dir=path.is_dir(),
        is_file=path.is_file(),
        extension=path.suffix.lower(),
    )


def _validate_path_request(
    payload: FilesystemValidateRequest,
    resource_paths: ResourcePaths | None = None,
) -> FilesystemValidateResponse:
    kind = payload.kind if payload.kind in FILESYSTEM_KIND_VALUES else "any"
    extensions = _normalize_extensions(payload.extensions)
    path = _resolve_home_path(payload.path, resource_paths)
    exists = path.exists()
    warnings: list[str] = []

    response = FilesystemValidateResponse(
        valid=True,
        path=_display_path(path, resource_paths),
        exists=exists,
        is_dir=path.is_dir(),
        is_file=path.is_file(),
    )

    if not exists:
        if not payload.allow_missing:
            response.valid = False
            response.error = "Path does not exist"
        else:
            warnings.append("Path does not exist yet")
        response.warnings = warnings
        return response

    if kind == "directory" and not path.is_dir():
        response.valid = False
        response.error = "Path must be a directory"
    elif kind == "file" and not path.is_file():
        response.valid = False
        response.error = "Path must be a file"
    elif kind == "file" and extensions and path.suffix.lower() not in extensions:
        response.valid = False
        response.error = f"File extension must be one of: {', '.join(sorted(extensions))}"

    response.warnings = warnings
    return response


def system_error_websocket_message(event: Any) -> str:
    """Serialize a SystemErrorEvent-compatible object for websocket clients."""
    return json.dumps({
        "type": "SystemErrorEvent",
        "message": getattr(event, "message", "Unknown Error"),
        "component": getattr(event, "component", "Unknown"),
        "sticky": bool(getattr(event, "sticky", False)),
        "code": getattr(event, "code", None),
    })


def _coerce_media_item_dict(media_item: Any) -> dict[str, Any]:
    """Convert a current-media event payload into a plain mapping."""
    if hasattr(media_item, "to_dict") and callable(media_item.to_dict):
        return cast(dict[str, Any], media_item.to_dict())
    if hasattr(media_item, "__dict__"):
        return cast(dict[str, Any], media_item.__dict__)
    if isinstance(media_item, dict):
        return cast(dict[str, Any], media_item)
    return {"raw": str(media_item)}


def _media_item_to_dto(
    item_dict: dict[str, Any],
    media_repository: IMediaRepository | None,
) -> MediaResponseDTO:
    """Build a frontend media DTO without depending on a concrete cache database."""
    file_path = item_dict.get("file_path") or item_dict.get("filepath")
    if not file_path:
        file_path = "no_pictures.jpg"

    location = None
    if "latitude" in item_dict and "longitude" in item_dict:
        if item_dict["latitude"] is not None and item_dict["longitude"] is not None:
            location = {
                "lat": item_dict["latitude"],
                "lon": item_dict["longitude"]
            }

    exif_data: dict[str, Any] = {}
    if "exif" in item_dict and isinstance(item_dict["exif"], dict):
        exif_data = dict(item_dict["exif"])
    else:
        for key in MEDIA_DTO_EXIF_KEYS:
            if key in item_dict and item_dict[key] is not None:
                if key == "location" and isinstance(item_dict[key], dict):
                    continue
                exif_data[key] = item_dict[key]

    if "location" in item_dict and isinstance(item_dict["location"], str):
        exif_data["location_name"] = item_dict["location"]
    elif "location" in exif_data and isinstance(exif_data["location"], str):
        exif_data["location_name"] = exif_data["location"]

    if "location_name" not in exif_data and location is not None and media_repository:
        try:
            location_name = media_repository.get_location(location["lat"], location["lon"])
            if location_name:
                exif_data["location_name"] = location_name
        except Exception as e:
            logger.error(f"Error fetching location from media repository: {e}")

    return MediaResponseDTO(
        file_path=str(file_path),
        exif=exif_data,
        location=location,
        id=item_dict.get("id"),
        role=item_dict.get("role"),
        index=item_dict.get("index"),
    )


def media_event_to_response_dto(
    media_item: Any,
    media_repository: IMediaRepository | None = None,
) -> MediaResponseDTO:
    """Serialize current-media event payloads for WebSocket clients."""
    media_dict = _coerce_media_item_dict(media_item)

    layout = str(media_dict.get("layout", "single"))
    primary_index = int(media_dict.get("primary_index", 0) or 0)
    item_dicts = media_dict.get("items")
    if not isinstance(item_dicts, list) or not item_dicts:
        item_dicts = [media_dict]

    item_dtos = [
        _media_item_to_dto(cast(dict[str, Any], item), media_repository)
        for item in item_dicts
        if isinstance(item, dict)
    ]
    if not item_dtos:
        item_dtos = [_media_item_to_dto(media_dict, media_repository)]
        primary_index = 0
    if primary_index < 0 or primary_index >= len(item_dtos):
        primary_index = 0

    primary_dto = item_dtos[primary_index]
    return MediaResponseDTO(
        file_path=primary_dto.file_path,
        exif=primary_dto.exif,
        location=primary_dto.location,
        id=primary_dto.id,
        role=primary_dto.role,
        index=primary_dto.index,
        layout=layout,
        primary_index=primary_index,
        items=item_dtos,
    )


def _normalize_legacy_yaml_config(yaml_data: dict[str, Any]) -> dict[str, Any]:
    """Normalize supported legacy YAML keys before AppConfig validation."""
    viewer = yaml_data.get("viewer")
    if isinstance(viewer, dict):
        if "show_text" in viewer:
            legacy_show_text = viewer.pop("show_text")
            text_overlay_format = "" if legacy_show_text is None else str(legacy_show_text).strip()
            if "text_overlay_format" not in viewer:
                viewer["text_overlay_format"] = text_overlay_format
            if "show_text_enabled" not in viewer:
                viewer["show_text_enabled"] = bool(text_overlay_format)

        if "display_w" in viewer and viewer["display_w"] is not None:
            viewer["display_w"] = str(viewer["display_w"])
        if "display_h" in viewer and viewer["display_h"] is not None:
            viewer["display_h"] = str(viewer["display_h"])
        if "display_power" in viewer:
            viewer["display_power"] = str(viewer["display_power"])

    http = yaml_data.get("http")
    if isinstance(http, dict):
        if "password" in http and http["password"] is None:
            http["password"] = ""

        # These legacy HTTP keys are startup-only in next-gen Picframe.
        for key in STARTUP_ONLY_LEGACY_HTTP_KEYS:
            http.pop(key, None)

    peripherals = yaml_data.get("peripherals")
    if isinstance(peripherals, dict):
        buttons = peripherals.get("buttons")
        if isinstance(buttons, dict):
            for key, value in buttons.items():
                if isinstance(value, dict) and "shortcut" in value:
                    buttons[key] = value["shortcut"]

    return yaml_data


def _install_openapi_documentation(app: FastAPI) -> None:
    """Attach Picframe-specific OpenAPI extensions for WebSocket payloads."""

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return cast(dict[str, Any], app.openapi_schema)

        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
            tags=OPENAPI_TAGS,
        )
        components = schema.setdefault("components", {}).setdefault("schemas", {})
        for model in WEBSOCKET_DOCUMENTATION_MODELS:
            model_schema = model.model_json_schema(ref_template="#/components/schemas/{model}")
            for name, definition in model_schema.pop("$defs", {}).items():
                components.setdefault(name, definition)
            components[model.__name__] = model_schema

        schema["x-websocket-contracts"] = {
            "/ws/state": {
                "description": (
                    "Bidirectional state synchronization channel for playback events "
                    "and remote-control commands."
                ),
                "incoming": [
                    {"$ref": "#/components/schemas/WebSocketCommandMessage"},
                ],
                "outgoing": [
                    {"$ref": "#/components/schemas/MediaChangedWebSocketMessage"},
                    {"$ref": "#/components/schemas/StateWebSocketMessage"},
                    {"$ref": "#/components/schemas/SystemErrorWebSocketMessage"},
                ],
            }
        }
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi  # type: ignore[method-assign]


def create_app(
    cors_allowed_origins: list[str],
    event_publisher: IEventPublisher | None = None,
    event_subscriber: IEventSubscriber | None = None,
    config_repository: IConfigRepository | None = None,
    media_repository: IMediaRepository | None = None,
    image_processing_service: Any | None = None,
    html_dir: str = "~/.picframe/html",
    resource_paths: ResourcePaths | None = None,
) -> FastAPI:
    """
    Create and configure the FastAPI application instance.

    Args:
        event_publisher: Optional event publisher for sending commands.
        event_subscriber: Optional event subscriber for receiving state updates.
        cors_allowed_origins: Optional list of allowed origins for CORS. Defaults to ["*"].

    Returns:
        FastAPI: The configured application instance.
    """
    logger.info("Initializing FastAPI application...")
    resource_paths = resource_paths or ResourcePaths.from_base_dir(
        _path_picker_root() / ".picframe"
    )
    
    app = FastAPI(
        title="Picframe Web Control Plane",
        description=OPENAPI_DESCRIPTION,
        version="2.0.0",
        openapi_tags=OPENAPI_TAGS,
    )
    _install_openapi_documentation(app)

    # Configure CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get(
        "/health",
        response_model=HealthResponse,
        tags=["System"],
        summary="Check API health",
        description="Return a minimal liveness response for the web control plane.",
    )
    async def health_check() -> dict[str, str]:
        """Basic health check endpoint."""
        return {"status": "ok"}

    @app.websocket("/ws/state")
    async def websocket_state(websocket: WebSocket) -> None:
        """WebSocket endpoint for state synchronization."""
        await websocket.accept()
        
        # Queue for sending messages to the websocket from the event bus
        send_queue: asyncio.Queue[str] = asyncio.Queue()
        
        # Capture the event loop here, in the main thread
        loop = asyncio.get_running_loop()
        
        def handle_media_changed(event: CurrentMediaChangedEvent) -> None:
            dto = media_event_to_response_dto(event.media_item, media_repository)
            msg = json.dumps({"type": "MediaChangedEvent", "media": dto.model_dump()})
            # Use call_soon_threadsafe because this callback runs in the event bus thread
            loop.call_soon_threadsafe(send_queue.put_nowait, msg)

        # Initialize rate limiter for outbound state events
        # Default to 10 events per second, burst of 20
        rate_limit = 10.0
        capacity = 20
        if config_repository:
            rate_limit = float(
                config_repository.get_app_config("http.websocket_broadcast_rate_limit", 10.0)
            )
            capacity = int(
                config_repository.get_app_config("http.websocket_broadcast_capacity", 20)
            )
            
        from picframe.core.utils.rate_limit import TokenBucket
        state_rate_limiter = TokenBucket(capacity=capacity, refill_rate=rate_limit)

        def handle_state_changed(event: StateEvent) -> None:
            # Only rate limit state events, not media changes or critical events
            if state_rate_limiter.consume(1):
                msg = json.dumps(
                    {
                        "type": "StateEvent",
                        "state": event.state.name,
                        "payload": event.payload,
                    }
                )
                loop.call_soon_threadsafe(send_queue.put_nowait, msg)
            else:
                logger.debug("WebSocket state broadcast rate limited")

        def handle_system_error(event: Any) -> None:
            # We use Any here to avoid circular imports if SystemErrorEvent is not available
            # but we expect it to be a SystemErrorEvent
            msg = system_error_websocket_message(event)
            loop.call_soon_threadsafe(send_queue.put_nowait, msg)

        if event_subscriber:
            event_subscriber.subscribe(CurrentMediaChangedEvent, handle_media_changed)
            event_subscriber.subscribe(StateEvent, handle_state_changed)
            
            # Try to subscribe to SystemErrorEvent if it exists
            try:
                from picframe.core.events.dto import SystemErrorEvent
                event_subscriber.subscribe(SystemErrorEvent, handle_system_error)
            except ImportError:
                pass
            
            # Request the current state and media immediately upon connection
            if event_publisher:
                event_publisher.publish(CommandEvent(command=Command.REQUEST_STATE))

        # Initialize debouncer for inbound commands
        debounce_ms = 200
        if config_repository:
            debounce_ms = int(config_repository.get_app_config("http.command_debounce_ms", 200))
            
        from picframe.core.utils.debounce import Debouncer
        command_debouncer = Debouncer(delay_ms=debounce_ms)

        async def receive_messages() -> None:
            try:
                while True:
                    data = await websocket.receive_text()
                    logger.debug(f"Received websocket message: {data}")
                    try:
                        payload = json.loads(data)
                        command_str = payload.get("command")
                        if command_str and event_publisher:
                            # Apply debouncing to high-frequency commands
                            if command_str in ("NEXT", "PREV", "SET_BRIGHTNESS"):
                                if not command_debouncer.should_execute(command_str):
                                    logger.debug(f"Debounced command: {command_str}")
                                    continue
                                    
                            if command_str == "NEXT":
                                event_publisher.publish(CommandEvent(command=Command.NEXT))
                            elif command_str == "PREV":
                                event_publisher.publish(CommandEvent(command=Command.PREV))
                            elif command_str == "PAUSE":
                                event_publisher.publish(CommandEvent(command=Command.PAUSE))
                            elif command_str == "PLAY":
                                event_publisher.publish(CommandEvent(command=Command.PLAY))
                            elif command_str == "SET_BRIGHTNESS":
                                value = payload.get("value")
                                if value is not None:
                                    event_publisher.publish(
                                        CommandEvent(
                                            command=Command.SET_BRIGHTNESS, payload=float(value)
                                        )
                                    )
                            elif command_str == "DISPLAY_ON":
                                event_publisher.publish(CommandEvent(command=Command.DISPLAY_ON))
                            elif command_str == "DISPLAY_OFF":
                                event_publisher.publish(CommandEvent(command=Command.DISPLAY_OFF))
                            elif command_str == "DELETE":
                                delete_payload = {
                                    k: v for k, v in payload.items() if k != "command"
                                }
                                event_publisher.publish(
                                    CommandEvent(
                                        command=Command.DELETE,
                                        payload=delete_payload or None,
                                    )
                                )
                            elif command_str == "PURGE_FILES":
                                event_publisher.publish(CommandEvent(command=Command.PURGE_FILES))
                            elif command_str == "STOP":
                                event_publisher.publish(CommandEvent(command=Command.STOP))
                            elif command_str == "REBOOT_HOST":
                                event_publisher.publish(CommandEvent(command=Command.REBOOT_HOST))
                            elif command_str == "SHUTDOWN_HOST":
                                event_publisher.publish(CommandEvent(command=Command.SHUTDOWN_HOST))
                            elif command_str == "REQUEST_STATE":
                                event_publisher.publish(CommandEvent(command=Command.REQUEST_STATE))
                            elif command_str == "SET_CONFIG":
                                # The frontend sends the payload directly in the root object,
                                # not nested under "payload"
                                # e.g. {"command": "SET_CONFIG", "viewer": {"show_clock": true}}
                                config_payload = payload.get("payload")
                                if config_payload is None:
                                    # Extract everything except the command key
                                    config_payload = {
                                        k: v for k, v in payload.items() if k != "command"
                                    }
                                
                                if config_payload:
                                    event_publisher.publish(
                                        CommandEvent(
                                            command=Command.SET_CONFIG, payload=config_payload
                                        )
                                    )
                    except json.JSONDecodeError:
                        logger.error("Invalid JSON received on websocket")
            except WebSocketDisconnect:
                pass

        async def send_messages() -> None:
            try:
                while True:
                    msg = await send_queue.get()
                    await websocket.send_text(msg)
            except WebSocketDisconnect:
                pass

        try:
            # Run both tasks concurrently
            await asyncio.gather(
                receive_messages(),
                send_messages(),
            )
        except WebSocketDisconnect:
            logger.info("WebSocket client disconnected")
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
        finally:
            if event_subscriber:
                event_subscriber.unsubscribe(CurrentMediaChangedEvent, handle_media_changed)
                event_subscriber.unsubscribe(StateEvent, handle_state_changed)
                try:
                    from picframe.core.events.dto import SystemErrorEvent
                    event_subscriber.unsubscribe(SystemErrorEvent, handle_system_error)
                except ImportError:
                    pass

    @app.post(
        "/api/system/reboot",
        response_model=StatusResponse,
        tags=["System"],
        summary="Reboot the host",
        description="Queue a host reboot command on the Picframe event bus.",
    )
    async def api_reboot() -> dict[str, str]:
        """Trigger a full host-level OS reboot."""
        if event_publisher:
            event_publisher.publish(CommandEvent(command=Command.REBOOT_HOST))
        return {"status": "rebooting"}

    @app.post(
        "/api/system/shutdown",
        response_model=StatusResponse,
        tags=["System"],
        summary="Shut down the host",
        description="Queue a host shutdown command on the Picframe event bus.",
    )
    async def api_shutdown() -> dict[str, str]:
        """Trigger a full host-level OS shutdown."""
        if event_publisher:
            event_publisher.publish(CommandEvent(command=Command.SHUTDOWN_HOST))
        return {"status": "shutting down"}

    @app.post(
        "/api/maintenance/purge-db",
        response_model=StatusResponse,
        tags=["System"],
        summary="Purge missing media rows",
        description="Queue a maintenance command that purges database entries for missing files.",
    )
    async def api_purge_db() -> dict[str, str]:
        """Trigger a database purge of missing files."""
        if event_publisher:
            event_publisher.publish(CommandEvent(command=Command.PURGE_FILES))
        return {"status": "purging database"}

    @app.post(
        "/api/maintenance/clear-cache",
        response_model=StatusMessageResponse,
        response_model_exclude_none=True,
        tags=["System"],
        summary="Clear generated media cache",
        description=(
            "Delete generated image and video-frame cache artifacts. Original media files "
            "and media database rows are not removed."
        ),
    )
    async def api_clear_cache() -> dict[str, str]:
        """Clear generated image and video-frame cache artifacts."""
        if not image_processing_service:
            return {
                "status": "error",
                "message": "Image cache service not available",
            }
        image_processing_service.clear_cache()
        return {"status": "cache cleared"}

    @app.get(
        "/api/filesystem/browse",
        response_model=FilesystemBrowseResponse,
        tags=["Filesystem"],
        summary="Browse filesystem paths",
        description=(
            "List safe filesystem entries under the Picframe user's home directory for "
            "settings path pickers."
        ),
        responses={
            **BAD_REQUEST_RESPONSE,
            **FORBIDDEN_RESPONSE,
            **NOT_FOUND_RESPONSE,
            **VALIDATION_RESPONSE,
        },
    )
    async def api_filesystem_browse(
        path: str = Query("~", description="Path to browse. Supports `~` and `${PICFRAME_DATA}`."),
        kind: str = Query("any", description="Entry filter: `any`, `file`, or `directory`."),
        extensions: str = Query(
            "",
            description="Comma-separated extension filter for file entries.",
        ),
    ) -> dict[str, Any]:
        """Browse host filesystem paths safely under the Picframe user's home."""
        if kind not in FILESYSTEM_KIND_VALUES:
            raise HTTPException(status_code=422, detail="Unsupported filesystem browse kind")

        directory = _resolve_home_path(path, resource_paths)
        if not directory.exists():
            raise HTTPException(status_code=404, detail="Path does not exist")
        if not directory.is_dir():
            raise HTTPException(status_code=400, detail="Path must be a directory")

        extension_set = _normalize_extensions(extensions)
        entries: list[FilesystemEntryDTO] = []
        try:
            for child in directory.iterdir():
                try:
                    resolved_child = child.resolve(strict=False)
                    resolved_child.relative_to(_path_picker_root())
                except (OSError, ValueError):
                    continue

                is_dir = child.is_dir()
                is_file = child.is_file()
                if kind == "directory" and not is_dir:
                    continue
                if kind == "file" and not is_dir:
                    if not is_file:
                        continue
                    if extension_set and child.suffix.lower() not in extension_set:
                        continue
                entries.append(_filesystem_entry(child, resource_paths))
        except OSError as exc:
            raise HTTPException(status_code=400, detail=f"Unable to read path: {exc}") from exc

        entries.sort(key=lambda item: (not item.is_dir, item.name.lower()))
        root = _path_picker_root()
        parent = None if directory == root else _display_path(directory.parent, resource_paths)
        return FilesystemBrowseResponse(
            root=_display_path(root, resource_paths),
            path=_display_path(directory, resource_paths),
            parent=parent,
            entries=entries,
            shortcuts=_filesystem_shortcuts(resource_paths),
        ).model_dump()

    @app.post(
        "/api/filesystem/validate",
        response_model=FilesystemValidateResponse,
        tags=["Filesystem"],
        summary="Validate a filesystem path",
        description=(
            "Validate a settings path under the Picframe user's home directory and report "
            "existence, file type, warnings, and validation errors."
        ),
        responses={**FORBIDDEN_RESPONSE, **VALIDATION_RESPONSE},
    )
    async def api_filesystem_validate(
        payload: FilesystemValidateRequest,
    ) -> dict[str, Any]:
        """Validate a Settings path under the Picframe user's home directory."""
        return _validate_path_request(payload, resource_paths).model_dump()

    @app.get(
        "/api/config",
        response_model=EmptyConfigResponse | AppConfig,
        tags=["Configuration"],
        summary="Get current configuration",
        description=(
            "Return Picframe's nested runtime configuration. A bare `{}` response means "
            "the application was created without a configuration repository."
        ),
    )
    async def api_get_config() -> dict[str, Any]:
        """Get the full application configuration."""
        if not config_repository:
            return {}
            
        # Use ConfigService to handle the unflattening logic
        # We create a temporary instance here since the API layer doesn't have
        # direct access to the long-running ConfigService instance.
        # In a more complex setup, this would be injected.
        class DummyPublisher(IEventPublisher):
            def publish(self, event: Any) -> None: pass
        class DummySubscriber(IEventSubscriber):
            def subscribe(self, event_type: type, callback: Any) -> None: pass
            def unsubscribe(self, event_type: type, callback: Any) -> None: pass
            
        from picframe.core.services.config_service import ConfigService
        temp_service = ConfigService(config_repository, DummySubscriber(), DummyPublisher())
        nested_config = temp_service.get_nested_config()
        
        # Pass through Pydantic model to populate default values
        from picframe.api.models import AppConfig
        app_config = AppConfig(**nested_config)
        return app_config.model_dump()

    @app.get(
        "/api/media/filter-options",
        response_model=MediaFilterOptionsResponse,
        tags=["Media"],
        summary="Get media filter options",
        description=(
            "Return distinct subdirectories, locations, tags, and sort columns for the "
            "Remote media selection controls."
        ),
    )
    async def api_media_filter_options() -> dict[str, Any]:
        """Return distinct values for Remote media selection controls."""
        if not media_repository:
            return {
                "subdirectories": [],
                "locations": [],
                "tags": [],
                "sort_columns": [],
            }
        pic_dir = None
        if config_repository:
            pic_dir = str(config_repository.get_app_config("model.pic_dir", "~/Pictures"))
        return media_repository.get_filter_options(pic_dir)

    @app.post(
        "/api/media/selection-count",
        response_model=MediaSelectionCountResponse,
        tags=["Media"],
        summary="Count selected media",
        description=(
            "Return selected and folder-scope media counts for the supplied Remote "
            "media selection filters."
        ),
        responses={**VALIDATION_RESPONSE},
    )
    async def api_media_selection_count(
        payload: MediaSelectionCountRequest | None = Body(
            default=None,
            description="Optional media selection filters. Empty body uses default filters.",
        ),
    ) -> dict[str, Any]:
        """Return selected and folder-scope media counts for Remote filters."""
        payload = payload or MediaSelectionCountRequest()
        if not media_repository:
            scope_label = payload.subdirectory.strip().strip("/")
            return MediaSelectionCountResponse(
                scope="subdirectory" if scope_label else "pic_dir",
                scope_label=scope_label,
            ).model_dump()

        pic_dir = "~/Pictures"
        if config_repository:
            pic_dir = str(config_repository.get_app_config("model.pic_dir", pic_dir))
        criteria = PlaylistCriteria(
            pic_dir=pic_dir,
            subdirectory=payload.subdirectory,
            date_from=payload.date_from,
            date_to=payload.date_to,
            location_filter=payload.location_filter,
            tags_filter=payload.tags_filter,
            shuffle=False,
            recent_n=0,
        )
        counts = media_repository.count_media(criteria)
        return MediaSelectionCountResponse(**counts).model_dump()

    @app.get(
        "/api/hardware-inputs",
        response_model=HardwareInputsConfig,
        tags=["Hardware Inputs"],
        summary="Get hardware input configuration",
        description="Return validated GPIO button and PIR sensor input configuration.",
    )
    async def api_get_hardware_inputs() -> dict[str, Any]:
        """Get validated hardware input configuration."""
        if not config_repository:
            return HardwareInputsConfig().model_dump()

        class DummyPublisher(IEventPublisher):
            def publish(self, event: Any) -> None: pass
        class DummySubscriber(IEventSubscriber):
            def subscribe(self, event_type: type, callback: Any) -> None: pass
            def unsubscribe(self, event_type: type, callback: Any) -> None: pass

        from picframe.core.services.config_service import ConfigService
        temp_service = ConfigService(config_repository, DummySubscriber(), DummyPublisher())
        nested_config = temp_service.get_nested_config()
        return HardwareInputsConfig(**nested_config.get("hardware_inputs", {})).model_dump()

    @app.put(
        "/api/hardware-inputs",
        response_model=HardwareInputsUpdateResponse,
        response_model_exclude_none=True,
        tags=["Hardware Inputs"],
        summary="Update hardware input configuration",
        description=(
            "Validate, persist, and broadcast GPIO button and PIR sensor input "
            "configuration."
        ),
        responses={**VALIDATION_RESPONSE},
    )
    async def api_put_hardware_inputs(payload: HardwareInputsConfig) -> dict[str, Any]:
        """Update validated hardware input configuration."""
        if not config_repository:
            return {"status": "error", "message": "Config repository not available"}

        class DummyPublisher(IEventPublisher):
            def publish(self, event: Any) -> None: pass
        class DummySubscriber(IEventSubscriber):
            def subscribe(self, event_type: type, callback: Any) -> None: pass
            def unsubscribe(self, event_type: type, callback: Any) -> None: pass

        from picframe.core.services.config_service import ConfigService
        temp_service = ConfigService(config_repository, DummySubscriber(), DummyPublisher())

        config_dict = payload.model_dump()
        temp_service.update_nested_config({"hardware_inputs": config_dict})

        if event_publisher:
            event_publisher.publish(
                CommandEvent(command=Command.SET_CONFIG, payload={"hardware_inputs": config_dict})
            )

        return {
            "status": "success",
            "hardware_inputs": config_dict,
        }

    @app.post(
        "/api/config/import-yaml",
        response_model=StatusMessageResponse,
        response_model_exclude_none=True,
        tags=["Configuration"],
        summary="Import legacy YAML configuration",
        description=(
            "Parse a legacy `configuration.yaml`, normalize supported legacy keys, validate "
            "it against the API config model, persist valid settings, and broadcast config "
            "changes."
        ),
        responses={**BAD_REQUEST_RESPONSE, **VALIDATION_RESPONSE, **SERVER_ERROR_RESPONSE},
    )
    async def api_import_yaml(
        file: UploadFile = File(..., description="Legacy Picframe configuration YAML file."),
    ) -> dict[str, Any]:
        """Import legacy configuration.yaml file."""
        if not config_repository:
            return {"status": "error", "message": "Config repository not available"}
            
        try:
            content = await file.read()
            import yaml
            yaml_data = yaml.safe_load(content)
            
            if not isinstance(yaml_data, dict):
                raise ValueError("Invalid YAML format: expected a dictionary")
                
            # Use ConfigService to handle the flattening logic
            class DummyPublisher(IEventPublisher):
                def publish(self, event: Any) -> None: pass
            class DummySubscriber(IEventSubscriber):
                def subscribe(self, event_type: type, callback: Any) -> None: pass
                def unsubscribe(self, event_type: type, callback: Any) -> None: pass
                
            from picframe.core.services.config_service import ConfigService
            temp_service = ConfigService(config_repository, DummySubscriber(), DummyPublisher())
            
            yaml_data = _normalize_legacy_yaml_config(yaml_data)

            # Validate against AppConfig, ignoring unknown fields
            # Pydantic v2 ignores extra fields by default unless configured otherwise
            from picframe.api.models import AppConfig
            app_config = AppConfig(**yaml_data)
            
            config_dict = app_config.model_dump(exclude_unset=True)
            temp_service.update_nested_config(config_dict)
            
            # Publish a SET_CONFIG event to notify other components
            if event_publisher:
                event_publisher.publish(
                    CommandEvent(command=Command.SET_CONFIG, payload=config_dict)
                )
                
            return {
                "status": "success",
                "message": "Legacy YAML configuration imported successfully",
            }
            
        except yaml.YAMLError as e:
            raise HTTPException(status_code=400, detail=f"Invalid YAML file: {e}")
        except Exception as e:
            logger.error(f"Error importing YAML: {e}")
            raise HTTPException(status_code=500, detail=f"Error importing configuration: {e}")

    @app.put(
        "/api/config",
        response_model=StatusMessageResponse,
        response_model_exclude_none=True,
        tags=["Configuration"],
        summary="Update current configuration",
        description=(
            "Validate and persist Picframe runtime configuration, then broadcast a "
            "`SET_CONFIG` command so running services can react."
        ),
        responses={**VALIDATION_RESPONSE},
    )
    async def api_put_config(payload: AppConfig = Body(...)) -> dict[str, str]:
        """Update the application configuration."""
        if not config_repository:
            return {"status": "error", "message": "Config repository not available"}
            
        # Use ConfigService to handle the flattening logic
        class DummyPublisher(IEventPublisher):
            def publish(self, event: Any) -> None: pass
        class DummySubscriber(IEventSubscriber):
            def subscribe(self, event_type: type, callback: Any) -> None: pass
            def unsubscribe(self, event_type: type, callback: Any) -> None: pass
            
        from picframe.core.services.config_service import ConfigService
        temp_service = ConfigService(config_repository, DummySubscriber(), DummyPublisher())
        
        # Convert Pydantic model to dict, excluding unset values to avoid overwriting
        # existing config with None values if the frontend didn't send them.
        config_dict = payload.model_dump(exclude_unset=True)
        temp_service.update_nested_config(config_dict)
                
        # Publish a SET_CONFIG event to notify other components
        if event_publisher:
            event_publisher.publish(CommandEvent(command=Command.SET_CONFIG, payload=config_dict))
            
        return {"status": "success"}

    @app.get(
        "/media",
        response_class=FileResponse,
        tags=["Media"],
        summary="Serve an allowed media file",
        description=(
            "Serve image and video files only when the requested path belongs to the "
            "configured media directories or Picframe's default placeholder image."
        ),
        responses={
            200: {
                "description": "Media file stream.",
                "content": {
                    "image/jpeg": {},
                    "image/png": {},
                    "image/gif": {},
                    "video/mp4": {},
                    "video/quicktime": {},
                    "video/x-matroska": {},
                    "video/x-msvideo": {},
                    "video/webm": {},
                    "application/octet-stream": {},
                },
            },
            **FORBIDDEN_RESPONSE,
            **NOT_FOUND_RESPONSE,
        },
    )
    async def serve_media(
        path: str = Query(..., description="Absolute media path to stream."),
    ) -> FileResponse:
        """Serve media files from the filesystem."""
        file_path = Path(path).resolve()
        
        # Basic security check: only serve files with known media extensions
        # to prevent arbitrary file read (e.g., /etc/passwd)
        allowed_extensions = {
            ".jpg", ".jpeg", ".png", ".gif", ".heic",
            ".mp4", ".mov", ".mkv", ".avi", ".webm"
        }
        
        # Security check: ensure the path is within the configured media directory
        is_allowed = False
        if config_repository:
            # We need to get the full config to check the pic_dir
            # Since IConfigRepository doesn't have a get_config method, we'll use get_all_app_config
            # and reconstruct the nested structure, or just get the specific key if it's flat
            pic_dir_str = config_repository.get_app_config("model.pic_dir", "~/Pictures")
            pic_dir = Path(pic_dir_str).expanduser().resolve()
            
            # Also check directories table
            allowed_dirs = [pic_dir]
            for d in config_repository.get_all_directories():
                allowed_dirs.append(Path(d["path"]).expanduser().resolve())
                
            for allowed_dir in allowed_dirs:
                if file_path.is_relative_to(allowed_dir):
                    is_allowed = True
                    break
                
        if not is_allowed:
            # Allow serving the default no_pictures.jpg
            user_no_pic_path = Path.home() / ".picframe" / "data" / "no_pictures.jpg"
            fallback_path = Path(__file__).parent.parent / "data" / "no_pictures.jpg"
            if file_path == user_no_pic_path.resolve() or file_path == fallback_path.resolve():
                is_allowed = True
                
        if not is_allowed:
            raise HTTPException(status_code=403, detail="Access denied")
        
        if (file_path.exists() and file_path.is_file() and
            file_path.suffix.lower() in allowed_extensions):
            return FileResponse(file_path)
            
        # Return a 404 or a default image if not found
        # First try the user's configuration directory
        user_no_pic_path = Path.home() / ".picframe" / "data" / "no_pictures.jpg"
        if user_no_pic_path.exists() and user_no_pic_path.is_file():
            return FileResponse(user_no_pic_path)
            
        # Fallback to the source code directory
        fallback_path = Path(__file__).parent.parent / "data" / "no_pictures.jpg"
        if fallback_path.exists() and fallback_path.is_file():
            return FileResponse(fallback_path)
            
        # If all else fails, return a 404
        raise HTTPException(status_code=404, detail="Media not found")

    # Serve SPA static files
    html_dir_path = Path(html_dir).expanduser()
    if html_dir_path.exists():
        # Mount the assets directory
        assets_dir = html_dir_path / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        # Catch-all route for SPA
        @app.get("/{full_path:path}", include_in_schema=False)
        async def serve_spa(full_path: str) -> FileResponse:
            requested_file = html_dir_path / full_path
            if full_path and requested_file.is_file():
                return FileResponse(requested_file)
            return FileResponse(html_dir_path / "index.html")
    else:
        logger.warning(
            f"Frontend build directory not found at {html_dir_path}. Web UI will not be available."
        )

    return app
