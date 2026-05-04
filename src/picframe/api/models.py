"""Pydantic models for API payload validation."""

from typing import Any

from pydantic import BaseModel, Field


class ViewerConfig(BaseModel):
    blur_amount: int | None = None
    blur_zoom: float | None = None
    blur_edges: bool | None = None
    edge_alpha: float | None = None
    fps: float | None = None
    background: list[Any] | None = None
    blend_type: str | None = None
    font_file: str | None = None
    shader: str | None = None
    show_text_fm: str | None = None
    show_text_tm: float | None = None
    show_text_sz: int | None = None
    show_text: str | None = None
    text_justify: str | None = None
    text_bkg_hgt: float | None = None
    text_opacity: float | None = None
    text_x_margin: int | None = None
    text_y_margin: int | None = None
    fit: bool | None = None
    video_fit_display: bool | None = None
    kenburns: bool | None = None
    display_x: int | None = None
    display_y: int | None = None
    display_w: str | None = None
    display_h: str | None = None
    display_power: str | None = None
    display_hdmi: str | None = None
    use_glx: bool | None = None
    use_sdl2: bool | None = None
    mat_images: float | None = None
    mat_type: str | None = None
    outer_mat_color: str | None = None
    inner_mat_color: str | None = None
    outer_mat_border: int | None = None
    inner_mat_border: int | None = None
    outer_mat_use_texture: bool | None = None
    inner_mat_use_texture: bool | None = None
    mat_resource_folder: str | None = None
    show_clock: bool | None = None
    clock_justify: str | None = None
    clock_text_sz: int | None = None
    clock_format: str | None = None
    clock_opacity: float | None = None
    clock_top_bottom: str | None = None
    clock_wdt_offset_pct: float | None = None
    clock_hgt_offset_pct: float | None = None
    menu_text_sz: int | None = None
    menu_autohide_tm: float | None = None
    geo_suppress_list: list[Any] | None = None

class ModelConfig(BaseModel):
    pic_dir: str | None = None
    deleted_pictures: str | None = None
    follow_links: bool | None = None
    no_files_img: str | None = None
    subdirectory: str | None = None
    recent_n: int | None = None
    reshuffle_num: int | None = None
    time_delay: float | None = None
    fade_time: float | None = None
    update_interval: float | None = None
    shuffle: bool | None = None
    sort_cols: str | None = None
    image_attr: list[Any] | None = None
    load_geoloc: bool | None = None
    geo_key: str | None = None
    locale: str | None = None
    key_list: list[Any] | None = None
    db_file: str | None = None
    portrait_pairs: bool | None = None
    location_filter: str | None = None
    tags_filter: str | None = None
    log_level: str | None = None
    log_file: str | None = None

class MqttConfig(BaseModel):
    use_mqtt: bool | None = None
    server: str | None = None
    port: int | None = None
    login: str | None = None
    password: str | None = None
    tls: str | None = None
    device_id: str | None = None
    device_url: str | None = None

class HttpConfig(BaseModel):
    use_http: bool | None = None
    path: str | None = None
    port: int | None = None
    auth: bool | None = None
    username: str | None = None
    password: str | None = None
    use_ssl: bool | None = None
    keyfile: str | None = None
    certfile: str | None = None

class PeripheralButtons(BaseModel):
    pause: str | None = None
    display_off: str | None = None
    location: str | None = None
    exit: str | None = None
    power_down: str | None = None

class PeripheralsConfig(BaseModel):
    input_type: str | None = None
    buttons: PeripheralButtons | None = None
    enable: bool | None = None
    label: str | None = None
    shortcut: str | None = None

class AppConfig(BaseModel):
    viewer: ViewerConfig = Field(default_factory=ViewerConfig)
    model: ModelConfig = Field(default_factory=ModelConfig)
    mqtt: MqttConfig = Field(default_factory=MqttConfig)
    http: HttpConfig = Field(default_factory=HttpConfig)
    peripherals: PeripheralsConfig = Field(default_factory=PeripheralsConfig)
