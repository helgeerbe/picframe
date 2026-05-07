#!/bin/bash
# Picframe Automated Installation Script
# Target: Raspberry Pi OS Lite 64-bit (Trixie), Ubuntu/Debian

set -e

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

ACTUAL_HOME=$(eval echo ~$ACTUAL_USER)
PROJECT_ROOT=$(dirname $(dirname $(realpath $0)))

echo "======================================================="
echo "Starting Picframe installation for user: $ACTUAL_USER"
echo "Project Root: $PROJECT_ROOT"
echo "======================================================="

# 1. Install Base APT dependencies
echo "[1/6] Installing base system dependencies via apt..."
apt-get update
apt-get install -y \
    libsdl2-dev \
    libegl1-mesa-dev \
    libgles2-mesa-dev \
    wlr-randr \
    ddcutil \
    brightnessctl \
    i2c-tools \
    python3-pip \
    python3-venv \
    git \
    gstreamer1.0-libav \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad \
    gstreamer1.0-plugins-ugly \
    pciutils \
    lshw

# 2. Hardware Probing and Dynamic Dependency Installation
echo "[2/6] Probing hardware for optimal video decoding support..."

ARCH=$(uname -m)
IS_VM=false
if systemd-detect-virt -q; then
    IS_VM=true
    echo "  -> Detected Virtual Machine environment."
fi

HW_PACKAGES=""

if [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "armv7l" ]; then
    echo "  -> Detected ARM architecture (likely Raspberry Pi)."
    # Raspberry Pi specific hardware decoding (V4L2)
    HW_PACKAGES="gstreamer1.0-gl gstreamer1.0-v4l2"
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

# 3. Configure user privileges
echo "[3/6] Configuring user groups for hardware access..."
usermod -aG i2c "$ACTUAL_USER"
usermod -aG video "$ACTUAL_USER"
usermod -aG render "$ACTUAL_USER" || true # Add to render group for DRM/KMS access if it exists

# 4. Configure sudoers rules for reboot/shutdown
echo "[4/6] Configuring passwordless sudo for reboot and shutdown..."
SUDOERS_FILE="/etc/sudoers.d/picframe-power"
echo "$ACTUAL_USER ALL=(ALL) NOPASSWD: /sbin/reboot, /sbin/shutdown" > "$SUDOERS_FILE"
chmod 0440 "$SUDOERS_FILE"

# 5. Install picframe via pip in a virtual environment
echo "[5/6] Setting up Python virtual environment and installing picframe..."
VENV_DIR="$ACTUAL_HOME/picframe_env"

# Create venv as the actual user
sudo -u "$ACTUAL_USER" python3 -m venv "$VENV_DIR"

# Install the package (assuming the script is run from within the project repository)
if [ -f "$PROJECT_ROOT/pyproject.toml" ]; then
    echo "Found local project. Installing from $PROJECT_ROOT..."
    sudo -u "$ACTUAL_USER" "$VENV_DIR/bin/pip" install -e "$PROJECT_ROOT"
else
    echo "Local project not found. Installing from PyPI..."
    sudo -u "$ACTUAL_USER" "$VENV_DIR/bin/pip" install picframe
fi

# 6. Execute system initialization
echo "[6/6] Initializing Picframe environment..."
sudo -u "$ACTUAL_USER" "$VENV_DIR/bin/picframe" init --force

echo "======================================================="
echo "Installation and initialization complete!"
echo "Picframe has been installed in: $VENV_DIR"
echo "You can run picframe using: $VENV_DIR/bin/picframe run"
echo "Note: You may need to log out and log back in for group changes (i2c, video, render) to take effect."
echo "======================================================="
