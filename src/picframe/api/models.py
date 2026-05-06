"""Pydantic models for API payload validation."""

from typing import Any

from pydantic import BaseModel, Field


class MediaResponseDTO(BaseModel):
    """Data Transfer Object for media items sent to the frontend."""
    file_path: str
    exif: dict[str, Any] = Field(default_factory=dict)
    location: dict[str, float] | None = None


class ViewerConfig(BaseModel):
    blur_amount: int = 12
    blur_zoom: float = 1.0
    blur_edges: bool = False
    edge_alpha: float = 0.5
    fps: float = 20.0
    background: list[Any] = Field(default_factory=lambda: [0.2, 0.2, 0.3, 1.0])
    blend_type: str = "blend"
    font_file: str = "~/picframe_data/data/fonts/NotoSans-Regular.ttf"
    shader: str = "~/picframe_data/data/shaders/blend_new"
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
    kenburns: bool = False
    display_x: int = 0
    display_y: int = 0
    display_w: str | None = None
    display_h: str | None = None
    display_power: str = "0"
    display_hdmi: str = "HDMI-A-1"
    use_glx: bool = False
    use_sdl2: bool = True
    mat_images: float = 0.01
    mat_type: str | None = None
    outer_mat_color: str | None = None
    inner_mat_color: str | None = None
    outer_mat_border: int = 75
    inner_mat_border: int = 40
    outer_mat_use_texture: bool = True
    inner_mat_use_texture: bool = False
    mat_resource_folder: str = "~/picframe_data/data/mat"
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
    no_files_img: str = "~/picframe_data/data/no_pictures.jpg"
    subdirectory: str = ""
    recent_n: int = 7
    reshuffle_num: int = 1
    time_delay: float = 200.0
    fade_time: float = 10.0
    update_interval: float = 2.0
    shuffle: bool = True
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
    key_list: list[Any] = Field(default_factory=lambda: [
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

class AppConfig(BaseModel):
    viewer: ViewerConfig = Field(default_factory=ViewerConfig)
    model: ModelConfig = Field(default_factory=ModelConfig)
    mqtt: MqttConfig = Field(default_factory=MqttConfig)
    http: HttpConfig = Field(default_factory=HttpConfig)
    peripherals: PeripheralsConfig = Field(default_factory=PeripheralsConfig)
