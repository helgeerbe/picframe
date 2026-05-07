#!/bin/bash
# Picframe Automated Installation Script
# Target: Raspberry Pi OS Lite 64-bit (Trixie)

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

# 1. Install APT dependencies
echo "[1/5] Installing system dependencies via apt..."
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
    git

# 2. Configure user privileges
echo "[2/5] Configuring user groups for hardware access..."
usermod -aG i2c "$ACTUAL_USER"
usermod -aG video "$ACTUAL_USER"

# 3. Configure sudoers rules for reboot/shutdown
echo "[3/5] Configuring passwordless sudo for reboot and shutdown..."
SUDOERS_FILE="/etc/sudoers.d/picframe-power"
echo "$ACTUAL_USER ALL=(ALL) NOPASSWD: /sbin/reboot, /sbin/shutdown" > "$SUDOERS_FILE"
chmod 0440 "$SUDOERS_FILE"

# 4. Install picframe via pip in a virtual environment
echo "[4/5] Setting up Python virtual environment and installing picframe..."
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

# 5. Execute system initialization
echo "[5/5] Initializing Picframe environment..."
sudo -u "$ACTUAL_USER" "$VENV_DIR/bin/picframe" init --force

echo "======================================================="
echo "Installation and initialization complete!"
echo "Picframe has been installed in: $VENV_DIR"
echo "You can run picframe using: $VENV_DIR/bin/picframe run"
echo "Note: You may need to log out and log back in for group changes (i2c, video) to take effect."
echo "======================================================="
