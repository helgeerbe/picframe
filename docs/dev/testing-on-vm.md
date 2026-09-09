# Testing Picframe on a QEMU aarch64 VM

Picframe targets Raspberry Pi / Wayland hardware, but most overlay and
compositor work can be developed and debugged on a QEMU aarch64 VM running
Ubuntu. This doc records the working setup: a **labwc** Wayland session (not
the default GNOME), the WebKitGTK worker socket timeout override needed under
software emulation, and the two biggest boot-latency fixes
(`xdg-desktop-portal` and KVM).

It is a developer convenience guide, not a supported deployment target.
Production runs on real Pi hardware.

## Why a VM?

- No Pi required for iterating on the touch overlay, plugin shell, labwc
  stacking, or the GStreamer video handoff.
- `virtio-gpu` gives a working GL/Wayland stack so pi3d and the GTK4 video host
  run under software decoding (`libav`) within the configured software limit.
- The same code path runs as on a Pi: `GDK_BACKEND=wayland`,
  `wlr-layer-shell`, out-of-process workers.

## 1. Create the VM (QEMU aarch64, Ubuntu Server)

Minimal Ubuntu Server ARM64 image, booted with `virtio-gpu-gl` so there is a
usable GL/Wayland surface:

```bash
qemu-system-aarch64 \
  -machine virt \
  -cpu cortex-a72 \
  -smp 4 -m 4096 \
  -drive file=ubuntu-24.04-server-arm64.img,if=virtio \
  -bios /usr/share/qemu-efi-aarch64/QEMU_EFI.fd \
  -device virtio-gpu-gl -display gtk,gl=on \
  -netdev user,id=net0 -device virtio-net-pci,netdev=net0
```

Install a desktop session on top of the server image (you need a Wayland
session + a display manager to log in graphically):

```bash
sudo apt update
sudo apt install --no-install-recommends ubuntu-desktop
```

> If you enable **KVM** (see §6), drop `-cpu cortex-a72` and use
> `-enable-kvm -cpu host` instead — the overlay worker timeout override in
> §4 becomes unnecessary.

## 2. Install labwc and pick the labwc session at login

Install the compositor plus the WebKitGTK / gtk4-layer-shell packages the
overlay needs:

```bash
sudo apt install labwc foot \
  gir1.2-webkit-6.0 gir1.2-gtk4layershell-1.0 libgtk4-layer-shell0 \
  fonts-noto-color-emoji
```

`labwc` ships `/usr/share/wayland-sessions/labwc.desktop`, so any display
manager (GDM, SDDM, LightDM) offers it as a session choice.

**At the graphical login screen, do not log into the default GNOME session.**
GNOME runs Mutter, which does **not** implement `wlr-layer-shell`, so the
touch overlay degrades to a plain `Gtk.Window` that renders behind the GTK4
video host during playback (clock hidden, input over video lost). Instead:

1. Enter your username.
2. Before typing the password, click the session/gear selector (⚙ in GDM,
   the session dropdown in SDDM/LightDM).
3. Choose **labwc** (sometimes shown as "Labwc").
4. Log in.

Verify the compositor advertises the protocols the overlay relies on:

```bash
wayland-info | grep -E 'zwlr_layer_shell_v1|zwp_linux_dmabuf_v1|wl_drm'
```

You should see `zwpr_layer_shell_v1` v4, `zwp_linux_dmabuf_v1` v4, and `wl_drm`.
(Install with `sudo apt install wayland-utils` if `wayland-info` is missing.)

Also confirm the gtk4-layer-shell runtime `.so` resolves (the overlay
`LD_PRELOAD`s `libgtk4-layer-shell.so.0` before `libwayland-client`):

```bash
ldconfig -p | grep libgtk4-layer-shell
```

## 3. Install picframe

```bash
sudo apt install git python3-venv python3-pip python3-gi \
  libgirepository1.0-dev libwebkitgtk-6.0-dev \
  libgstreamer1.0-dev gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
  gstreamer1.0-plugins-bad gstreamer1.0-libav
python3 -m venv ~/.venv
source ~/.venv/bin/activate
pip install -e .[dev]
picframe init
```

