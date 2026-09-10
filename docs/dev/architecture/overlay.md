# Architecture: WebKitGTK Touch Overlay + Plugin System (#739)

Status: developer architecture document for the next-gen overlay. Keep aligned
with `src/picframe/core/{models,ports,renderers}`, `src/picframe/infrastructure/overlay/`,
`src/picframe/overlay_plugins/`, and `frontend/src/overlay/`. Issue #739 is the
authoritative task tracker; this document records the design decisions and the
data/control flow that survives a reset.

## 1. Goal & constraints

A transparent, pointer- and keyboard-enabled HTML overlay sits on top of the
pi3d photo (and above the GTK4 video surface) using **WebKitGTK embedded in a
GTK4 Wayland window**, with a **plugin architecture** so users can drop in their
own widgets (clock, weather, photo metadata + map, custom). It fills the gap
left by the removed pygame touch interface and supersedes the Electron-based
`picframe-overlay` with a lighter, **out-of-process**, event-bus-integrated
equivalent.

Non-negotiables (from the project rules):

- **Wayland only.** X11 is not a target.
- **The main process stays GTK/WebKit-free.** The browser engine runs in its
  own subprocess, mirroring the `gst_worker.py` GStreamer worker, because
  WebKitGTK is a heavy native stack that can crash or leak. A crash/leak is
  confined to the overlay surface and never takes down the frame.
- **The overlay is always present and always the input surface.** "Hide" means
  opacity 0 (transparent), not withdrawn — the Wayland surface stays on top and
  keeps capturing input so any touch/keyboard/mouse event wakes it back up.
  (This stacking requires a `wlr-layer-shell` compositor such as labwc; the
  fallback on non-layer-shell compositors does not stay on top — see §10.)
- **User config is persistent (`config.db3`); plugin code is stateless.**
  Per-plugin user values live under `overlay.plugin_config.<id>.*`, never inside
  the plugin directory, so a plugin dir is safe to update/replace without
  clobbering user values.

The feature is gated behind `overlay.enabled: false` by default and degrades
gracefully when WebKitGTK is absent, so incomplete phases never block the rest
of picframe.

## 2. Runtime component diagram

```
Main process (no GTK/WebKit)
  Event Bus ──OverlayConfigChangedEvent──▶ WebKitOverlayRenderer (IPC client)
  Event Bus ──RenderCommand (video reveal)─▶  (drives opacity 0/1)
  Event Bus ◀──InputEvent (republished)─────┐
                                            │
                              /tmp/picframe_overlay_<pid>.sock  (AF_UNIX, newline JSON)
                                            │
                                            ▼
Overlay subprocess (own process, GLib MainLoop + WebKitGTK)
  overlay_worker.py ──▶ WebView (transparent wlr-layer-shell Wayland surface)
                            │  JS bridge (window.picframe) — bidirectional
                            │  loads shell via file://  (plugins via file://)
                            └──▶ ws://localhost:<port>/ws/state  (live state, like the SPA)

Frontend SPA (separate Vite build → src/picframe/html/overlay/)
  shell.ts ─▶ InputRouter (pointer + keyboard) ─▶ bridge.sendAction(action)
          ─▶ Dock (plugin icons + active plugin iframe)
          ─▶ StateClient (/ws/state) ─▶ onMedia ─▶ dock.postToActivePlugin({picframe:media})
```

## 3. Process model (out-of-process, mirroring gst_worker.py)

The overlay runs in its **own process** (`overlay_worker.py`), spawned via
`subprocess.Popen` from the main process. The main process contains no
GTK/WebKit; the in-process `WebKitOverlayRenderer` is a thin IPC client (like
`GstVideoRenderer`) that talks to the worker over a Unix-domain socket.

- **`src/picframe/core/renderers/webkit_overlay_renderer.py`** —
  `WebKitOverlayRenderer(IOverlayController)`: spawns the worker with
  `GDK_BACKEND=wayland`, opens an `AF_UNIX` socket, runs a listener thread that
  republishes worker `InputEvent`s as `CommandEvent`s on the event bus,
  subscribes to `OverlayConfigChangedEvent` (forward `SetConfig`) and
  `RenderCommand` (video reveal → opacity). `_probe_webkit()` imports `gi` and
  tries `WebKit 6.0` (GTK4) then `WebKit2 4.1` (GTK3); if neither imports,
  `is_available()` returns `False` and `start()` publishes a
  `SystemErrorEvent(code="webkit_unavailable")` instead of spawning.
- **`src/picframe/infrastructure/overlay/overlay_worker.py`** — the worker:
  guarded `gi`/Gtk/WebKit import, GLib `MainLoop` + `WebKit.WebView`, transparent
  `wlr-layer-shell` surface (falls back to a plain borderless `Gtk.Window`,
  which is unsupported on non-layer-shell compositors — see §10),
  `window.picframe` JS bridge, GTK-free IPC plumbing (`handle_command`/`_serve`)
  that is unit-tested headless. `main()` is the subprocess entry point.

