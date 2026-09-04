#!/bin/bash
# Picframe Automated Installation Script
# Target: Raspberry Pi OS Lite 64-bit (Trixie), Ubuntu/Debian

set -e

INSTALL_SOURCE="${PICFRAME_INSTALL_SOURCE:-github}"
GITHUB_REPO="${PICFRAME_GITHUB_REPO:-helgeerbe/picframe}"
GITHUB_BRANCH="${PICFRAME_GITHUB_BRANCH:-main}"
LOCAL_PATH="${PICFRAME_LOCAL_PATH:-}"
PICFRAME_LOCALE="${PICFRAME_LOCALE:-}"
NON_INTERACTIVE=false
ENABLE_SERVICE="${PICFRAME_ENABLE_SERVICE:-ask}"
ENABLE_OVERLAY="${PICFRAME_ENABLE_OVERLAY:-ask}"
DISPLAY_MODE="${PICFRAME_DISPLAY_MODE:-labwc-kiosk}"

usage() {
    cat <<'EOF'
Usage: sudo ./install_picframe.sh [options]

Options:
  --source github|local|pypi   Install source (default: github)
  --repo OWNER/REPO            GitHub repository (default: helgeerbe/picframe)
  --branch BRANCH              GitHub branch or tag (default: main)
  --local-path PATH            Local checkout path for --source local
  --locale LOCALE              Picframe locale, for example en_US.UTF-8 or de_DE.UTF-8
  --enable-service             Create and enable a systemd service for boot startup
  --disable-service            Do not create a systemd service
  --enable-overlay             Install WebKitGTK touch overlay packages (default)
  --disable-overlay            Skip WebKitGTK touch overlay packages (low-perf platforms)
  --display-mode MODE          Service display mode: labwc-kiosk or
                                existing-wayland
                                (default: labwc-kiosk)
  -y, --yes                    Use defaults without interactive prompts
  -h, --help                   Show this help

Examples:
  sudo ./install_picframe.sh
  sudo ./install_picframe.sh --branch dev
  sudo ./install_picframe.sh --branch dev --enable-service
  sudo ./install_picframe.sh --enable-service --display-mode labwc-kiosk
  sudo ./install_picframe.sh --source local --local-path /home/pi/Development/picframe
  sudo ./install_picframe.sh --disable-overlay --source pypi
EOF
}

die() {
    echo "Error: $*" >&2
    exit 1
}

require_option_value() {
    local option="$1"
    local value="${2:-}"
    if [ -z "$value" ] || [[ "$value" == --* ]]; then
        usage >&2
        die "$option requires a value"
    fi
}

normalize_locale() {
    local value="${1:-}"
    value="${value%% *}"
    value="${value:-en_US.UTF-8}"
    printf '%s\n' "$value" | sed -E 's/\.utf-?8$/.utf8/I'
}

locale_gen_name() {
    local normalized
    normalized=$(normalize_locale "$1")
    printf '%s\n' "$normalized" | sed -E 's/\.utf8$/.UTF-8/I'
}

regex_escape() {
    printf '%s\n' "$1" | sed -E 's/[][\/.^$*+?{}()|]/\\&/g'
}

locale_is_installed() {
    local normalized="$1"
    locale -a | sed -E 's/\.utf-?8$/.utf8/I' | grep -Fxq "$normalized"
}

prompt_with_default() {
    local prompt="$1"
    local default_value="$2"
    local reply=""

    if [ "$NON_INTERACTIVE" = true ] || [ ! -t 0 ]; then
        printf '%s\n' "$default_value"
        return
    fi

    read -r -p "$prompt [$default_value]: " reply
    printf '%s\n' "${reply:-$default_value}"
}

prompt_yes_no() {
    local prompt="$1"
    local default_value="$2"
    local reply=""

    if [ "$NON_INTERACTIVE" = true ] || [ ! -t 0 ]; then
        printf '%s\n' "$default_value"
        return
    fi

    read -r -p "$prompt [$default_value]: " reply
    reply="${reply:-$default_value}"
    case "$reply" in
        y|Y|yes|YES|Yes) printf 'yes\n' ;;
        *) printf 'no\n' ;;
    esac
}

