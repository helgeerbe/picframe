# Phase 1 Readiness & Prerequisites

This document defines the foundational structures required before implementing the Phase 1 Core Image MVP.

## 1. Database Schemas

The system utilizes a Dual-Database Strategy to separate persistent user configuration from ephemeral media metadata.

### 1.1 `config.db3` (Persistent Configuration)

This database replaces the legacy `configuration.yaml`. It stores user preferences that must survive reboots and media cache rebuilds.

```sql
-- Table to track schema versions for migrations
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Core configuration settings (key-value store for flexibility, or structured tables)
-- We will use a structured approach for type safety and easier querying.

CREATE TABLE IF NOT EXISTS viewer_config (
    id INTEGER PRIMARY KEY CHECK (id = 1), -- Ensure only one row exists
    blur_amount INTEGER DEFAULT 12,
    blur_zoom REAL DEFAULT 1.0,
    blur_edges BOOLEAN DEFAULT 0,
    edge_alpha REAL DEFAULT 0.5,
    fps REAL DEFAULT 20.0,
    background_r REAL DEFAULT 0.2,
    background_g REAL DEFAULT 0.2,
    background_b REAL DEFAULT 0.3,
    background_a REAL DEFAULT 1.0,
    blend_type TEXT DEFAULT 'blend',
    font_file TEXT DEFAULT '~/picframe_data/data/fonts/NotoSans-Regular.ttf',
    shader TEXT DEFAULT '~/picframe_data/data/shaders/blend_new',
    show_text_fm TEXT DEFAULT '%b %d, %Y',
    show_text_tm REAL DEFAULT 20.0,
    show_text_sz INTEGER DEFAULT 40,
    show_text TEXT DEFAULT 'title caption name date folder location',
    text_justify TEXT DEFAULT 'L',
    text_bkg_hgt REAL DEFAULT 0.25,
    text_opacity REAL DEFAULT 1.0,
    text_x_margin INTEGER DEFAULT 100,
    text_y_margin INTEGER DEFAULT 0,
    fit BOOLEAN DEFAULT 0,
    video_fit_display BOOLEAN DEFAULT 0,
    kenburns BOOLEAN DEFAULT 0,
    display_x INTEGER DEFAULT 0,
    display_y INTEGER DEFAULT 0,
    display_w INTEGER DEFAULT NULL,
    display_h INTEGER DEFAULT NULL,
    display_power INTEGER DEFAULT 2,
    display_hdmi TEXT DEFAULT 'HDMI-A-1',
    use_glx BOOLEAN DEFAULT 0,
    use_sdl2 BOOLEAN DEFAULT 1,
    mat_images REAL DEFAULT 0.01,
    mat_type TEXT DEFAULT NULL,
    outer_mat_color TEXT DEFAULT NULL,
    inner_mat_color TEXT DEFAULT NULL,
    outer_mat_border INTEGER DEFAULT 75,
    inner_mat_border INTEGER DEFAULT 40,
    outer_mat_use_texture BOOLEAN DEFAULT 1,
    inner_mat_use_texture BOOLEAN DEFAULT 0,
    mat_resource_folder TEXT DEFAULT '~/picframe_data/data/mat',
    show_clock BOOLEAN DEFAULT 0,
    clock_justify TEXT DEFAULT 'R',
    clock_text_sz INTEGER DEFAULT 120,
    clock_format TEXT DEFAULT '%-I:%M',
    clock_opacity REAL DEFAULT 1.0,
    clock_top_bottom TEXT DEFAULT 'T',
    clock_wdt_offset_pct REAL DEFAULT 3.0,
    clock_hgt_offset_pct REAL DEFAULT 3.0,
    menu_text_sz INTEGER DEFAULT 40,
    menu_autohide_tm REAL DEFAULT 10.0
);

CREATE TABLE IF NOT EXISTS model_config (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    pic_dir TEXT DEFAULT '~/Pictures',
    deleted_pictures TEXT DEFAULT '~/DeletedPictures',
    follow_links BOOLEAN DEFAULT 0,
    no_files_img TEXT DEFAULT '~/picframe_data/data/no_pictures.jpg',
    subdirectory TEXT DEFAULT '',
    recent_n INTEGER DEFAULT 7,
    reshuffle_num INTEGER DEFAULT 1,
    time_delay REAL DEFAULT 200.0,
    fade_time REAL DEFAULT 10.0,
    update_interval REAL DEFAULT 2.0,
    shuffle BOOLEAN DEFAULT 1,
    sort_cols TEXT DEFAULT 'fname ASC',
    load_geoloc BOOLEAN DEFAULT 0,
    geo_key TEXT DEFAULT 'this_needs_to@be_changed',
    locale TEXT DEFAULT 'en_US.utf8',
    portrait_pairs BOOLEAN DEFAULT 0,
    location_filter TEXT DEFAULT '',
    tags_filter TEXT DEFAULT '',
    log_level TEXT DEFAULT 'WARNING',
    log_file TEXT DEFAULT ''
);

-- Tables for lists/arrays in config
CREATE TABLE IF NOT EXISTS geo_suppress_list (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    suppress_string TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS image_attr_list (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attr_string TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS geo_key_list (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    level INTEGER NOT NULL, -- 0 for tourism/amenity, 1 for suburb/village, etc.
    key_string TEXT NOT NULL
);
```

