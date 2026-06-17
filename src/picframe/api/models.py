"""Pydantic models for API payload validation."""

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from picframe.core.models.hardware_input import normalize_hardware_inputs_config

AuthScope = Literal["none", "settings", "site"]


class APIErrorResponse(BaseModel):
    """Error response returned by HTTPException and validation handlers."""
    detail: Any = Field(description="Human-readable error detail or validation error payload.")


class HealthResponse(BaseModel):
    """Liveness response for the web control plane."""
    status: str = Field(description="Current health state.", examples=["ok"])


class StatusResponse(BaseModel):
    """Generic status response for command endpoints."""
    status: str = Field(description="Result or queued command state.")


class StatusMessageResponse(StatusResponse):
    """Status response with an optional explanatory message."""
    message: str | None = Field(default=None, description="Optional status detail.")


class SystemServiceStatusResponse(BaseModel):
    """Runtime status for the managed Picframe systemd service."""
    status: Literal["active", "inactive", "unavailable"] = "unavailable"
    active: bool = False
    restart_available: bool = False
    message: str | None = None


class BasicAuthConfigResponse(BaseModel):
    """Public shape of the plaintext Basic Auth settings."""
    enabled: bool = False
    username: str = "admin"
    scope: AuthScope = "none"
    password_set: bool = False
    password: str | None = None


class BasicAuthConfigRequest(BaseModel):
    """Request to update Basic Auth settings."""
    scope: AuthScope | None = None
    enabled: bool | None = None
    username: str = "admin"
    password: str | None = None


class LogEventMessage(BaseModel):
    """Log event sent over /ws/logs."""
    type: Literal["LogEvent"] = "LogEvent"
    timestamp: float
    level: str
    logger: str
    message: str
    formatted: str


class LogSnapshotMessage(BaseModel):
    """Initial log snapshot sent when a Logs websocket connects."""
    type: Literal["LogSnapshot"] = "LogSnapshot"
    events: list[LogEventMessage] = Field(default_factory=list)


class MediaResponseDTO(BaseModel):
    """Data Transfer Object for media items sent to the frontend."""
    file_path: str
    exif: dict[str, Any] = Field(default_factory=dict)
    location: dict[str, float] | None = None
    id: int | None = None
    role: str | None = None
    index: int | None = None
    layout: str = "single"
    primary_index: int = 0
    items: list["MediaResponseDTO"] = Field(default_factory=list)


class MediaSelectionCountRequest(BaseModel):
    """Remote media-selection filters used for count previews."""
    subdirectory: str = ""
    date_from: str = ""
    date_to: str = ""
    location_filter: str = ""
    tags_filter: str = ""


class MediaSelectionCountResponse(BaseModel):
    """Count preview for Remote media-selection filters."""
    selected_count: int = 0
    total_count: int = 0
    scope: str = "pic_dir"
    scope_label: str = ""


class MediaFilterOptionsResponse(BaseModel):
    """Distinct values used to populate Remote media filter controls."""
    subdirectories: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    sort_columns: list[dict[str, Any]] = Field(default_factory=list)


class MediaLocationOptionDTO(BaseModel):
    """A searchable media location option with usage count."""
    value: str
    count: int = 0


class MediaLocationOptionsResponse(BaseModel):
    """Search results for the Remote location picker."""
    locations: list[MediaLocationOptionDTO] = Field(default_factory=list)


class LocaleOptionsResponse(BaseModel):
    """Installed host locales visible to Settings."""
    locales: list[str] = Field(default_factory=list)


class FilesystemEntryDTO(BaseModel):
    """Filesystem entry visible to the Settings path picker."""
    name: str
    path: str
    is_dir: bool = False
    is_file: bool = False
    extension: str = ""


class FilesystemBrowseResponse(BaseModel):
    """Safe filesystem browse response rooted at the Picframe user's home."""
    root: str
    path: str
    parent: str | None = None
    entries: list[FilesystemEntryDTO] = Field(default_factory=list)
    shortcuts: list[FilesystemEntryDTO] = Field(default_factory=list)


class FilesystemValidateRequest(BaseModel):
    """Path validation request for Settings path controls."""
    path: str = ""
    kind: str = "any"
    field: str = ""
    allow_missing: bool = False
    extensions: list[str] = Field(default_factory=list)


