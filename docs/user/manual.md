# Picframe Configuration & Setup Manual

This document provides comprehensive instructions for configuring and setting up Picframe. It is divided into standard user instructions and extended developer guidelines.

---

## Part 1: Standard User Instructions

Picframe uses a centralized configuration management system backed by SQLite and validated by Pydantic.
The installed `picframe` command uses the next-generation CLI. The public
commands are `picframe init` and `picframe run`; legacy direct
`picframe configuration.yaml` startup is not part of the next-generation public
entry point.

### Quick Install From GitHub

On Raspberry Pi OS / Debian-style systems, download the installer script from
GitHub, make it executable, and run it with `sudo`:

```bash
curl -fsSL \
  https://raw.githubusercontent.com/helgeerbe/picframe/main/docs/user/install_picframe.sh \
  -o install_picframe.sh
chmod +x install_picframe.sh
sudo ./install_picframe.sh
```

For next-generation testing from the development branch, use `v2-dev` instead
of `main`:

```bash
curl -fsSL \
  https://raw.githubusercontent.com/helgeerbe/picframe/v2-dev/docs/user/install_picframe.sh \
  -o install_picframe.sh
chmod +x install_picframe.sh
sudo ./install_picframe.sh --branch v2-dev
```

The current helper script installs the required APT packages, configures basic
hardware access groups and power-management sudoers rules, creates a virtual
environment at `~/picframe_env`, installs Picframe from GitHub `main` by
default, provisions the selected locale, and runs:

```bash
~/picframe_env/bin/picframe init --force
```

After installation, start Picframe manually with:

```bash
~/picframe_env/bin/picframe run
```

On Raspberry Pi OS Lite, create the default media and deleted-media folders
before the first service start:

```bash
mkdir -p ~/Pictures ~/DeletedPictures
```

If Picframe already started before `~/Pictures` existed, create the directory
and restart the service once so the media watcher can attach to it:

```bash
sudo systemctl restart picframe.service
```

Installer options:

```bash
# Use defaults without prompts
sudo ./install_picframe.sh --yes

# Install Picframe from GitHub v2-dev
sudo ./install_picframe.sh --branch v2-dev

# Install Picframe from GitHub v2-dev and enable boot startup
sudo ./install_picframe.sh --branch v2-dev --enable-service

# Select a locale and generate it if it is missing
sudo ./install_picframe.sh --locale de_DE.UTF-8

# Install from a local checkout
sudo ./install_picframe.sh --source local --local-path /home/pi/Development/picframe

# Install from PyPI
sudo ./install_picframe.sh --source pypi
```

#### Optional Systemd Boot Service

Pass `--enable-service` to create `/etc/systemd/system/picframe.service` and
enable Picframe on boot:

```bash
sudo ./install_picframe.sh --enable-service
```

On Raspberry Pi OS Lite the default service display mode is `wayland-kiosk`,
which starts Picframe inside the lightweight `cage` Wayland compositor instead
of requiring a full desktop environment. The installer also installs `labwc`;
if it behaves better on the target Pi, use `--display-mode labwc-kiosk`
instead. The installer enables `seatd` for kiosk compositor modes.

```bash
sudo ./install_picframe.sh --enable-service --display-mode labwc-kiosk
```

Service commands:

```bash
sudo systemctl status picframe.service
sudo systemctl start picframe.service
sudo systemctl stop picframe.service
sudo systemctl disable picframe.service
```

### Initialization (`picframe init`)

When you run `picframe init`, the application bootstraps your environment (defaulting to `~/.picframe`).

The default runtime directory layout is:

```text
~/.picframe/
  data/
    config.db3          # Persistent runtime configuration
    media_cache.db3     # Rebuildable media metadata and playback statistics
    cache/              # Generated image/video transition artifacts
    fonts/              # Packaged renderer fonts
    mat/                # Packaged matting textures and patches
    shaders/            # Packaged pi3d shader files
    no_pictures.jpg     # Fallback image shown when no media is indexed
  html/                 # Compiled Vue SPA served by FastAPI
```

Original photos and videos are not copied into `~/.picframe`. By default,
Picframe indexes `~/Pictures`; change `model.pic_dir` in Settings if your media
library lives elsewhere.

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

### Import Legacy `configuration.yaml`

Existing users can import a legacy `configuration.yaml` after running `picframe init`.
The import is an explicit user action: initialization creates and seeds `config.db3`
with defaults first, then the Settings UI can merge supported legacy values into that
database.

To import a legacy configuration:

1. Start Picframe and open the Settings UI.
2. Click **Import**.
3. Select the existing `configuration.yaml` file. Files ending in `.yaml` and `.yml`
   are accepted.

The Settings UI sends the file to `/api/config/import-yaml`. The backend validates the
supported runtime settings and immediately writes them to `config.db3`; after a
successful import, the Settings UI refreshes and shows the imported values.

Some legacy keys are renamed during import. For example, legacy `viewer.show_text` is
migrated to `viewer.text_overlay_format` and `viewer.show_text_enabled` unless those
next-generation keys are already present in the imported file. Obsolete or startup-only
legacy fields are ignored. In particular, `http.use_http`, `http.path`, and `http.port`
are not stored in `config.db3`; startup behavior is controlled by CLI arguments and
environment variables instead.

### CLI Parameters

The `picframe run` command accepts several parameters to override default paths and ports. These parameters take precedence over any configuration database settings.

*   `--dir`: Base directory for picframe data (default: `~/.picframe` or `PICFRAME_DIR` env var).
*   `--port`: Port for the web server (default: `9000` or `PICFRAME_PORT` env var).
*   `--config-db`: Path to config database (default: `<dir>/data/config.db3` or `PICFRAME_CONFIG_DB` env var).
*   `--media-db`: Path to media database (default: `<dir>/data/media_cache.db3` or `PICFRAME_MEDIA_DB` env var).
*   `--html-dir`: Path to frontend HTML assets (default: `<dir>/html` or `PICFRAME_HTML_DIR` env var).

*Note: The webserver port and HTML directory path are strictly managed via CLI arguments and environment variables. They are not editable via the frontend UI to prevent connection loss and synchronization issues.*

### Web Control Plane

When `picframe run` or `picframe.service` is active, open the web UI from a
browser on the same local network:

```text
http://<picframe-host>:9000/
```

The Vue SPA is served by the FastAPI backend from `~/.picframe/html` by
default. The main views are:

*   **Remote:** playback controls, current media details, selected filters,
    shuffle/timing controls, display controls, and current-media delete actions.
*   **Settings:** runtime configuration stored in `config.db3`, media/library
    paths, renderer options, MQTT, GPIO inputs, legacy YAML import, and
    maintenance actions.

Backend API documentation is available at:

```text
http://<picframe-host>:9000/docs
```

Live playback state, current media updates, command responses, and system
errors are synchronized through the `/ws/state` WebSocket.

#### Manual Remote Start Over SSH

On Raspberry Pi OS Lite, Picframe can be started manually from an SSH session
inside the same lightweight Wayland kiosk environment used by the optional
systemd service:

```bash
dbus-run-session -- cage -s -- bash -lc 'exec /home/pi/picframe_env/bin/picframe run --dir /home/pi/.picframe --port 9000'
```

If `cage` logs EGL messages such as `eglQueryDeviceStringEXT` with
`EGL_BAD_PARAMETER` but Picframe renders normally, the message is compositor
startup noise rather than a Picframe playback failure. On Raspberry Pi systems
where `labwc` is available, this equivalent launch is quieter:

```bash
dbus-run-session -- labwc --session 'bash -lc "exec /home/pi/picframe_env/bin/picframe run --dir /home/pi/.picframe --port 9000"'
```

For a development checkout using the repository virtual environment and a
separate development base directory:

```bash
dbus-run-session -- cage -s -- bash -lc 'cd /home/pi/Development/picframe && exec .venv/bin/python -m picframe.main run --dir /home/pi/.picframe-dev --port 9000'
dbus-run-session -- labwc --session 'bash -lc "cd /home/pi/Development/picframe && exec /home/pi/picframe_env/bin/python -m picframe.main run --dir /home/pi/.picframe-dev --port 9000"'
```

`--html-dir` can usually be omitted because it defaults to `<dir>/html`, which
is populated by `picframe init`. If a development base directory has not been
initialized with frontend assets yet, point it at the checkout copy:

```bash
dbus-run-session -- cage -s -- bash -lc 'cd /home/pi/Development/picframe && exec .venv/bin/python -m picframe.main run --dir /home/pi/.picframe-dev --port 9000 --html-dir /home/pi/Development/picframe/src/picframe/html'
```

Picframe enables `GST_V4L2_ENABLE_PROBE=1` for its GStreamer worker on
Raspberry Pi hardware when the variable is not already set, so it does not need
to be included in normal Picframe launch commands. Keep setting it explicitly
for standalone GStreamer validation commands.

### Settings UI