configure_systemd_service() {
    local service_file="/etc/systemd/system/picframe.service"
    local service_tmp
    local exec_start
    local labwc_path=""
    local labwc_config_dir=""

    case "$DISPLAY_MODE" in
        labwc-kiosk)
            labwc_path=$(command -v labwc || true)
            if [ -z "$labwc_path" ]; then
                die "labwc is required for --display-mode labwc-kiosk"
            fi
            labwc_config_dir="$ACTUAL_HOME/.picframe/labwc"
            configure_labwc_kiosk_config "$labwc_config_dir"
            exec_start="$labwc_path -C $labwc_config_dir --session \"$VENV_DIR/bin/picframe run\""
            ;;
        existing-wayland)
            exec_start="$VENV_DIR/bin/picframe run"
            ;;
    esac

    service_tmp=$(mktemp)
    cat > "$service_tmp" <<EOF
[Unit]
Description=Picframe
After=network-online.target systemd-user-sessions.service
Wants=network-online.target

[Service]
Type=simple
User=$ACTUAL_USER
Group=$ACTUAL_GROUP
WorkingDirectory=$ACTUAL_HOME
Environment=PICFRAME_DIR=$ACTUAL_HOME/.picframe
Environment=SDL_VIDEODRIVER=wayland
Environment=SDL_VIDEO_WAYLAND_WMCLASS=picframe-pi3d
Environment=SDL_VIDEO_X11_WMCLASS=picframe-pi3d
Environment=SDL_APP_ID=picframe-pi3d
Environment=XDG_RUNTIME_DIR=/run/picframe
RuntimeDirectory=picframe
RuntimeDirectoryMode=0700
ExecStart=$exec_start
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

    install -o root -g root -m 0644 "$service_tmp" "$service_file"
    rm -f "$service_tmp"
    systemctl daemon-reload
    systemctl enable picframe.service

    if [ "$DISPLAY_MODE" = "labwc-kiosk" ]; then
        systemctl enable --now seatd.service >/dev/null 2>&1 || true
    fi
}

configure_labwc_kiosk_config() {
    local labwc_config_dir="$1"
    local labwc_config_tmp

    install -d -o "$ACTUAL_USER" -g "$ACTUAL_GROUP" -m 0755 "$labwc_config_dir"
    labwc_config_tmp=$(mktemp)
    cat > "$labwc_config_tmp" <<'EOF'
<?xml version="1.0"?>
<labwc_config>
  <windowRules>
    <windowRule identifier="picframe-pi3d"
                serverDecoration="no"
                skipTaskbar="yes"
                skipWindowSwitcher="yes"
                fixedPosition="yes" />
    <windowRule title="picframe-pi3d"
                serverDecoration="no"
                skipTaskbar="yes"
                skipWindowSwitcher="yes"
                fixedPosition="yes" />
    <windowRule title="picframe-video"
                serverDecoration="no"
                skipTaskbar="yes"
                skipWindowSwitcher="yes"
                fixedPosition="yes" />
  </windowRules>
</labwc_config>
EOF
    install -o "$ACTUAL_USER" -g "$ACTUAL_GROUP" -m 0644 "$labwc_config_tmp" "$labwc_config_dir/rc.xml"
    rm -f "$labwc_config_tmp"
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --source)
            require_option_value "$1" "${2:-}"
            INSTALL_SOURCE="${2:-}"
            shift 2
            ;;
        --repo)
            require_option_value "$1" "${2:-}"
            GITHUB_REPO="${2:-}"
            shift 2
            ;;
        --branch)
            require_option_value "$1" "${2:-}"
            GITHUB_BRANCH="${2:-}"
            shift 2
            ;;
        --local-path)
            require_option_value "$1" "${2:-}"
            LOCAL_PATH="${2:-}"
            shift 2
            ;;
        --locale)
            require_option_value "$1" "${2:-}"
            PICFRAME_LOCALE="${2:-}"
            shift 2
            ;;
        --enable-service)
            ENABLE_SERVICE=true
            shift
            ;;
        --disable-service)
            ENABLE_SERVICE=false
            shift
            ;;
        --enable-overlay)
            ENABLE_OVERLAY=true
            shift
            ;;
        --disable-overlay)
            ENABLE_OVERLAY=false
            shift
            ;;
        --display-mode)
            require_option_value "$1" "${2:-}"
            DISPLAY_MODE="${2:-}"
            shift 2
            ;;
        -y|--yes)
            NON_INTERACTIVE=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            usage >&2
            die "unknown option: $1"
            ;;
    esac