class FilesystemValidateResponse(BaseModel):
    """Path validation result for Settings path controls."""
    valid: bool = False
    path: str = ""
    exists: bool = False
    is_dir: bool = False
    is_file: bool = False
    warnings: list[str] = Field(default_factory=list)
    error: str = ""


class ViewerConfig(BaseModel):
    blur_amount: int = 12
    blur_zoom: float = 1.0
    blur_edges: bool = False
    edge_alpha: float = 0.5
    fps: float = 20.0
    background: list[Any] = Field(default_factory=lambda: [0.2, 0.2, 0.3, 1.0])
    blend_type: str = "blend"
    font_file: str = "${PICFRAME_DATA}/fonts/NotoSans-Regular.ttf"
    shader: str = "${PICFRAME_DATA}/shaders/blend_new"
    show_text_fm: str = "%b %d, %Y"
    show_text_tm: float = 20.0
    show_text_sz: int = 40
    show_text_enabled: bool = True
    text_overlay_format: str = "title caption name date folder location"
    text_justify: str = "L"
    text_bkg_hgt: float = 0.25
    text_opacity: float = 1.0
    text_x_margin: int = 100
    text_y_margin: int = 0
    fit: bool = False
    video_fit_display: bool = False
    max_software_decode_resolution: str = "1280x720"
    kenburns: bool = False
    display_x: int = 0
    display_y: int = 0
    display_w: str | None = None
    display_h: str | None = None
    display_power: str = "0"
    display_hdmi: str = "HDMI-A-1"
    use_glx: bool = False
    use_sdl2: bool = True
    mat_images: bool | float | str = 0.01
    mat_type: str | None = None
    outer_mat_color: str | None = None
    inner_mat_color: str | None = None
    outer_mat_border: int = 75
    inner_mat_border: int = 40
    outer_mat_use_texture: bool = True
    inner_mat_use_texture: bool = False
    mat_resource_folder: str = "${PICFRAME_DATA}/mat"
    show_clock: bool = False
    clock_justify: str = "R"
    clock_text_sz: int = 120
    clock_format: str = "%-I:%M"
    clock_opacity: float = 1.0
    clock_top_bottom: str = "T"
    clock_wdt_offset_pct: float = 3.0
    clock_hgt_offset_pct: float = 3.0
    menu_text_sz: int = 40
    menu_autohide_tm: float = 10.0
    geo_suppress_list: list[Any] = Field(default_factory=list)

class ModelConfig(BaseModel):
    pic_dir: str = "~/Pictures"
    image_extensions: list[str] = Field(default_factory=lambda: [
        ".jpg", ".jpeg", ".png", ".heic", ".heif"
    ])
    video_extensions: list[str] = Field(default_factory=lambda: [
        ".mp4", ".mkv", ".flv", ".mov", ".avi", ".webm", ".hevc"
    ])
    deleted_pictures: str = "~/DeletedPictures"
    follow_links: bool = False
    no_files_img: str = "${PICFRAME_DATA}/no_pictures.jpg"
    subdirectory: str = ""
    date_from: str = ""
    date_to: str = ""
    recent_n: int = 7
    reshuffle_num: int = 1
    time_delay: float = 200.0
    fade_time: float = 10.0
    update_interval: float = 2.0
    shuffle: bool = True
    shuffle_mode: str = "standard"
    sort_cols: str = "fname ASC"
    image_attr: list[Any] = Field(default_factory=lambda: [
        "PICFRAME GPS",
        "PICFRAME LOCATION",
        "EXIF FNumber",
        "EXIF ExposureTime",
        "EXIF ISOSpeedRatings",
        "EXIF FocalLength",
        "EXIF DateTimeOriginal",
        "Image Model",
        "Image Make",
        "IPTC Caption/Abstract",
        "IPTC Object Name",
        "IPTC Keywords"
    ])
    load_geoloc: bool = False
    geo_key: str = "this_needs_to@be_changed"
    locale: str = "en_US.utf8"
    key_list: list[list[str]] = Field(default_factory=lambda: [
        ["tourism", "amenity", "isolated_dwelling"],
        ["suburb", "village"],
        ["city", "county"],
        ["region", "state", "province"],
        ["country"]
    ])
    portrait_pairs: bool = False
    location_filter: str = ""
    tags_filter: str = ""
    log_level: str = "WARNING"
    log_file: str = ""

