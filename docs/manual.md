# Picframe Configuration & Setup Manual

This document provides comprehensive instructions for configuring and setting up Picframe. It is divided into standard user instructions and extended developer guidelines.

---

## Part 1: Standard User Instructions

Picframe uses a centralized configuration management system backed by SQLite and validated by Pydantic.

### Initialization (`picframe init`)

When you run `picframe init`, the application bootstraps your environment (defaulting to `~/.picframe`).

#### Interactive Prompts
If the configuration database (`config.db3`) or media cache database (`media_cache.db3`) already exists, the CLI will interactively prompt you to either keep or delete them.

#### Force Flag
For automated environments (like Docker or CI/CD), you can bypass these prompts using the `--force` (or `-f`) flag:
```bash
picframe init --force
```
This will automatically overwrite any existing databases.

#### Database Seeding
If the configuration database is newly created or cleared, it is automatically seeded with default values. These defaults are read from `src/picframe/config/default_config.yaml`, validated against the Pydantic models, and stored in the SQLite database.

### CLI Parameters

The `picframe run` command accepts several parameters to override default paths and ports. These parameters take precedence over any configuration database settings.

*   `--dir`: Base directory for picframe data (default: `~/.picframe` or `PICFRAME_DIR` env var).
*   `--port`: Port for the web server (default: `9000` or `PICFRAME_PORT` env var).
*   `--config-db`: Path to config database (default: `<dir>/data/config.db3` or `PICFRAME_CONFIG_DB` env var).
*   `--media-db`: Path to media database (default: `<dir>/data/media_cache.db3` or `PICFRAME_MEDIA_DB` env var).
*   `--html-dir`: Path to frontend HTML assets (default: `<dir>/html` or `PICFRAME_HTML_DIR` env var).

*Note: The webserver port and HTML directory path are strictly managed via CLI arguments and environment variables. They are not editable via the frontend UI to prevent connection loss and synchronization issues.*

### Geocoding Configuration (`key_list`)

The `model.key_list` configuration parameter dictates how raw address data from the Nominatim reverse geocoding service is formatted into a human-readable location string.

#### Structure Requirement: List of Lists
This parameter **must** be structured strictly as a list of lists (e.g., `[["tourism", "amenity"], ["city", "town", "village"], ["country"]]`).

Each inner list represents a single "slot" or component in the final comma-separated location string. The items within an inner list define **prioritized fallback options** for that slot.

**Example Default Configuration:**
```json
[
    ["tourism", "amenity", "isolated_dwelling"],
    ["suburb", "village"],
    ["city", "county"],
    ["region", "state", "province"],
    ["country"]
]
```

**How it works:**
1. The system evaluates the first inner list: `["tourism", "amenity", "isolated_dwelling"]`.
2. It checks the Nominatim response for the key `tourism`. If found, it adds the value to the location string and **stops checking** the rest of this inner list.
3. If `tourism` is not found, it checks for `amenity`, and so on.
4. It then moves to the next inner list (`["suburb", "village"]`) and repeats the process.

This nested structure prevents redundant output (like "Berlin, Berlin" if Nominatim returns both a `city` and a `county` key for the same location) by acting as an `OR` condition within the group and an `AND` condition between groups.

#### Available Nominatim Keys
You can customize the `key_list` using any of the standard address keys returned by Nominatim. Common keys include:

*   **Points of Interest:** `tourism`, `amenity`, `historic`, `leisure`, `shop`, `office`, `building`
*   **Specific Locations:** `isolated_dwelling`, `farm`, `house_number`, `road`, `pedestrian`, `square`
*   **Neighborhoods/Localities:** `suburb`, `village`, `hamlet`, `town`, `city_district`, `borough`, `quarter`, `neighbourhood`
*   **Municipalities:** `city`, `town`, `municipality`, `county`, `local_administrative_area`
*   **Regions:** `region`, `state`, `province`, `state_district`
*   **National:** `country`, `country_code`
*   **Postal:** `postcode`

### Network & Security Configuration

#### CORS (Cross-Origin Resource Sharing)
The API's CORS policy is managed via the `cors_allowed_origins` parameter within the `http` section of the configuration. This setting dictates which external domains are permitted to make requests to the Picframe API from a web browser.

*   **Type:** List of strings
*   **Default:** `["*"]` (Allows requests from any origin)
*   **Location:** `http.cors_allowed_origins`

**Security Note:** The default `["*"]` is permissive to ensure out-of-the-box compatibility on local networks. If you expose your Picframe API to the internet or want to strictly lock down access, you should update this setting via the Web UI or SQLite database to explicitly list your allowed domains (e.g., `["http://localhost:5173", "https://my-picframe.example.com"]`).

---

## Part 2: Extended Developer Guidelines & System Setup

This section defines the foundational structures and system permissions required for developing, testing, and deploying Picframe.

### Development Environment & System Setup

To develop, test, and deploy Picframe, specific system packages are required depending on the host OS. The provided `docs/install_picframe.sh` script automates this process, including dynamic hardware probing for optimal video playback.

#### Automated Hardware Probing and Video Acceleration

The installation script now includes intelligent hardware probing to ensure GStreamer utilizes the best available video decoding method:

1.  **Architecture Detection:** The script detects if it's running on ARM (Raspberry Pi) or x86/x86_64.
2.  **Virtual Machine Detection:** It checks if the environment is a Virtual Machine (using `systemd-detect-virt`).
3.  **Dynamic Dependency Installation:**
    *   **Raspberry Pi (ARM):** Installs `gstreamer1.0-gl` and `gstreamer1.0-v4l2` for native hardware acceleration.
    *   **Bare-Metal Linux (x86/x86_64):** Uses `lspci` to identify the GPU vendor (Intel, AMD, or NVIDIA) and installs the corresponding VA-API drivers (e.g., `intel-media-va-driver-non-free`, `mesa-va-drivers`, `vdpau-driver-all`) alongside `gstreamer1.0-vaapi` and `vainfo`.
    *   **Virtual Machines:** Installs generic `gstreamer1.0-vaapi` support, though hardware acceleration is often limited without GPU passthrough.

#### GStreamer Fallback Mechanism

Picframe's video renderer is designed to be resilient. If hardware-accelerated decoding (via VA-API, V4L2, etc.) is unavailable or fails to initialize (e.g., in a VM without GPU passthrough or if specific plugins are missing), GStreamer's `autoplug-select` mechanism will automatically fall back to software decoding.

To support this fallback, the installation script always installs `gstreamer1.0-libav`, which provides robust software decoders for formats like H.265/HEVC. While software decoding consumes more CPU resources, it ensures video playback remains functional across diverse environments.

#### Manual Installation (Ubuntu / Debian)
If you prefer to install dependencies manually for headless testing or windowed SDL2 rendering:
```bash
sudo apt-get update
sudo apt-get install -y libsdl2-dev libegl1-mesa-dev libgles2-mesa-dev xvfb gstreamer1.0-libav gstreamer1.0-vaapi vainfo
```
*(Note: `xvfb` is used for headless automated testing of OpenGL contexts. `gstreamer1.0-libav` provides software decoders. `gstreamer1.0-vaapi` and `vainfo` provide hardware acceleration support via VA-API).*

#### Manual Installation (Raspberry Pi)
```bash
sudo apt-get update
sudo apt-get install -y libsdl2-dev libegl1-mesa-dev libgles2-mesa-dev wlr-randr ddcutil brightnessctl i2c-tools gstreamer1.0-libav gstreamer1.0-gl gstreamer1.0-v4l2
```
*(Note: `gstreamer1.0-gl` and `gstreamer1.0-v4l2` provide hardware acceleration support for the Raspberry Pi).*

**Note on Display Power Management:**
`wlr-randr` is required for turning the display on and off under Wayland. It is not always installed by default on Raspberry Pi OS and must be explicitly installed.

To allow the application to control display brightness without root privileges, ensure the user running the application is added to the appropriate groups:
```bash
sudo usermod -aG i2c $USER    # For ddcutil (external HDMI/DP monitors)
sudo usermod -aG video $USER  # For brightnessctl (internal DSI/eDP displays)
sudo usermod -aG render $USER # For DRM/KMS access
```

**Note on System Power Management (Critical):**
To allow the application to reboot or shut down the host system without prompting for a password, you must configure `sudo` or `polkit` for the user running the application. The `LinuxSystemManager` relies on these permissions to function correctly without interactive prompts.

For `sudo` (visudo):
```bash
# Add the following line to /etc/sudoers (using visudo)
# Replace 'pi' with the actual username running the application
pi ALL=(ALL) NOPASSWD: /sbin/reboot, /sbin/shutdown
```

Alternatively, you can dynamically create a drop-in file in `/etc/sudoers.d/` for the current user:
```bash
echo "$USER ALL=(ALL) NOPASSWD: /sbin/reboot, /sbin/shutdown" | sudo tee /etc/sudoers.d/picframe-power
sudo chmod 0440 /etc/sudoers.d/picframe-power
```

**Note on Virtual Machine Development:**
Hardware-level display tools (`ddcutil`, `brightnessctl`, `wlr-randr`) will not function correctly within an Ubuntu Virtual Machine because hypervisors do not emulate physical I2C, PWM, or DRM interfaces. For local VM development, the application must use the `MockDisplayPower` adapter. Furthermore, hardware-accelerated video decoding may be limited or unavailable in a VM unless GPU passthrough is configured.

### Developer Guide: Adding Configuration Keys

To add a new configuration key, you must update three locations to ensure the frontend, backend validation, and database seeding remain synchronized:

1.  **Frontend Schema (`frontend/src/configSchema.json`)**:
    Add the new key and its type to the appropriate section. This dictates how the Vue.js frontend renders the input field.

2.  **Backend Baseline (`src/picframe/config/default_config.yaml`)**:
    Add the new key with its default value. This file acts as the single source of truth for factory resets and initial database seeding.

3.  **Backend Validation (`src/picframe/api/models.py`)**:
    Add the new key to the corresponding Pydantic model (e.g., `ViewerConfig`, `ModelConfig`). Ensure you provide a default value (e.g., `my_new_key: int = 10`) so that validation passes even if the key is missing from an older database.

### Database Migrations

Picframe uses a code-based migration system to handle schema changes for both `config.db3` and `media_cache.db3`.

To modify a database schema:
1.  Open the relevant repository file (`src/picframe/core/repositories/sqlite_config.py` or `sqlite_media.py`).
2.  Locate the `MIGRATIONS` list (e.g., `CONFIG_MIGRATIONS`).
3.  Append a new `Migration` object to the list.
4.  Increment the `version` integer sequentially.
5.  Provide the SQL `up_script` to execute the schema change.

Example:
```python
CONFIG_MIGRATIONS = [
    # ... existing migrations ...
    Migration(
        version=2,
        up_script="ALTER TABLE app_config ADD COLUMN description TEXT;"
    )
]
```
The `MigrationManager` will automatically detect and apply this script during the next application startup.