done

case "$INSTALL_SOURCE" in
    github|local|pypi) ;;
    *) die "--source must be one of: github, local, pypi" ;;
esac

if [ -z "$GITHUB_REPO" ]; then
    die "--repo must not be empty"
fi

if [ -z "$GITHUB_BRANCH" ]; then
    die "--branch must not be empty"
fi

case "$ENABLE_SERVICE" in
    ask|true|false) ;;
    *) die "PICFRAME_ENABLE_SERVICE must be ask, true, or false" ;;
esac

case "$ENABLE_OVERLAY" in
    ask|true|false) ;;
    *) die "PICFRAME_ENABLE_OVERLAY must be ask, true, or false" ;;
esac

case "$DISPLAY_MODE" in
    labwc-kiosk|existing-wayland) ;;
    *) die "--display-mode must be one of: labwc-kiosk, existing-wayland" ;;
esac

# Ensure script is run as root
if [ "$EUID" -ne 0 ]; then
  echo "Error: Please run this script as root (e.g., using sudo ./install_picframe.sh)."
  exit 1
fi

# Determine the actual user running the script
if [ -n "$SUDO_USER" ]; then
    ACTUAL_USER="$SUDO_USER"
else
    echo "Error: Could not determine the actual user. Please run using sudo from your standard user account."
    exit 1
fi

ACTUAL_HOME=$(eval echo ~"$ACTUAL_USER")
ACTUAL_GROUP=$(id -gn "$ACTUAL_USER")
SCRIPT_PATH=$(realpath "$0")
SCRIPT_DIR=$(dirname "$SCRIPT_PATH")
PROJECT_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
if [ ! -f "$PROJECT_ROOT/pyproject.toml" ]; then
    PROJECT_ROOT=""
fi

if [ "$NON_INTERACTIVE" = false ] && [ -t 0 ]; then
    INSTALL_SOURCE=$(prompt_with_default "Install source (github/local/pypi)" "$INSTALL_SOURCE")
    case "$INSTALL_SOURCE" in
        github|local|pypi) ;;
        *) die "install source must be one of: github, local, pypi" ;;
    esac

    if [ "$INSTALL_SOURCE" = "github" ]; then
        GITHUB_REPO=$(prompt_with_default "GitHub repository" "$GITHUB_REPO")
        GITHUB_BRANCH=$(prompt_with_default "GitHub branch or tag" "$GITHUB_BRANCH")
    elif [ "$INSTALL_SOURCE" = "local" ]; then
        LOCAL_DEFAULT="${PROJECT_ROOT:-$ACTUAL_HOME/picframe}"
        LOCAL_PATH=$(prompt_with_default "Local checkout path" "${LOCAL_PATH:-$LOCAL_DEFAULT}")
    fi

    if [ "$ENABLE_SERVICE" = "ask" ]; then
        ENABLE_SERVICE=$(prompt_yes_no "Create and enable systemd boot service?" "no")
        if [ "$ENABLE_SERVICE" = "yes" ]; then
            ENABLE_SERVICE=true
        else
            ENABLE_SERVICE=false
        fi
    fi

    if [ "$ENABLE_OVERLAY" = "ask" ]; then
        ENABLE_OVERLAY=$(prompt_yes_no "Install WebKitGTK touch overlay packages?" "yes")
        if [ "$ENABLE_OVERLAY" = "yes" ]; then
            ENABLE_OVERLAY=true
        else
            ENABLE_OVERLAY=false
        fi
    fi