The Settings UI uses purpose-built editors instead of raw text fields for the
most important runtime configuration. Examples include host path pickers,
ordered text-overlay chips, token lists for extensions and CORS origins, color
pickers for matting, date pickers, sort-rule rows, a location-format builder
for geocoding, and keyboard shortcut capture.

Path pickers browse the Picframe host filesystem from the current user's home
directory only. They include shortcuts such as `~`, `~/Pictures`, `~/.picframe`,
and `~/DeletedPictures`. Attempts to browse outside the home directory,
including symlink escapes, are rejected by the backend. Media library paths may
be saved while missing so temporary NAS or mount outages do not force a reset.

Low-level options such as renderer resource paths, WebSocket rate limits, and
debug logging remain editable, but are grouped under collapsed Advanced areas.
Shader selection stores the shader path without `.fs` or `.vs`; Picframe loads
the matching shader files from that basename. Image metadata attributes and
image/video extensions are selected from fixed supported lists. Password fields
remain masked by default and include an eye button for temporary visibility.

### GPIO Hardware Inputs

Raspberry Pi GPIO inputs are configured from the Settings UI under **GPIO Inputs**.
These mappings are stored in `config.db3` as `hardware_inputs` and are separate
from the legacy-style keyboard/touch `peripherals` settings.

Pins use BCM numbering. Each input has a label, a device type, a BCM pin, and
one or more action mappings:

*   **Button** inputs support `pressed` and `released`.
*   **PIR** inputs support `motion_detected` and `no_motion`.

PIR inputs can also set a no-motion delay in seconds. A value of `0` runs the
`no_motion` command immediately. A value such as `900` waits 15 minutes before
running it; a new `motion_detected` event cancels the pending no-motion command.

The backend validates mappings before saving. Duplicate pins, unsupported input
types, invalid actions, and commands that require payloads are rejected. GPIO
commands are limited to payload-free commands such as playback, display power,
text overlay refresh/toggle, sleep/wake, reboot, shutdown, and stop.

Hardware input changes are applied at runtime after saving Settings. Picframe
does not need to be restarted for a changed GPIO mapping.

### Geocoding Configuration (`key_list`)

The `model.key_list` configuration parameter dictates how raw address data from the Nominatim reverse geocoding service is formatted into a human-readable location string.

In the Settings UI this is edited as **Location format**. Each visible part is
one output component, and the chips inside that part are fallback choices in
priority order. Presets such as Default, Detailed, City/Region/Country, and
City/Country write the same nested `model.key_list` structure shown below.

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

### Remote Shuffle Modes

Shuffle has two separate settings. `model.shuffle` turns shuffle on or off,
and `model.shuffle_mode` selects how shuffled playback is ordered.

*   **Standard** is the default mode and uses the normal random order.
*   **Fewer repeats** uses the existing `last_displayed` history in
    `media_cache.db3` to prefer items that have not been shown recently near
    the front of the next shuffled order.

Changing either setting through the Remote rebuilds playback immediately. The
selected mode is persisted, but it only affects playback while shuffle is
enabled. If `model.shuffle_mode` is missing or invalid, Picframe falls back to
`standard`.

### Home Assistant / MQTT

MQTT is optional. When `mqtt.use_mqtt` is enabled, the next-generation runtime
connects to the configured broker and publishes Home Assistant discovery
entities for playback, display power, brightness, selected configuration
values, current media state, and host reboot/shutdown.

Deleting current media from Home Assistant uses explicit target buttons:
**delete current / left**, **delete right**, and **delete both**. For single
media, only the current/left action deletes the active file; right/both are
reserved for portrait pairs and are rejected or ignored if the current display
is not a pair.

**Purge Media Database** and **Clear Image Cache** are not exposed over MQTT.
They remain Settings/UI and REST maintenance actions so generated-cache cleanup
and database purging stay deliberate.

### Network & Security Configuration

#### CORS (Cross-Origin Resource Sharing)
The API's CORS policy is managed via the `cors_allowed_origins` parameter within the `http` section of the configuration. This setting dictates which external domains are permitted to make requests to the Picframe API from a web browser.

*   **Type:** List of strings
*   **Default:** `["*"]` (Allows requests from any origin)
*   **Location:** `http.cors_allowed_origins`

**Security Note:** The default `["*"]` is permissive to ensure out-of-the-box compatibility on local networks. If you expose your Picframe API to the internet or want to strictly lock down access, you should update this setting via the Web UI or SQLite database to explicitly list your allowed domains (e.g., `["http://localhost:5173", "https://my-picframe.example.com"]`).