class MqttConfig(BaseModel):
    use_mqtt: bool = False
    server: str = "your_mqtt_broker"
    port: int = 1883
    login: str = "name"
    password: str = "your_password"
    tls: str = ""
    device_id: str = "picframe"
    device_url: str = ""

class HttpConfig(BaseModel):
    auth: bool = False
    username: str = "admin"
    password: str = ""
    use_ssl: bool = False
    keyfile: str = "path/to/key.pem"
    certfile: str = "path/to/cert.pem"
    websocket_broadcast_rate_limit: float = 10.0
    websocket_broadcast_capacity: int = 20
    command_debounce_ms: int = 200
    cors_allowed_origins: list[str] = Field(default_factory=lambda: ["*"])

class PeripheralButtons(BaseModel):
    pause: str = " "
    display_off: str = "o"
    location: str = "l"
    exit: str = "e"
    power_down: str = "p"

class PeripheralsConfig(BaseModel):
    input_type: str | None = None
    buttons: PeripheralButtons = Field(default_factory=PeripheralButtons)
    enable: bool = True
    label: str = ""
    shortcut: str = ""


class HardwareInputsConfig(BaseModel):
    enabled: bool = False
    inputs: dict[str, dict[str, Any]] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def validate_hardware_inputs(cls, data: Any) -> dict[str, Any]:
        return normalize_hardware_inputs_config(data)


class HardwareInputsUpdateResponse(StatusMessageResponse):
    """Result returned after updating hardware input configuration."""
    hardware_inputs: dict[str, Any] | None = Field(
        default=None,
        description="Validated hardware input configuration that was persisted.",
    )


class AppConfig(BaseModel):
    viewer: ViewerConfig = Field(default_factory=ViewerConfig)
    model: ModelConfig = Field(default_factory=ModelConfig)
    mqtt: MqttConfig = Field(default_factory=MqttConfig)
    http: HttpConfig = Field(default_factory=HttpConfig)
    peripherals: PeripheralsConfig = Field(default_factory=PeripheralsConfig)
    hardware_inputs: HardwareInputsConfig = Field(default_factory=HardwareInputsConfig)


class EmptyConfigResponse(BaseModel):
    """Empty configuration response used when no repository is injected."""


class WebSocketCommandMessage(BaseModel):
    """Inbound command message accepted by the /ws/state WebSocket."""
    command: Literal[
        "NEXT",
        "PREV",
        "PAUSE",
        "PLAY",
        "SET_BRIGHTNESS",
        "DISPLAY_ON",
        "DISPLAY_OFF",
        "DELETE",
        "PURGE_FILES",
        "STOP",
        "REBOOT_HOST",
        "SHUTDOWN_HOST",
        "REQUEST_STATE",
        "SET_CONFIG",
    ] = Field(description="Command name to publish to the Picframe event bus.")
    value: float | None = Field(
        default=None,
        description="Brightness value for SET_BRIGHTNESS commands.",
    )
    payload: dict[str, Any] | None = Field(
        default=None,
        description="Optional command payload, primarily used by SET_CONFIG.",
    )


class MediaChangedWebSocketMessage(BaseModel):
    """Outbound WebSocket message sent when the current media item changes."""
    type: Literal["MediaChangedEvent"] = "MediaChangedEvent"
    media: MediaResponseDTO


class StateWebSocketMessage(BaseModel):
    """Outbound WebSocket message sent for playback and system state updates."""
    type: Literal["StateEvent"] = "StateEvent"
    state: str = Field(description="State enum name, such as PLAYING or PAUSED.")
    payload: Any = Field(default=None, description="Optional state-specific payload.")


class SystemErrorWebSocketMessage(BaseModel):
    """Outbound WebSocket message sent for user-visible system errors."""
    type: Literal["SystemErrorEvent"] = "SystemErrorEvent"
    message: str
    component: str
    sticky: bool = False
    code: str | None = None