fi

if [ "$ENABLE_SERVICE" = "ask" ]; then
    ENABLE_SERVICE=false
fi

if [ "$ENABLE_OVERLAY" = "ask" ]; then
    ENABLE_OVERLAY=true
fi

if [ "$INSTALL_SOURCE" = "local" ] && [ -z "$LOCAL_PATH" ]; then
    if [ -n "$PROJECT_ROOT" ]; then
        LOCAL_PATH="$PROJECT_ROOT"
    else
        die "--local-path is required when --source local is used outside a checkout"
    fi
fi

echo "======================================================="
echo "Starting Picframe installation for user: $ACTUAL_USER"
echo "Install source: $INSTALL_SOURCE"
if [ "$INSTALL_SOURCE" = "github" ]; then
    echo "GitHub repository: $GITHUB_REPO"
    echo "GitHub branch/tag: $GITHUB_BRANCH"
elif [ "$INSTALL_SOURCE" = "local" ]; then
    echo "Local checkout: $LOCAL_PATH"
fi
echo "Systemd boot service: $ENABLE_SERVICE"
if [ "$ENABLE_SERVICE" = true ]; then
    echo "Service display mode: $DISPLAY_MODE"
fi
echo "Touch overlay packages: $ENABLE_OVERLAY"
echo "======================================================="

# 1. Install Base APT dependencies
echo "[1/7] Installing base system dependencies via apt..."
apt-get update
apt-get install -y \
    build-essential \
    ca-certificates \
    labwc \
    dbus-user-session \
    libsdl2-dev \
    libegl1-mesa-dev \
    libgles2-mesa-dev \
    gir1.2-gst-plugins-base-1.0 \
    gir1.2-gstreamer-1.0 \
    gir1.2-gtk-4.0 \
    libheif1 \
    libheif-dev \
    libjpeg-dev \
    libopenjp2-7 \
    libtiff6 \
    locales \
    mesa-utils \
    pkg-config \
    wlr-randr \
    ddcutil \
    brightnessctl \
    i2c-tools \
    python3 \
    python3-dev \
    python3-gi \
    python3-gst-1.0 \
    python3-pip \
    python3-venv \
    seatd \
    git \
    sudo \
    zlib1g-dev \
    ffmpeg \
    gstreamer1.0-libav \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad \
    gstreamer1.0-plugins-ugly \
    gstreamer1.0-gtk4 \
    gstreamer1.0-tools \
    pciutils \
    lshw

# 2. Configure locale
echo "[2/7] Configuring Picframe locale..."
if [ -z "$PICFRAME_LOCALE" ]; then
    DEFAULT_LOCALE=$(normalize_locale "${LANG:-en_US.UTF-8}")
    case "$DEFAULT_LOCALE" in
        C|POSIX|C.utf8) DEFAULT_LOCALE="en_US.utf8" ;;
    esac
    PICFRAME_LOCALE=$(prompt_with_default "Picframe locale" "$DEFAULT_LOCALE")
fi
PICFRAME_LOCALE=$(normalize_locale "$PICFRAME_LOCALE")
LOCALE_GEN_NAME=$(locale_gen_name "$PICFRAME_LOCALE")

if locale_is_installed "$PICFRAME_LOCALE"; then
    echo "  -> Locale already installed: $PICFRAME_LOCALE"
else
    echo "  -> Locale $PICFRAME_LOCALE is not installed. Generating $LOCALE_GEN_NAME..."
    LOCALE_GEN_REGEX=$(regex_escape "$LOCALE_GEN_NAME")
    if grep -Eq "^#?[[:space:]]*$LOCALE_GEN_REGEX[[:space:]]+UTF-8" /etc/locale.gen; then
        sed -i -E \
            "s/^#?[[:space:]]*($LOCALE_GEN_REGEX[[:space:]]+UTF-8)/\1/" \
            /etc/locale.gen
    else
        echo "$LOCALE_GEN_NAME UTF-8" >> /etc/locale.gen
    fi
    locale-gen "$LOCALE_GEN_NAME"
    if ! locale_is_installed "$PICFRAME_LOCALE"; then
        die "failed to generate locale $PICFRAME_LOCALE"
    fi