### 1.2 `media_cache.db3` (Ephemeral Metadata)

This database stores extracted metadata for fast querying and playlist generation. It can be safely deleted and rebuilt.

```sql
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS media_items (
    file_id INTEGER PRIMARY KEY AUTOINCREMENT,
    fname TEXT UNIQUE NOT NULL,          -- Full path to the file
    last_modified REAL NOT NULL,         -- OS timestamp
    file_type TEXT NOT NULL,             -- 'image' or 'video'
    
    -- Extracted Metadata
    orientation INTEGER DEFAULT 1,
    exif_datetime REAL,                  -- Parsed to timestamp
    f_number REAL,
    exposure_time TEXT,
    iso INTEGER,
    focal_length TEXT,
    make TEXT,
    model TEXT,
    lens TEXT,
    rating INTEGER,
    latitude REAL,
    longitude REAL,
    width INTEGER,
    height INTEGER,
    title TEXT,
    caption TEXT,
    tags TEXT,
    is_portrait BOOLEAN,
    location TEXT,                       -- Reverse geocoded string
    
    -- Video specific
    duration REAL,
    
    -- Internal state
    is_deleted BOOLEAN DEFAULT 0         -- Soft delete flag
);

-- Indexes for fast playlist generation
CREATE INDEX IF NOT EXISTS idx_media_fname ON media_items(fname);
CREATE INDEX IF NOT EXISTS idx_media_last_modified ON media_items(last_modified);
CREATE INDEX IF NOT EXISTS idx_media_exif_datetime ON media_items(exif_datetime);
```

## 2. Event Dictionary

The system uses a Strict Event-Driven Architecture. All communication across the `PriorityQueue` Event Bus uses immutable DTOs (`@dataclass(frozen=True)`).

### 2.1 Base Event Types

*   **`CommandEvent`**: A request for the system to *do* something (e.g., Pause, Next, Sleep). Usually high priority.
*   **`StateEvent`**: A notification that the system's state *has changed* (e.g., Now Playing, Paused). Usually normal priority.
*   **`RenderCommand`**: A specific instruction for the Presentation Layer to draw pixels.
*   **`FileChangeEvent`**: A notification from the `MediaMonitorService` that the filesystem changed.

### 2.2 Event Definitions