## 4. The WebKitGTK worker timeout (TCG software emulation)

This is the single most important VM-specific gotcha.

On real Pi hardware WebKitGTK boots in 1–3 s. Under QEMU **TCG software
emulation** (the default when `/dev/kvm` is not available to the guest), the
same boot takes ~2:20. The main process waits only `_WORKER_SOCKET_TIMEOUT_SECONDS`
(default `20.0`) for the worker to create its IPC socket, then kills it and
publishes a `webkit_unavailable` system error — so on a TCG VM the touch
overlay is silently disabled every time, even though labwc, the typelib, and
the runtime `.so` are all correct.

Raise the deadline with the environment variable (seconds, float):

```bash
export PICFRAME_OVERLAY_WORKER_SOCKET_TIMEOUT=180
picframe run
```

With `180` the worker finishes booting (~2:22) and the plugins appear. This
variable is documented in `docs/dev/architecture/overlay.md` §3 and
`docs/user/overlay.md` (Troubleshooting).

> The override is a crutch for emulation slowness. Enable KVM (§6) to make
> it unnecessary; on real hardware it is never needed.

## 5. Remove the 25 s xdg-desktop-portal stall

Even with the timeout raised, ~25 s of every overlay boot is a
`xdg-desktop-portal` D-Bus call timeout. Ubuntu ships only
`xdg-desktop-portal-gtk` (the GNOME backend); labwc is a wlroots compositor
and needs the wlroots backend:

```bash
sudo apt install xdg-desktop-portal-wlr
```

After this the portal call resolves immediately instead of timing out, which
is the biggest single boot-latency win on the VM (aside from KVM).

## 6. Enable KVM (best fix)

If the aarch64 host supports virtualization extensions, expose `/dev/kvm` to
the guest and boot with `-enable-kvm -cpu host`. WebKitGTK then boots in a few
seconds, the `PICFRAME_OVERLAY_WORKER_SOCKET_TIMEOUT` override becomes
unnecessary, and you can drop it. Keep the `xdg-desktop-portal-wlr` install
regardless — it is correct for labwc on any host.

## 7. Run picframe in the labwc session

labwc has no panel by default. Open a terminal (e.g. `foot`) or SSH in with
`WAYLAND_DISPLAY` exported, then:

```bash
export PICFRAME_OVERLAY_WORKER_SOCKET_TIMEOUT=180   # only under TCG
picframe run
```

To make picframe start with the session, add it to `~/.config/labwc/autostart`:

```bash
mkdir -p ~/.config/labwc
cat >> ~/.config/labwc/autostart <<'EOF'
PICFRAME_OVERLAY_WORKER_SOCKET_TIMEOUT=180 picframe run &
EOF
chmod +x ~/.config/labwc/autostart
```

(If you run picframe as a systemd user service, set the variable in the unit's
`Environment=` instead.)

## 8. Plugins appear then fade after a few seconds (not a bug)

The default `overlay.idle_hide_seconds: 5.0` (see
`src/picframe/config/default_config.yaml`) fades the overlay to transparent
after 5 s of inactivity in `auto_hide` mode. Any input wakes it. If you want
the plugins to stay visible while testing, either:

- set `display_mode: persistent` per plugin, or
- set `overlay.idle_hide_seconds: 0.0` (always visible).

Both are writable from the web UI (**Settings → Touch Overlay**) or
`config.db3`.

## 9. Verifying the overlay end-to-end

1. `overlay.enabled: true` (Settings → Touch Overlay, or `picframe init`).
2. `picframe init` copied built-in plugins to `~/.picframe/overlay-plugins/`.
3. Start picframe with the timeout override (TCG) or KVM.
4. Confirm the dock + active plugin render above the photo and capture input.
5. Start a video; the overlay fades to opacity 0 (video shows through) but
   stays on top — tap anywhere to bring it back.

If the overlay is created but the clock is invisible while photos play, you
are on a non-`wlr-layer-shell` compositor (e.g. you logged into GNOME/Mutter).
Log out and pick the **labwc** session (§2).