fi

# 3. Hardware Probing and Dynamic Dependency Installation
echo "[3/7] Probing hardware for optimal video decoding support..."

ARCH=$(uname -m)
IS_VM=false
if systemd-detect-virt -q; then
    IS_VM=true
    echo "  -> Detected Virtual Machine environment."
fi

HW_PACKAGES=""

if [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "armv7l" ]; then
    echo "  -> Detected ARM architecture (likely Raspberry Pi)."
    # Raspberry Pi V4L2 decoder elements are provided by the base
    # gstreamer1.0-plugins-good/bad packages installed above.
    HW_PACKAGES="gstreamer1.0-gl"
else
    echo "  -> Detected x86/x86_64 architecture."
    if [ "$IS_VM" = true ]; then
        echo "  -> Running in a VM. Hardware acceleration might be limited unless GPU passthrough is configured."
        # Install VA-API anyway, as some VMs support virtio-gpu or similar
        HW_PACKAGES="gstreamer1.0-vaapi vainfo"
    else
        # Bare-metal Linux: Probe for GPU vendor
        if lspci | grep -i "vga\|3d\|display" | grep -qi "intel"; then
            echo "  -> Detected Intel GPU."
            HW_PACKAGES="gstreamer1.0-vaapi intel-media-va-driver-non-free vainfo"
        elif lspci | grep -i "vga\|3d\|display" | grep -qi "amd\|radeon"; then
            echo "  -> Detected AMD GPU."
            HW_PACKAGES="gstreamer1.0-vaapi mesa-va-drivers vainfo"
        elif lspci | grep -i "vga\|3d\|display" | grep -qi "nvidia"; then
            echo "  -> Detected NVIDIA GPU."
            # NVIDIA typically uses VDPAU or NVDEC, but VA-API wrapper is common
            HW_PACKAGES="gstreamer1.0-vaapi vdpau-driver-all vainfo"
        else
            echo "  -> Unknown GPU vendor. Installing generic VA-API support."
            HW_PACKAGES="gstreamer1.0-vaapi vainfo"
        fi
    fi
fi

if [ -n "$HW_PACKAGES" ]; then
    echo "  -> Installing hardware acceleration packages: $HW_PACKAGES"
    apt-get install -y $HW_PACKAGES
else
    echo "  -> No specific hardware acceleration packages identified."
fi

# Optional WebKitGTK touch overlay (#739). Installed by default; the runtime
# overlay stays off until `overlay.enabled` is set, but the packages are pulled
# in so the feature works out of the box on Trixie/Ubuntu 24.04+. Soft-fail so
# older OS releases (e.g. Bookworm, which lacks gir1.2-webkit-6.0) still install.
if [ "$ENABLE_OVERLAY" = true ]; then
    echo "  -> Installing WebKitGTK touch overlay packages..."
    if apt-get install -y gir1.2-webkit-6.0 gir1.2-gtk4layershell-1.0 libgtk4-layer-shell0 fonts-noto-color-emoji; then
        echo "  -> WebKitGTK overlay packages installed."
    else
        echo "  -> Warning: overlay packages unavailable on this OS release" >&2
        echo "     (need Raspberry Pi OS Trixie / Ubuntu 24.04+)." >&2
        echo "     Picframe will run with the touch overlay disabled." >&2
        ENABLE_OVERLAY=false
    fi
else
    echo "  -> WebKitGTK overlay packages skipped. Install later with:"
    echo "     sudo apt install gir1.2-webkit-6.0 gir1.2-gtk4layershell-1.0 libgtk4-layer-shell0 fonts-noto-color-emoji"
fi