### Worker socket-connect timeout

After spawning the worker, the renderer waits for the subprocess to create its
`AF_UNIX` IPC socket file — the point at which `Gtk.init` + WebKitGTK have
finished booting in the worker. `_WORKER_SOCKET_TIMEOUT_SECONDS` bounds this
wait; the default is `20.0` seconds, which is ample on real Raspberry Pi
hardware (WebKitGTK boots in 1–3 s). If the socket does not appear in time
the renderer raises a `RuntimeError`, publishes a `webkit_unavailable`
`SystemErrorEvent`, and picframe continues without the overlay.

The deadline is overridable for slow environments via the
`PICFRAME_OVERLAY_WORKER_SOCKET_TIMEOUT` environment variable (seconds, float):

```bash
PICFRAME_OVERLAY_WORKER_SOCKET_TIMEOUT=180 picframe run
```

This is needed under **QEMU TCG software emulation** (no `/dev/kvm`), where
WebKitGTK boot takes ~2:20 instead of a few seconds and the 20 s default kills
the worker before it finishes initializing. On real hardware, or a VM with KVM
enabled, the override is unnecessary. See `docs/dev/testing-on-vm.md`.

## 4. IPC protocol

`src/picframe/core/renderers/overlay_ipc.py` mirrors
`picframe.core.renderers.ipc_protocol` (the GStreamer worker protocol). All
messages are **frozen dataclasses** with a `type` discriminator field so
`parse_overlay_ipc_message()` rebuilds the right subclass. Serialization is
newline-delimited JSON over the Unix-domain socket.

Commands (Main → Worker):

| Message | Fields | Purpose |
|---|---|---|
| `SetOpacityCommand` | `opacity: float` | 0.0 transparent / 1.0 opaque |
| `SetConfigCommand` | `config: dict` | Apply merged `overlay` config live (no restart) |
| `ReloadCommand` | — | Re-scan plugins / reload shell after a change |
| `ShutdownCommand` | — | Clean worker shutdown |

Events (Worker → Main):

