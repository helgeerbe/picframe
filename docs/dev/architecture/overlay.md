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
| `InputEvent` | `action: str` | `prev`/`next`/`toggle`/`hide` → translated to `Command` |
| `OverlayErrorEvent` | `details: str`, `code: str?` | e.g. WebKitGTK init failure |

`parse_overlay_ipc_message()` returns `None` for malformed JSON or unknown
types so a bad line from the worker never crashes the listener. Input actions
map to playback `Command`s via `_command_for_input_action()`:
`prev`→`PREV`, `next`→`NEXT`, `toggle`→`PLAY`, `hide`→`STOP`.

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

## 6. Plugin manifest & loader

A plugin is a directory under `overlay.plugin_dir` containing a `plugin.json`
manifest and an HTML entry (default `index.html`). The manifest loader
(`src/picframe/infrastructure/overlay/plugin_loader.py`) is **pure filesystem
IO** — it never imports WebKitGTK/GTK — and is the source of truth for
discovered plugins. A missing/empty `plugin_dir` yields `[]`; malformed
manifests are skipped with a warning so one bad plugin never breaks discovery.

`PluginDescriptor` (`src/picframe/core/models/overlay.py`) is an immutable
dataclass: `id` (defaults to the directory name), `name`, `description`, `icon`
(emoji), `trigger` (`"icon"` = dock tap), `position`, `size` (`{w,h}`),
`requires` (informational capability list), `config_schema`, `entry`,
`directory`. `plugin_config_defaults()` and `validate_plugin_config()` turn a
`config_schema` into defaults and validate user payloads: unknown keys are
rejected, `required` fields must be present, declared `type`s
(`string`/`integer`/`number`/`boolean`) and `enum` constraints are enforced.

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

- `test/core/renderers/test_overlay_ipc.py` (10) — IPC message round-trips + parser.
- `test/core/renderers/test_webkit_overlay_renderer.py` (15) — mocked `gi`/WebKit: spawn, opacity from render actions, config forwarding, input republish, graceful degradation.
- `test/core/models/test_overlay.py` (11) — `PluginDescriptor`, `validate_plugin_config` defaults/required/type/enum/unknown.
- `test/infrastructure/overlay/test_plugin_loader.py` (8) — discovery, malformed manifest skip.
- `test/infrastructure/overlay/test_overlay_worker.py` (25) — headless GTK-free IPC plumbing, layer-shell wiring.
- `test/infrastructure/overlay/test_builtin_plugins.py` (6) — built-in manifests/config_schema validation.
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