# 4. Configure user privileges
echo "[4/7] Configuring user groups for hardware access..."
usermod -aG i2c "$ACTUAL_USER"
usermod -aG video "$ACTUAL_USER"
usermod -aG render "$ACTUAL_USER" || true # Add to render group for DRM/KMS access if it exists
usermod -aG input "$ACTUAL_USER" || true # Hardware/event access on some Lite installs
usermod -aG seat "$ACTUAL_USER" || true # seatd access for kiosk Wayland sessions if present

# 5. Configure sudoers rules for reboot/shutdown and Picframe service restart
echo "[5/7] Configuring passwordless sudo for reboot and shutdown..."
SUDOERS_FILE="/etc/sudoers.d/picframe-power"
SUDOERS_TMP=$(mktemp)
cat > "$SUDOERS_TMP" <<EOF
# Managed by Picframe installer.
# Allows only Picframe host power commands without an interactive password prompt.
Cmnd_Alias PICFRAME_POWER = /usr/sbin/reboot, /sbin/reboot, /usr/sbin/shutdown -h now, /sbin/shutdown -h now, /usr/bin/systemctl reboot, /usr/bin/systemctl poweroff, /usr/bin/systemctl restart picframe.service, /bin/systemctl restart picframe.service
$ACTUAL_USER ALL=(root) NOPASSWD: PICFRAME_POWER
EOF

if ! visudo -cf "$SUDOERS_TMP"; then
    rm -f "$SUDOERS_TMP"
    echo "Error: generated Picframe sudoers file failed validation." >&2
    exit 1
fi
install -o root -g root -m 0440 "$SUDOERS_TMP" "$SUDOERS_FILE"
rm -f "$SUDOERS_TMP"

REBOOT_PATH=$(command -v reboot || true)
SHUTDOWN_PATH=$(command -v shutdown || true)
if [ -n "$REBOOT_PATH" ]; then
    sudo -u "$ACTUAL_USER" sudo -n -l -- "$REBOOT_PATH" >/dev/null
fi
if [ -n "$SHUTDOWN_PATH" ]; then
    sudo -u "$ACTUAL_USER" sudo -n -l -- "$SHUTDOWN_PATH" -h now >/dev/null
fi

# 6. Install picframe via pip in a virtual environment
echo "[6/7] Setting up Python virtual environment and installing picframe..."
VENV_DIR="$ACTUAL_HOME/picframe_env"

# Create venv as the actual user. GObject Introspection bindings are provided
# by Debian packages, so the venv must see system site packages.
sudo -u "$ACTUAL_USER" python3 -m venv --system-site-packages "$VENV_DIR"
sudo -u "$ACTUAL_USER" "$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel

echo "  -> Verifying Python GObject/GStreamer bindings..."
sudo -u "$ACTUAL_USER" "$VENV_DIR/bin/python" - <<'PY'
import gi

gi.require_version("Gst", "1.0")
gi.require_version("GstPbutils", "1.0")
from gi.repository import Gst, GstPbutils  # noqa: F401
PY

if [ "$ENABLE_OVERLAY" = true ]; then
    echo "  -> Verifying WebKitGTK bindings..."
    if sudo -u "$ACTUAL_USER" "$VENV_DIR/bin/python" - <<'PY'
import ctypes

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("WebKit", "6.0")
from gi.repository import WebKit  # noqa: F401
# The gtk4-layer-shell *typelib* imports without the runtime shared library:
# GObject-introspection dlopens libgtk4-layer-shell.so.0 lazily on first call,
# not at import. That mismatch (typelib present, .so absent) is the exact cause
# of the overlay rendering invisibly behind pi3d. So when the typelib is present
# we also probe the runtime .so directly and fail the verification if missing.
try:
    gi.require_version("Gtk4LayerShell", "1.0")
    from gi.repository import Gtk4LayerShell  # noqa: F401
    ctypes.CDLL("libgtk4-layer-shell.so.0")
except (ImportError, ValueError):
    pass  # gir1.2-gtk4layershell-1.0 optional; worker falls back to a plain window