| Message | Fields | Purpose |
|---|---|---|
| `ReadyEvent` | — | Worker finished initializing the surface |
| `InputEvent` | `action: str` | `prev`/`next`/`toggle` → translated to `Command` |
| `OverlayErrorEvent` | `details: str`, `code: str?` | e.g. WebKitGTK init failure |
| `VisiblePluginsChangedEvent` | `visible_plugins: tuple[str, ...]` | Dock toggle changed the expanded set → renderer republishes as `CommandEvent(SET_CONFIG, {overlay: {visible_plugins}})` (#765) |
| `OnScreenPluginsChangedEvent` | `on_screen_plugins: tuple[str, ...]` | On-screen (runtime) visibility changed (auto-hide fade/wake/`media_change` re-arm/toggle) → renderer republishes as `OverlayVisibilityChangedEvent` (runtime channel, **not** persisted) so the Remote tab tile highlights mirror the dock icon (#766) |

`parse_overlay_ipc_message()` returns `None` for malformed JSON or unknown
types so a bad line from the worker never crashes the listener. Input actions
map to playback `Command`s via `_command_for_input_action()`:
`prev`→`PREV`, `next`→`NEXT`, `toggle`→`PLAY`, `stop`→`STOP` (#740).

## 5. Config & plugin storage

The `overlay` section lives in `src/picframe/config/default_config.yaml` and
is modeled by the Pydantic `OverlayConfig` on `AppConfig`
(`src/picframe/api/models.py`). This model is the single blocking prerequisite
for the feature: Pydantic v2 `extra='ignore'` silently drops unknown YAML keys,
so an `overlay` section absent from the schema would be dropped entirely during
`picframe init` seeding.

```yaml
overlay:
  enabled: false
  backend: webkit
  plugin_dir: ~/.picframe/overlay-plugins
  enabled_plugins: [clock, meta]
  visible_plugin: clock          # null = dock only
  display_mode: auto_hide        # persistent | auto_hide
  enabled_input_types: [touch, mouse, keyboard]
  idle_hide_seconds: 5.0
  transparent: true
  plugin_config: {}              # overlay.plugin_config.<id>.* per plugin
```

`ConfigService` reuses the `hardware_inputs` flatten/unflatten pattern
(`delete_app_config_prefix("overlay")` + re-write; `overlay` is on the
`get_nested_config` whitelist) and publishes an `OverlayConfigChangedEvent` on
every `overlay` write — distinct from the unrelated `RENDER_UPDATE_OVERLAY`
constant (the pi3d text/clock overlay). **Per-plugin user values persist in
`config.db3` under `overlay.plugin_config.<id>.*`** (flat dotted keys,
JSON-encoded), never inside the plugin directory. Effective config = manifest
defaults ← db overrides.

### Visible-plugins persistence (#765)

`overlay.visible_plugins` (a list of plugin ids expanded on screen; empty =
dock only) is the **single source of truth** for which panels are expanded,
shared by the touch overlay dock and the Remote/Appearance web tabs. Both UIs
write it through the **same** `CommandEvent(SET_CONFIG, {overlay:
{visible_plugins}})` path, so a toggle from either side persists to
`config.db3` and both refresh through the resulting `OverlayConfigChangedEvent`
round-trip — surviving `media_change` and restarts.

- **Web tabs** (`OverlayPanel.vue` / `OverlayAppearanceSection.vue`) call
  `configStore.saveWorkflowConfig({ overlay: { visible_plugins } })`, which
  hits `PUT /api/workflow-config` → `ConfigService` → `CommandEvent(SET_CONFIG)`.
- **Touch overlay dock** (`dock.ts`) toggles optimistically, then the shell's
  `onVisiblePluginsChange` callback calls the JS bridge `setVisiblePlugins(ids)`
  (`bridge.ts` → `{ action: "__set_visible_plugins", plugins: [...] }`). The
  worker sanitizes the payload (non-string entries dropped; missing/non-list
  `plugins` → empty tuple) and emits a `VisiblePluginsChangedEvent`. The
  renderer republishes it as the exact `CommandEvent(SET_CONFIG, {overlay:
  {visible_plugins}})` the REST endpoint publishes, so ConfigService persists
  it and the `OverlayConfigChangedEvent` reconciles the dock's optimistic update.
- **`media_change` auto-show** (`dock.ts` `showPluginIdle`) only expands a
  plugin while it remains in `visible_plugins`; collapsing a plugin (now
  persisted) keeps it collapsed across subsequent photo changes until the user
  expands it again — matching the remote-tab semantics.

### On-screen (runtime) visibility — `OverlayVisibilityChangedEvent` (#766)

`overlay.visible_plugins` is the **persisted** expanded set, but auto-hide is
a **transient** client-side CSS fade (`pf-plugin-panel--idle`) that never
writes `config.db3`. Without a runtime channel the Remote tab only sees the
persisted set, so its tile highlights stay lit during an auto-hide fade while
the dock icon correctly de-activates (#766). A separate runtime event keeps
them in sync:

- The dock's `emitOnScreen()` (hooked at the end of `setPluginIdle()` and
  `render()`) computes the on-screen set — expanded plugins whose panel exists
  and is **not** `--idle` — and diff-guards it (`sameIdSet`, order-independent)
  so only actual changes fire. The shell's `onOnScreenPluginsChange` callback
  calls the JS bridge `setOnScreenPlugins(ids)`
  (`bridge.ts` → `{ action: "__set_on_screen_plugins", plugins: [...] }`).
- The worker sanitizes the payload (non-string entries dropped; missing/
  non-list `plugins` → empty tuple) and emits an `OnScreenPluginsChangedEvent`.
  The renderer republishes it as an `OverlayVisibilityChangedEvent` (priority 3)
  — **not** a `CommandEvent(SET_CONFIG)`, since auto-hide must not persist.
- The `/ws/state` endpoint forwards it to browsers as
  `{ type: "OverlayVisibilityChangedEvent", on_screen_plugins: [...] }`; the
  player store calls `configStore.applyOverlayVisibility(ids)`, which replaces
  the transient `onScreenPlugins` ref. `OverlayPanel.vue`'s `isActive()` tile
  highlight is `visible_plugins.includes(id) && (onScreenPlugins === null ||
  onScreenPlugins.includes(id))` — so an auto-hidden tile de-highlights while
  staying in the persisted set, and tapping it still collapses (removes from
  config), matching the dock.

**Fresh-connect replay:** the `WebKitOverlayRenderer` caches the last
`OnScreenPluginsChangedEvent` on-screen set (lock-guarded). On
`CommandEvent(REQUEST_STATE)` — published by `/ws/state` on every fresh
browser connect — it replays the cached set as `OverlayVisibilityChangedEvent`
so the Remote tab's `onScreenPlugins` is seeded with the real (possibly
auto-hidden) state instead of falling back to `visible_plugins` (assume shown).
Before this a fresh connect while a panel was auto-hidden left its tile
highlighted until the next hide/wake event.

## 6. Plugin manifest & loader

A plugin is a directory under `overlay.plugin_dir` containing a `plugin.json`
manifest and an HTML entry (default `index.html`). The manifest loader
(`src/picframe/infrastructure/overlay/plugin_loader.py`) is **pure filesystem
IO** — it never imports WebKitGTK/GTK — and is the source of truth for
discovered plugins. A missing/empty `plugin_dir` yields `[]`; malformed
manifests are skipped with a warning so one bad plugin never breaks discovery.

`PluginDescriptor` (`src/picframe/core/models/overlay.py`) is an immutable
dataclass: `id` (defaults to the directory name), `name`, `description`, `icon`
(emoji fallback), `icon_svg` (inline SVG markup from an optional `icon.svg`
file — see *Dock icons* below), `trigger` (list of activation modes — see
*Activation modes* below), `position`, `size` (`{w,h}`), `requires`
(informational capability list), `default_display_mode`, `config_schema`,
`entry`, `directory`. `plugin_config_defaults()` and `validate_plugin_config()`
turn a `config_schema` into defaults and validate user payloads: unknown keys are
rejected, `required` fields must be present, declared `type`s
(`string`/`integer`/`number`/`boolean`) and `enum` constraints are enforced.

#### Activation modes (#757)

`trigger` is a **list of activation modes** (backward-compatible: a bare string
is normalized to a single-element list by `normalize_trigger()`). Every plugin
is **dock-activatable** — it appears in the dock and tapping its icon toggles
its panel, with duration governed by the existing #752 `display_mode`
(`persistent`/`auto_hide`) + per-plugin `idle_hide_seconds`.

`"media_change"` is a **composable additional activation mode**: a plugin
listing it (e.g. the built-in `text` plugin ships `["icon", "media_change"]`)
also **auto-shows on each media change**. On every `picframe:media` reaching
the shell, for each enabled plugin whose triggers include `"media_change"`,
the shell mounts the panel hidden, waits the image blend time (`time_fade`,
sourced from `model.fade_time` / `RendererConfig.time_fade` and injected into
the shell config by `WebKitOverlayRenderer`), then **wakes** it via the same
path as a dock tap — so the panel fades in and vanishes through the existing
#752 `auto_hide` + `idle_hide_seconds`, and any input wakes it early. This
replaces the legacy pi3d `show_text_tm` countdown; no fixed-countdown timing
path is reintroduced. Unknown trigger modes are rejected at load time.

Example `plugin.json`:

```json
{
  "id": "clock",
  "name": "Clock",
  "icon": "🕐",
  "trigger": "icon",
  "position": "top-right",
  "size": { "w": 320, "h": 240 },
  "config_schema": {
    "style": { "type": "string", "default": "digital", "enum": ["digital","analog"] },
    "show_seconds": { "type": "boolean", "default": false }
  }
}
```

### Dock icons (`icon.svg`)

The dock renders each plugin as an icon button. To stay **font-independent**
(no emoji font required) and **theme-aware** (inherits the dock text color), a
plugin may ship a single-color `icon.svg` alongside its `plugin.json`. The
loader reads that file into `PluginDescriptor.icon_svg`; the worker forwards it
to the shell as `PluginEntry.icon_svg`; `dock.ts` inlines the markup via
`innerHTML` (guarded by an `<svg`-root check) so the SVG inherits `currentColor`.
The SVG must use `stroke="currentColor"` (or `fill="currentColor"`) and a `24x24`
viewBox; the shell sizes it with `.pf-dock-icon svg { width: 1.5em; height: 1.5em }`.

When a plugin ships no `icon.svg`, `icon_svg` is `""` and the dock falls back to
the manifest `icon` emoji. Emoji rendering (in the dock fallback *and inside
plugin content*, e.g. the weather plugin's condition glyphs) requires the system
color-emoji font `fonts-noto-color-emoji`, which the installer adds alongside
the WebKitGTK packages — see `docs/user/overlay.md` troubleshooting.

#### Hover tooltips

Each dock icon — transport buttons (Previous / Play-Pause / Next), plugin
icons, and the danger (power) trigger — carries a `data-tooltip` label. When a
**mouse** pointer rests on an icon for ~600 ms (`TOOLTIP_DELAY_MS`), the dock
shows a single shared `.pf-dock-tooltip` label centered above the icon (flipping
below it when the dock sits at the top edge so the text stays on screen for any
anchor). The controller uses **event delegation** on `#pf-dock`, so it survives
`render()`'s `replaceChildren` without re-wiring per element. It is mouse-only:
touch and keyboard users already get the icon `aria-label`, so the tooltip is a
mouse convenience, not an accessibility path. The label is hidden on
pointer-leave, dock idle, destroy, and before each re-render (`hideTooltip`,
called from `closeOverlays`).

## 7. API

`src/picframe/api/app.py` exposes three endpoints under `/api/overlay`, all
delegating to the injected `IOverlayController` (which uses the plugin loader):

- `GET /api/overlay/plugins` — descriptors with merged effective config
  (manifest defaults ← db overrides).
- `GET /api/overlay/plugins/{id}/config` — effective config for one plugin.
- `PUT /api/overlay/plugins/{id}/config` — validate against `config_schema`,
  persist under `overlay.plugin_config.<id>.*`, publish
  `OverlayConfigChangedEvent`. Returns 422 on invalid payload, 404 on unknown
  plugin.

When no controller is wired (overlay disabled), `GET /plugins` returns `[]`.

## 8. Composition root & graceful degradation

`src/picframe/main.py` constructs `WebKitOverlayRenderer` only when
`overlay.enabled` **and** `is_available()` are true, injecting it into
`create_app(overlay_controller=...)`. Start/stop happen in both shutdown paths
(signal handler + engine `finally` block). If WebKitGTK is absent the renderer
publishes `SystemErrorEvent(code="webkit_unavailable")` and picframe runs
unchanged. This is distinct from the compositor-absent case: a running
WebKitGTK on a non-`wlr-layer-shell` compositor silently degrades to the
plain-window fallback documented in §10 (no system error is published, but
the overlay renders behind video and loses input).

`src/picframe/core/services/bootstrapper.py` calls `_copy_overlay_plugins()`
during `picframe init`: built-in plugins ship as package data under
`picframe/overlay_plugins/` (declared via `picframe.overlay_plugins = ["**"]`
package-data in `pyproject.toml`) and are copied to
`~/.picframe/overlay-plugins/`. Built-in dirs are **force-overwritten** on every
init (code/manifest updates propagate) while **user-created** plugin dirs are
preserved. Per-plugin user config lives in `config.db3`, so overwriting built-in
code is safe.

## 9. Frontend overlay shell

The overlay shell is a **second Vite multi-page build**
(`frontend/vite.overlay.config.ts`, `base: './'`, output
`src/picframe/html/overlay/`) so it is `file://`-loadable with relative assets.
`package.json build` runs both Vite builds. Files under
`frontend/src/overlay/`:

| File | Role |
|---|---|
| `overlay.html` | Vite entry for the shell page |
| `types.ts` | `OverlayShellConfig`, `PluginEntry`, `CurrentMedia`, `StateMessage` |
| `env.ts` | Parses `?ws=<port>&plugins=<uri>` from `location.search` |
| `bridge.ts` | `window.picframe.send`/`applyConfig` JS bridge to the worker |
| `state-client.ts` | Best-effort `/ws/state` WebSocket + auto-reconnect |
| `input.ts` | Pointer zone routing (left=prev, right=next, center=toggle, Esc=hide); device-class filtering via `enabled_input_types`; idle timer |
| `dock.ts` | Plugin icons + active plugin iframe; `postToActivePlugin()` |
| `shell.ts` | Orchestrator: DOM veil/content/dock, idle-hide fade, config apply, media forwarding |
| `main.ts`, `style.css` | Bootstrap + transparent styling |

The worker loads the shell via `file://…?ws=<port>&plugins=<file uri>`
(`_shell_uri()`), because the shell cannot derive the WS port or plugin dir
from its `file://` origin. `_build_shell_config()` enriches the overlay config
with `_plugins`, `_ws_port`, and `_plugin_uri`, then `_push_config_to_shell()`
injects `window.picframe.applyConfig(payload)`. The shell boots by asking for
config via the `__request_config` action over the JS bridge.

### Input routing (parallel, always-on)

The shell binds to **Pointer Events** (`pointerdown`, unifying mouse/touch/pen)
**and** keyboard (`keydown`) **in parallel, always-on** — one handler code path
for all devices. `overlay.enabled_input_types` only lets users *disable* a
device class (e.g. touch on a kiosk); activity tracking counts any enabled
event. This lets the overlay be developed/tested with mouse + keyboard on
hardware with no touchscreen, then work identically once a touchscreen is
connected.

## 10. Video + overlay stacking (Z-order & opacity)

Z-order is pi3d (bottom) < GTK4 video host < WebKitGTK overlay (top). The
overlay is never withdrawn; opacity drives visibility:

- `RENDER_PROMOTE_VIDEO_REVEAL` → `SetOpacity(0.0)`: video shows through, but
  the surface stays on top and keeps capturing input.
- `RENDER_PARK_VIDEO_REVEAL` / `RENDER_WAKE_VIDEO_REVEAL` → `SetOpacity(1.0)`.
- Any wake event (`pointermove`/`pointerdown`/`keydown`/`touchstart`) raises
  opacity back to 1.0; after `overlay.idle_hide_seconds` idle it fades to 0
  again (same behavior for photos and videos).

`wlr-layer-shell` (via `gtk4-layer-shell`, `_setup_layer_shell()`) anchors the
surface to all four edges in the `OVERLAY` layer with exclusive zone `-1` and
on-demand keyboard, so it floats above pi3d/video while transparent and still
receiving input. It degrades to a plain borderless `Gtk.Window` when the
typelib is absent.

**Compositor requirement:** `wlr-layer-shell` is a hard requirement for the
documented stacking. `labwc` (the installer's default kiosk compositor), Sway,
and Hyprland implement the protocol; `cage`, Mutter, and Weston do not. On a
non-layer-shell compositor the plain-window fallback renders behind the GTK4
video host during playback (the overlay is hidden and loses input), so the
installer no longer ships `cage` and the `wayland-kiosk` display mode has been
removed. The fallback code path is retained only as a graceful degrade for a
half-installed `gtk4-layer-shell` on a `labwc` system, not as a supported
compositor path.

### Display power-cycle (output destroy/recreate)

`WaylandDisplayPower.turn_off()` runs `wlr-randr --output <name> --off`, so the
compositor **destroys** that Wayland output. The layer-shell surface is bound
to that (now-destroyed) output, so labwc drops the view
(`view has no output, not updating geometry`). When the display is turned back
on (`wlr-randr ... --on`) the compositor creates a **new** output, but the
orphaned layer-shell surface never re-attaches to it, so the overlay stays
invisible until picframe is restarted. (pi3d's fullscreen surface survives the
cycle because it re-commits continuously on the main render loop; the one-shot
layer-shell surface in the separate worker process does not.)

The same orphaning happens for an **external** power-cycle — the monitor's
physical power button or a compositor-initiated DPMS sleep. Real-hardware
diagnostics (#755) showed labwc keeps `Enabled: yes` through a sustained off
(the connector is *not* removed while the monitor stays unplugged), but fires
a ~1 s HPD blip at the **on-transition**: the connector listing vanishes
momentarily then returns. That blip is only catchable by `wlr-randr` polling
at ≤ 0.5 s, and only then because the watcher parser matches the connector
name (first whitespace-delimited token, e.g. `HDMI-A-2`) rather than the
whole `wlr-randr` name line, which on real hardware carries a quoted human
description (`HDMI-A-2 "Samsung Electric Company SAMSUNG (HDMI-A-2)"`). The
in-process manager cannot see this either: `WaylandDisplayPower.is_on()` only
reflects picframe-initiated commands (it caches `self._is_on`), so no
`DisplayPowerEvent` is published for external cycles.

Fix (internal cycles): `DisplayPowerManager` publishes a
`DisplayPowerEvent(power_on=...)` on the event bus after a **real** display
state change (not on the idempotent "already in that state" skip branches).

Fix (external cycles, #755) is the **poll watcher** as the single proven
mechanism:

`DisplayOutputWatcher` (`infrastructure/os/display_output_watcher.py`) is
constructed in `main.py` only when the overlay is enabled and available. It
polls the configured output's presence/enabled state via `wlr-randr` (0.5 s
default, daemon thread) and publishes `DisplayPowerEvent` on observed
off->on / on->off transitions — edge-triggered, with no publish for the
startup baseline so it never emits a spurious power-on. It is a no-op when
`wlr-randr` is absent or the compositor lacks `wlr-output-management` (the
probe returns `None` and nothing is published), so headless/VM/dev
environments are unaffected. It deliberately polls rather than subscribing
to `Gdk.Display::monitor-added` / `monitor-removed`: that would drag a live
GLib/GTK main loop into the main process (violating the
keep-WebKit-out-of-process non-negotiable) and would miss DPMS-only blanks.

`WebKitOverlayRenderer` subscribes to `DisplayPowerEvent`; on power-on it
respawns the worker subprocess (`stop()` → `start()`) via a guarded
`_schedule_respawn()` helper run on a daemon thread, re-running the proven
`_build_surface()` / `_setup_layer_shell()` path against the now-live output.
`start()` re-pushes the cached overlay config so the shell boots with the
right plugins. The respawn is guarded so a burst of events cannot stack
restarts or race shutdown, and it is a no-op when the overlay is disabled
(display power-on never auto-enables the overlay). Because both the internal
command path and the external watcher poll publish the same
`DisplayPowerEvent` that collapses to a single respawn via the renderer's
restart guard, internal and external cycles heal identically. This mirrors
the worker-isolation non-negotiable: WebKitGTK can crash or leak, so respawn
rather than fix the live process.

### Wake-on-input while the output is off (#762)

While the Wayland output is destroyed by `wlr-randr --off` (or a compositor
DPMS blank), the overlay's JS listeners cannot fire — the layer-shell surface
is gone — so moving the mouse or pressing a key does nothing until picframe
re-creates the output itself. The **backend wake-on-input path** closes that
gap: a new `IWakeInputListener` port reads raw `/dev/input/event*` devices
*independent of any Wayland surface*, so it works in the off state.

`EvdevWakeAdapter` (`infrastructure/os/evdev_wake_adapter.py`) implements the
port using the `evdev` library (a Linux-only dependency, lazy-imported). It
listens **passively** (no `grab()`), so the compositor keeps receiving events
for normal UI while the display is on. It filters to pointer + keyboard
devices — touch devices are excluded by design (the surface is destroyed
while off, and touch-on-a-dark-screen is not a wake gesture) — and emits
`"mouse"` on relative pointer motion and `"keyboard"` on a key
press/repeat (releases are ignored).

`WakeOnInputService` (`core/services/wake_on_input.py`) turns those raw
events into `Command.DISPLAY_ON` on the event bus. It is gated by:

- **`overlay.enabled_input_types`** — only `mouse`/`keyboard` are
  wake-capable; `touch` never wakes (the service enforces this even if a
  future adapter emitted it). Disabling both classes from the web UI
  disables wake-on-input live (the service reloads on a `CONFIG_CHANGED`
  whose `updated_sections` contains `"overlay"`).
- **The current display state** — it is idempotent: `IDisplayPower.is_on()`
  is checked first, so an already-on display is never re-woken.
- **A 1 s cooldown debounce** — a burst of mouse moves while the display is
  still transitioning on publishes at most one `DISPLAY_ON`.

It deliberately publishes **only `DISPLAY_ON`**; the `PLAY` side-effect is
owned by `DisplayPowerManager`, keeping the single-owner responsibility
intact.

The HAL factory injects `EvdevWakeAdapter` on Linux when `evdev` is
importable and at least one `/dev/input/event*` device is readable;
otherwise it falls back to `MockWakeInputListener` (dev/CI/headless). The
picframe user must be in the **`input`** group for `/dev/input/event*`
access — the install script (`docs/user/install_picframe.sh`) already adds
this. The adapter degrades gracefully if a device is unreadable: it logs a
warning and skips that device rather than crashing.

### Why a worker self-report was attempted and reverted

An earlier Phase-2 design tried to make output loss event-driven: the worker
would connect `Gdk.Display::monitor-removed` on its window's `GdkDisplay` and
emit a `SurfaceOrphanedEvent` over the IPC channel, so the renderer could
respawn it without any polling. **This is architecturally impossible on the
target.** GTK4's `GdkWaylandDisplay` does not expose `monitor-removed` or
`monitor-added` — those are GTK3-era signals that were dropped in GTK4; a
`GdkWaylandDisplay` only offers `opened`, `closed`, `seat-added`, and
`seat-removed`. The `display.connect("monitor-removed", ...)` call failed on
every worker respawn, logging a misleading `connect failed` line while never
detecting a real orphan. Since the poll watcher (Phase 1) was already proven
on real hardware to self-heal on both physical monitor power-cycles and
UI-triggered `DISPLAY_OFF`/`DISPLAY_ON`, the dead self-report path was removed
to keep a single, proven mechanism.


## 11. Built-in plugins & postMessage protocol

Built-in plugins are self-contained static HTML (no build step) loaded via
`file://` in iframes:

- **clock** — analog (SVG hands) or digital styles, 12h/24h `clock_format`,
  `show_seconds`, `show_date`. Listens for `picframe:config`.
- **weather** — OpenWeatherMap One Call 3.0 (`api_key`/`lat`/`lon`/`units`/
  `language`/`refresh_seconds`); graceful error handling.
- **meta** — current image EXIF + Leaflet map at GPS coords (CDN, offline
  text-coordinate fallback); tap-to-expand; updates on photo change.

The shell pushes data into the active plugin's iframe via `postMessage`
(`dock.ts`):

- `{ type: 'picframe:config', pluginId, config }` — effective per-plugin config,
  sent on iframe load and on config change. Plugins opt in by listening for it.
- `{ type: 'picframe:media', media }` — **new** (Phase 3): the shell's
  `StateClient.onMedia` callback forwards the current media to the active plugin
  via `dock.postToActivePlugin()`, so a plugin (e.g. `meta`) reacts to photo
  changes without its own WebSocket client. `CurrentMedia.location` carries the
  GPS `{lat, lon}` (or `null`).

### Content sizing & alignment convention

Plugins use one of two layout **modes**, driven entirely by whether the
manifest declares a `size`:

- **Scale mode** (manifest `size` present — clock, weather): the plugin lays
  out its content once at the fixed design size, and the **shell zooms the whole
  widget** with `transform: scale(layout.scale)`. The panel is sized to
  `design × scale`, so its aspect matches the widget **exactly** — no contain-fit
  background strips. The user controls one **Scale** slider; there is no
  width/height or content-alignment control.
- **Fill mode** (no manifest `size` — meta/Photo Info): the iframe fills the
  panel `100% × 100%`, and the user-controlled **Width**/**Height** enlarge the
  panel. The plugin's own content (e.g. the Leaflet map with `flex: 1`) absorbs
  the extra space, so a bigger panel shows a bigger map.

Both modes avoid container queries, which turned out to be unreliable in the
WebKitGTK overlay iframe (see *Why not container queries* below).

- **Design size** — declare `"size": { "w": 320, "h": 240 }` in `plugin.json`
  to opt into scale mode. The worker forwards it as `_plugins[i].size` in the
  shell config. Omitting `size` opts into fill mode.
- **Shell scaling** (`dock.ts`) — for a scale-mode panel the shell sizes the
  panel to `design × scale` (`applyPanelLayout`), lays the iframe out at the
  design size, and applies `transform: scale(layout.scale)` with
  `transform-origin: top left` anchored at `(0, 0)`. The whole widget — text,
  SVG, card — scales **uniformly**; because the panel aspect matches the
  widget, the scaled iframe fills the panel with no gaps. No `clientWidth`
  measurement or reflow is needed. For a fill-mode panel the iframe simply
  fills it (`100% × 100%`, no transform).
- **Plugin content units (scale mode)** — size content at the design size with
  `max(min_floor, calc(var(--w) * N/100))`, where `--w` is the design width
  declared once on `:root` (e.g. `:root { --w: 320px; }`). `N/100` is the old
  `Ncqw` value expressed as a fraction of the design width; `calc(var(--w) *
  N/100)` reproduces it exactly at the design size and the shell's `scale()`
  handles all resizing. The `max()` floors a shrunk widget at a legible size;
  there is **no upper cap** — the user decides how big is too big via the Scale
  slider.
- **Scale-mode panel is transparent; plugins paint their own background** —
  a scale-mode shell panel (`.pf-plugin-panel--scale`) has no background or
  shadow, so the photo shows through everywhere except behind the content.
  Each plugin paints its readability background on its *content container*
  (e.g. `.pf-digital` / `.pf-weather`) so the dark area hugs the content as
  tightly as possible; the analog clock uses a filled disc matching the face
  diameter instead of a square. Because the background is inside the iframe,
  `transform: scale()` scales it with the rest of the widget. Fill-mode
  panels (no manifest `size`) keep the shell `.pf-plugin-panel` background.
- **Plugin content units (fill mode)** — set `--w`/`--h` in px from
  `window.innerWidth/innerHeight` (and update them on `resize`) so
  `calc(var(--w) * N/100)` text sizing tracks the user-chosen panel dimensions.
  The meta plugin does this in `setVars()` and calls `map.invalidateSize()` on
  resize so the Leaflet map reflows.

**Why not container queries:** two on-device attempts failed against WebKitGTK
2.52 — `container-type` on `<html>` (`cqw` → 0 on the root element, whose
containing block is the iframe's Initial Containing Block) and on `<body>`
(content still did not scale, despite `cqw` resolving). Even if a future
WebKitGTK build fixed `<body>`, container queries only scale *content* and
leave the panel background fixed — the opposite of the desired widget-scaling
model. `transform: scale()` scales the entire iframe (content *and* its own
background) uniformly and works regardless of the WebKitGTK container-query
quirk, so it is the long-term approach.

A plugin that needs both-axis fit beyond uniform scale (e.g. a different
aspect crop) can still compute its own layout in JS, but the scale/fill modes
cover the common cases.

## 12. Web UI controls

There is **no separate overlay tab** — controls are split to match existing UX:

- **Remote view** (`components/remote/OverlayPanel.vue`) — discovered plugin
  list with enable/disable toggles (`overlay.enabled_plugins`) + visible-plugin
  selector (with "Dock only" = null); per-plugin config editor rendering
  `config_schema` fields by type (boolean→ToggleSwitch, integer/number→
  NumberField, enum→select, string→input). Live apply on save. No
  `configSchema.json` entries (data-driven SettingsView only). Pinia store
  `stores/overlay.ts` does `fetchPlugins()` and `updatePluginConfig()`;
  `overlay.*` settings persist via `configStore.savePartialConfig({ overlay })`.
- **Appearance view** (`components/OverlayAppearanceSection.vue`) — display-mode
  SegmentedControl (persistent vs auto_hide) + auto-hide seconds (shown only in
  auto_hide), idle-fade seconds, enabled-input-types checkboxes,
  transparent-surface toggle.

i18n keys live under `remote.touchOverlay.*` and `appearance.overlay.*` in
`en.json`/`de.json` (full key parity).

## 13. Tests

TDD throughout Phases 0–3; all gates green (pytest 891, mypy strict 88 files,
ruff clean, ruff format 163 files, frontend lint 0 errors, both Vite builds):

- `test/core/renderers/test_overlay_ipc.py` (9) — IPC message round-trips + parser.
- `test/core/renderers/test_webkit_overlay_renderer.py` (12) — mocked `gi`/WebKit: spawn, opacity from render actions, config forwarding, input republish, graceful degradation.
- `test/core/models/test_overlay.py` (11) — `PluginDescriptor`, `validate_plugin_config` defaults/required/type/enum/unknown.
- `test/infrastructure/overlay/test_plugin_loader.py` (10) — discovery, malformed manifest skip, `icon.svg` loading.
- `test/infrastructure/overlay/test_overlay_worker.py` (20) — headless GTK-free IPC plumbing, layer-shell wiring.
- `test/infrastructure/overlay/test_builtin_plugins.py` (7) — built-in manifests/config_schema validation + `icon.svg` presence.
- API endpoint tests in `test/api/test_app.py` (7); bootstrapper copy in
  `test/core/services/test_bootstrapper.py` (10).

The frontend has no unit-test runner; its gate is `yarn lint` + `vue-tsc` + both
Vite builds (same as the main SPA). The **real-Wayland integration test**
(spawning a live worker on labwc) remains hardware-blocked — see issue #739
verification criteria.

## 14. Open / hardware-blocked

- End-to-end Phase-1 spike: `file://`→`ws://localhost` cross-origin WebSocket in
  WebKitGTK, and `wlr-layer-shell` availability on labwc, need a real Wayland
  display + WebKitGTK typelib to validate.
- A **controls plugin** (legacy menu replacement) is tracked separately and is
  out of scope for #739.