| Event Class | Payload | Priority | Description |
| :--- | :--- | :--- | :--- |
| `CommandEvent(NEXT)` | None | 1 (High) | Skip to the next media item immediately. |
| `CommandEvent(PREV)` | None | 1 (High) | Go back to the previous media item immediately. |
| `CommandEvent(PAUSE)` | None | 1 (High) | Pause the current playback (stop the timer/video). |
| `CommandEvent(PLAY)` | None | 1 (High) | Resume playback. |
| `CommandEvent(SLEEP)` | None | 2 (Medium) | Turn off the display (via `DisplayPowerManager`). |
| `CommandEvent(WAKE)` | None | 2 (Medium) | Turn on the display. |
| `CommandEvent(REBOOT)` | None | 1 (High) | Reboot the host OS. |
| `CommandEvent(SHUTDOWN)`| None | 1 (High) | Shutdown the host OS. |
| `CommandEvent(SET_VOL)` | `level: int` (0-100) | 2 (Medium) | Adjust video playback volume. |
| `CommandEvent(DELETE)` | None | 1 (High) | Delete the currently playing media item. |
| `CommandEvent(PURGE_FILES)` | None | 2 (Medium) | Purge missing files from the database. |
| `CommandEvent(STOP)` | None | 1 (High) | Stop the application gracefully. |
| `CommandEvent(SET_CONFIG)` | `key: str`, `value: Any` | 2 (Medium) | Update a configuration value (e.g., `time_delay`, `brightness`, `location_filter`). |
| `CommandEvent(TOGGLE_TEXT)` | `field: str`, `state: bool` | 2 (Medium) | Toggle text overlays (e.g., `title`, `caption`, `date`, `location`). |
| `CommandEvent(REFRESH_TEXT)` | None | 2 (Medium) | Force a refresh of the text overlays. |
| `StateEvent(PLAYING)` | `item: MediaItem` | 3 (Normal) | Broadcast when a new item starts playing. |
| `StateEvent(PAUSED)` | `item: MediaItem` | 3 (Normal) | Broadcast when playback is paused. |
| `StateEvent(SLEEPING)` | None | 3 (Normal) | Broadcast when the display is turned off. |
| `StateEvent(CONFIG_CHANGED)` | `key: str`, `value: Any` | 3 (Normal) | Broadcast when a configuration value has been updated. |
| `StateEvent(STATS_UPDATED)` | `image_counter: int`, `directory: str` | 3 (Normal) | Broadcast when system stats (like total images) change. |
| `RenderCommand` | `image_path: str`, `overlay: OverlayConfig` | 2 (Medium) | Instructs `Pi3dRenderer` to draw an image. |
| `FileChangeEvent` | `event_type: str` (created/modified/deleted), `path: str` | 4 (Low) | Triggered by `watchdog` when media folders change. |
| `SystemErrorEvent` | `message: str`, `component: str` | 1 (High) | Broadcast when a critical error occurs (Poison Pill). |

## 3. CI/CD Pipeline (GitHub Actions)

A basic workflow to enforce the Definition of Done on every Pull Request targeting `v2-dev`.

**File:** `.github/workflows/pr-checks.yml`

```yaml
name: PR Quality Checks

on:
  pull_request:
    branches: [ "v2-dev" ]

jobs:
  quality-gates:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4
    
    - name: Set up Python
      uses: actions/setup-python@v5
      with:
        python-version: "3.11"
        cache: "pip"
        
    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -e .[dev]
        
    - name: Run Ruff (Linting & Formatting)
      run: ruff check . && ruff format --check .
      
    - name: Run Mypy (Type Checking)
      run: mypy src/picframe
      
    - name: Run Pytest
      run: pytest test/
```

## 4. Development Environment

To develop and test the core engine locally (especially the `Pi3dRenderer`), specific system packages are required depending on the host OS.

### 4.1 Ubuntu / Debian (Native or WSL2)
For headless testing or windowed SDL2 rendering:
```bash
sudo apt-get update
sudo apt-get install -y libsdl2-dev libegl1-mesa-dev libgles2-mesa-dev xvfb
```
*(Note: `xvfb` is used for headless automated testing of OpenGL contexts).*

### 4.2 Raspberry Pi (Target Hardware)
```bash
sudo apt-get update
sudo apt-get install -y libsdl2-dev libegl1-mesa-dev libgles2-mesa-dev