except OSError as exc:
    raise SystemExit(f"libgtk4-layer-shell.so.0 not found: {exc}")
PY
    then
        echo "  -> WebKitGTK bindings verified (layer-shell runtime present)."
    else
        echo "  -> Warning: WebKitGTK/layer-shell runtime missing; overlay will stay disabled." >&2
        echo "     Install: sudo apt install gir1.2-webkit-6.0 gir1.2-gtk4layershell-1.0 libgtk4-layer-shell0" >&2
    fi
fi

case "$INSTALL_SOURCE" in
    github)
        GITHUB_URL="https://github.com/$GITHUB_REPO.git"
        echo "  -> Validating GitHub branch/tag: $GITHUB_URL@$GITHUB_BRANCH"
        if ! git ls-remote --exit-code --heads "$GITHUB_URL" "$GITHUB_BRANCH" >/dev/null; then
            if ! git ls-remote --exit-code --tags "$GITHUB_URL" "$GITHUB_BRANCH" >/dev/null; then
                die "GitHub branch or tag not found: $GITHUB_REPO@$GITHUB_BRANCH"
            fi
        fi
        echo "  -> Installing Picframe from GitHub: $GITHUB_REPO@$GITHUB_BRANCH"
        sudo -u "$ACTUAL_USER" "$VENV_DIR/bin/pip" install \
            "git+$GITHUB_URL@$GITHUB_BRANCH"
        ;;
    local)
        LOCAL_PATH=$(realpath "$LOCAL_PATH")
        if [ ! -f "$LOCAL_PATH/pyproject.toml" ]; then
            die "local checkout does not contain pyproject.toml: $LOCAL_PATH"
        fi
        echo "  -> Installing Picframe from local checkout: $LOCAL_PATH"
        sudo -u "$ACTUAL_USER" "$VENV_DIR/bin/pip" install -e "$LOCAL_PATH"
        ;;
    pypi)
        echo "  -> Installing Picframe from PyPI"
        sudo -u "$ACTUAL_USER" "$VENV_DIR/bin/pip" install picframe
        ;;
esac

# 7. Execute system initialization
echo "[7/7] Initializing Picframe environment..."
sudo -u "$ACTUAL_USER" "$VENV_DIR/bin/picframe" init --force

CONFIG_DB_PATH="$ACTUAL_HOME/.picframe/data/config.db3"
echo "  -> Storing Picframe locale in config: $PICFRAME_LOCALE"
sudo -u "$ACTUAL_USER" "$VENV_DIR/bin/python" - "$CONFIG_DB_PATH" "$PICFRAME_LOCALE" <<'PY'
import sys

from picframe.core.repositories.sqlite_config import SQLiteConfigRepository

repo = SQLiteConfigRepository(sys.argv[1])
try:
    repo.set_app_config("model.locale", sys.argv[2])
finally:
    repo.close()
PY

if [ "$ENABLE_SERVICE" = true ]; then
    echo "  -> Creating and enabling systemd service: picframe.service"
    configure_systemd_service
fi

echo "======================================================="
echo "Installation and initialization complete!"
echo "Picframe has been installed in: $VENV_DIR"
echo "Picframe locale: $PICFRAME_LOCALE"
echo "You can run picframe using: $VENV_DIR/bin/picframe run"
if [ "$ENABLE_SERVICE" = true ]; then
    echo "Picframe service enabled: systemctl status picframe.service"
    echo "Start now with: sudo systemctl start picframe.service"
fi
if [ "$ENABLE_OVERLAY" = true ]; then
    echo "Touch overlay packages installed. Enable at runtime by setting overlay.enabled = true."
else
    echo "Touch overlay packages skipped. To enable later: sudo apt install gir1.2-webkit-6.0 gir1.2-gtk4layershell-1.0 libgtk4-layer-shell0 fonts-noto-color-emoji"
fi
echo "Note: You may need to log out and log back in for group changes (i2c, video, render, input, seat) to take effect."
echo "======================================================="