### Maintenance Actions

The Settings danger zone exposes maintenance actions that intentionally affect
different kinds of state:

*   **Purge Media Database** removes `media_cache.db3` rows for original media
    files that no longer exist on disk. It does not clear generated cache files
    and does not delete photos or videos.
*   **Clear Image Cache** removes generated artifacts under the managed runtime
    cache directory, including video transition frames. The next playback or
    indexing pass can regenerate those files when needed. It never deletes
    original media files.

Deleting the current media item from the Remote remains separate from both
maintenance actions; it moves the selected original media file to the
configured deleted-media location and removes that media row from
`media_cache.db3`.

Temporarily missing files are handled differently from user deletes. If a file
is unavailable during playback, for example because an NAS mount is temporarily
down, Picframe marks the row inactive and skips it. A later scan reactivates
and refreshes the row when the file exists again. Only **Purge Media Database**
hard-deletes rows for files that are still missing on disk.

Display statistics (`displayed_count` and `last_displayed`) are stored in
`media_cache.db3`, survive normal restarts, and are preserved when unchanged
or changed files are reindexed. Manually deleting `media_cache.db3` rebuilds
the media cache from scratch and resets those statistics.

When `model.portrait_pairs` is enabled, portrait image pairs are displayed as
one slideshow slot with two original image files. Videos are never paired and
always remain fullscreen. In Remote, pair metadata can be switched between the
left and right image. Deleting a portrait pair opens a choice to delete the
left image, the right image, or both.
Portrait-pair detection uses indexed image orientation metadata. During
unpublished next-gen development, deleting and rebuilding `media_cache.db3` is
acceptable after changing portrait-detection behavior.

Viewer matting settings apply during image rendering only. When
`viewer.mat_images` enables matting, Picframe loads the image with EXIF
orientation applied, optionally wraps single images or image-only portrait
pairs with the configured mat style, and then creates the pi3d texture. Videos
are never matted, original media files are never modified, and the current
next-gen matting path creates no persistent cache artifacts.

Video playback support depends on the host hardware, GStreamer plugins, and
display session. Picframe targets Raspberry Pi 5, Pi 4, Pi 3, Zero 2 W, and
Zero-class boards with model-aware H.264/HEVC hardware decode limits. The
official model envelopes and the current Raspberry Pi 4/labwc validation matrix
are recorded in [Video format validation](video-format-validation.md), including
known-good H.264/HEVC files and guarded HEVC Main10/HDR MOV files. The same
page also records VLC comparison results from issue #680. VLC is only a
diagnostic reference there; Picframe's next-generation runtime continues to use
GStreamer.

On Wayland, Picframe first tries to host video playback in a borderless GTK3
window using `gtkwaylandsink`. The GTK window is sized and positioned to match
the configured pi3d display rectangle (`viewer.display_x`, `viewer.display_y`,
`viewer.display_w`, and `viewer.display_h`) so the video surface covers the
same pixels as image rendering. If GTK, `gtkwaylandsink`, or exact window
geometry is unavailable, Picframe falls back to the existing `waylandsink`
render-rectangle path.

Video transition frames are generated during indexing/cache work, not at EOS
runtime. The first transition frame is the first decoded video frame. The final
transition frame is taken by seeking near the end of the video and decoding a
short tail window through EOS, which makes the cached last frame match the
actual video handoff more closely than sampling a fixed duration offset.

Hardware playback is selected only when the Raspberry Pi model is known to
support the codec at the stream resolution/framerate and GStreamer exposes a
matching V4L2 decoder. Unknown, unsupported, over-limit, or missing-decoder
paths are allowed to fall back to software only within
`viewer.max_software_decode_resolution`; larger files are skipped with an
`unsupported_media` warning so the slideshow can continue.

On Raspberry Pi, GStreamer may only expose V4L2 hardware decoder elements after
probing is enabled. Picframe enables this for its GStreamer worker on Pi
hardware. For standalone target validation outside Picframe, launch the
validation command with `GST_V4L2_ENABLE_PROBE=1`.

Manual SSH start examples are listed in [Manual Remote Start Over SSH](#manual-remote-start-over-ssh).

---

## Part 2: Extended Developer Guidelines & System Setup

This section defines the foundational structures and system permissions required for developing, testing, and deploying Picframe.

### Developer Architecture: Media Monitoring

Media monitoring follows the clean-architecture boundary used elsewhere in the
next-gen code. The core layer defines the media-monitor port and consumes
`FileChangeEvent` DTOs; watchdog is only the infrastructure implementation.

*   Core services depend on `IMediaMonitor`, not watchdog classes.
*   `WatchdogMediaMonitor` translates create, modify, delete, and move
    notifications into `FileChangeEvent`s.
*   Differential sync publishes core events directly for discovered media
    files; the indexer decides whether each file is new, changed, restored, or
    unchanged.
*   Runtime wiring belongs in the composition root (`main.py`).

### Developer Architecture: MQTT And Legacy Runtime Cleanup

Home Assistant MQTT support is implemented as an infrastructure adapter. It
uses the event bus for commands, the config repository for runtime settings,
and `StateTrackerService` / `ISystemStateQuery` for state snapshots. It must
not depend on legacy controller, model, viewer, or runtime modules.

The legacy query-parameter HTTP interface, VLC/SDL video runtime, old
controller/model/start entry path, and old pi3d menu/touch UI are not part of
the next-generation public runtime. FastAPI/WebSocket is the web control plane;
GStreamer is the video runtime; HAL adapters cover hardware input.

### Development Environment & System Setup

To develop, test, and deploy Picframe, specific system packages are required depending on the host OS. The provided `docs/user/install_picframe.sh` script automates this process, including dynamic hardware probing for optimal video playback.

#### Automated Hardware Probing and Video Acceleration

The installation script now includes intelligent hardware probing to ensure GStreamer utilizes the best available video decoding method:

1.  **Architecture Detection:** The script detects if it's running on ARM (Raspberry Pi) or x86/x86_64.
2.  **Virtual Machine Detection:** It checks if the environment is a Virtual Machine (using `systemd-detect-virt`).
3.  **Dynamic Dependency Installation:**
    *   **Raspberry Pi (ARM):** Installs `gstreamer1.0-gl` for GL presentation. V4L2 decoder elements are provided by the standard `gstreamer1.0-plugins-good` and `gstreamer1.0-plugins-bad` packages installed by the base dependency set.
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
sudo apt-get install -y \
  build-essential ca-certificates cage labwc dbus-user-session git locales \
  python3 python3-dev python3-gi python3-gst-1.0 python3-pip python3-venv sudo \
  libsdl2-dev libegl1-mesa-dev libgles2-mesa-dev \
  gir1.2-gst-plugins-base-1.0 gir1.2-gstreamer-1.0 gir1.2-gtk-3.0 mesa-utils \
  libheif1 libheif-dev libjpeg-dev libopenjp2-7 libtiff6 zlib1g-dev \
  wlr-randr ddcutil brightnessctl i2c-tools seatd \
  gstreamer1.0-tools gstreamer1.0-libav \
  gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
  gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly \
  gstreamer1.0-gl
```
*(Note: `gstreamer1.0-gl` supports GL presentation. Raspberry Pi V4L2 decoder elements come from the standard GStreamer plugin packages above, especially `gstreamer1.0-plugins-good` and `gstreamer1.0-plugins-bad`).*
`gir1.2-gtk-3.0` is required for Picframe's GTK-backed Wayland video handoff.

When using a Python virtual environment with Debian/Raspberry Pi OS
GStreamer bindings, create it with system site packages so `import gi`,
`Gst`, and `GstPbutils` are visible:

```bash
python3 -m venv --system-site-packages ~/picframe_env
```

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
# Add the following lines to /etc/sudoers (using visudo)
# Replace 'pi' with the actual username running the application
Cmnd_Alias PICFRAME_POWER = /usr/sbin/reboot, /sbin/reboot, /usr/sbin/shutdown -h now, /sbin/shutdown -h now, /usr/bin/systemctl reboot, /usr/bin/systemctl poweroff
pi ALL=(root) NOPASSWD: PICFRAME_POWER
```

Alternatively, you can dynamically create a drop-in file in `/etc/sudoers.d/` for the current user:
```bash
sudo tee /etc/sudoers.d/picframe-power >/dev/null <<EOF
# Managed by Picframe installer.
Cmnd_Alias PICFRAME_POWER = /usr/sbin/reboot, /sbin/reboot, /usr/sbin/shutdown -h now, /sbin/shutdown -h now, /usr/bin/systemctl reboot, /usr/bin/systemctl poweroff
$USER ALL=(root) NOPASSWD: PICFRAME_POWER
EOF
sudo visudo -cf /etc/sudoers.d/picframe-power
sudo chmod 0440 /etc/sudoers.d/picframe-power
```

Picframe runs these commands through `sudo -n`, so missing permissions fail
immediately instead of hanging on a password prompt.

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
