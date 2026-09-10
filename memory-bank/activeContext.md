# Active Context

## Current Focus
**WebKitGTK touch overlay + plugin system (#739) shipped via PR #754
(squash-merged to `dev` as `6ec7c74`)** — nine issues closed (#739, #750,
#751, #752, #757, #758, #759, #760, #761). **Wake-on-input (#762) then
shipped via PR #768 (squash-merged to `dev` as `8c2f94a`); issue #762
closed.** `dev` head is now `8c2f94a`; both feature branches deleted.

**#777 — overlay keyboard navigation + configurable shortcuts (PR #778, open on
`dev`):** full implementation shipped in `17ec79a` on `feat/777-overlay-keyboard-navigation`
(config schema, backend models/app/renderer, overlay `input.ts`/`shell.ts`/`dock.ts`,
Settings `TouchOverlaySettingsSection.vue`, i18n en/de, 24 frontend + backend tests,
docs). Sourcery flagged one valid `bug_risk`: `saveKeyBindings` dropped a rapid
trailing edit made while a save was in flight (`if (isSaving.value) return`).
**Fixed in `290a88e`** via a reusable `useCoalescedSave` composable
(`frontend/src/composables/useCoalescedSave.ts`) that accepts the component's
shared `isSaving` ref and re-sends the latest snapshot once the in-flight PUT
settles — preserving the shared mutual-exclusion guard + "saving" button state.
Unit-tested (5 cases); `yarn test` (85)/`lint`/`format`/`build` (vue-tsc) green.
Replied to the Sourcery thread. Note: the identical inherited guard in
`OverlayAppearanceSection.vue` (plugin-toggle auto-save) was left out of scope —
candidate for a separate consistency ticket.

**#779 + #780 — follow-ups on `feat/777-overlay-keyboard-navigation` (PR #778):**
- **#779 (EXCLUSIVE keyboard mode):** `ON_DEMAND` (#754) only delivers keyboard
  events while the compositor considers the surface focused, and labwc does not
  retain that focus across key actions — so #777 routing worked once then went
  dead. Fixed in `overlay_worker.py` by switching the layer-shell keyboard mode
  to `EXCLUSIVE` (keyboard input only; pointer/touch + opacity/video-reveal
  path unchanged). Right mode for a kiosk frame with no competing Wayland app.
- **#780 (unified keyboard wake):** any key now wakes the dock (mirrors a touch
  tap), unifying keyboard with the touch reveal-then-navigate model. `input.ts`
  `handleKey` calls `onActivity('keyboard')` before bound-key routing; Escape
  still routes only to `onHide`. `shell.ts` `onHide` now **toggles** the dock
  from the `pf-root--dock-idle` state — wake (reveal + re-arm) when hidden,
  dismiss (close an open dropdown first, else hide the dock chrome) when shown.
  Bound keys wake + fire their action immediately; reserved keys (Tab/Enter/
  Space) wake but keep native behavior; unbound keys wake only (was a no-op).
  Frontend-only; no config/schema impact. Tests: `input.test.ts` (+unmapped/
  F5 wake, reserved-key `onActivity` asserts) and a new `shell.test.ts`
  Escape-toggle block. Gates: `yarn test` (89)/`lint`/`format`/`build`,
  `pytest` (1127)/`mypy`/`ruff` all green. `decisionLog.md` + `overlay.md`
  updated.

**What shipped:**
- Out-of-process WebKitGTK overlay worker (`infrastructure/overlay/overlay_worker.py`)
  using `wlr-layer-shell` via the guarded `gtk4-layer-shell` typelib (falls back
  to a plain borderless `Gtk.Window` when the typelib is absent), mirroring the
  `gst_worker.py` isolation pattern. `WebKitOverlayRenderer` drives it from the
  main thread behind `overlay.enabled` + `is_available()`.
- Plugin system: four built-in plugins under `src/picframe/overlay_plugins/`
  (package data) — **Clock** (`clock`, enabled by default), **Photo Info**
  (`meta`, enabled by default; EXIF + Leaflet GPS map), **Photo Caption**
  (`text`, opt-in), and **Weather** (`weather`, opt-in; OpenWeatherMap One Call
  3.0). Default-enable logic lives in `api/models.py`; the bootstrapper copies
  built-ins to `~/.picframe/overlay-plugins/` on `picframe init` (overwrites
  built-ins, preserves user plugins).
- Multi-plugin layout model: per-plugin position/scale/width/height/display
  mode/idle fade/z-order with simultaneous visibility; hybrid two-mode sizing
  (manifest `size` → scale mode; no `size` → fill mode). Opacity-based hide/wake
  with `idle_hide_seconds`, parallel pointer+keyboard input routing, and a Vite
  multi-page overlay shell (`frontend/src/overlay/` →
  `src/picframe/html/overlay/`).
- Power-cycle resilience (#755): the worker respawns on display power-on so the
  orphaned layer surface re-attaches to the recreated Wayland output. Display
  controls (dock, catalog, plugin list, activation/visibility toggles) are
  public; only per-plugin *config* (secrets such as the weather `api_key`) and
  *layout* stay Settings-protected, fetched on demand via
  `store.fetchPluginConfig` (#756).
- Docs: `docs/dev/architecture/overlay.md` and `docs/user/overlay.md`; the
  installer ships WebKitGTK + `gtk4layershell` packages and `labwc-kiosk`
  (`cage`/`wayland-kiosk` removed; `wlr-layer-shell` is a hard requirement).

**Still open:**
- **#753** — deprecate the pi3d Clock/Text renderers now that the WebKitGTK
  overlay ships Clock and Photo Caption plugins.
- **Real-Wayland integration test** — hardware-blocked (spawning a live worker
  on labwc); tracked in #739 verification criteria. The clock overlay was
  confirmed rendering on `picframepoc` (labwc) after the bridge-signal fix.

**#765 — dock visible-plugin persistence (in progress on a working branch):**
the touch-overlay dock icon toggle now persists `overlay.visible_plugins` to
`config.db3` through the same `CommandEvent(SET_CONFIG)` path the Remote/
Appearance REST endpoint uses, so both UIs share one source of truth and the
choice survives `media_change` and restarts. Backend: `VisiblePluginsChangedEvent`
added to `overlay_ipc.py` (+ `from_dict` coerces the JSON list back to the
declared tuple) and registered in `_EVENT_TYPES`; the worker handles
`__set_visible_plugins` bridge action → `emit_visible_plugins()`; the renderer
republishes the event as `CommandEvent(SET_CONFIG, {overlay:{visible_plugins}})`.
Frontend: `setVisiblePlugins()` emitter added to `bridge.ts` (typed via
`BridgeSendPayload`); `shell.ts` calls it in `onVisiblePluginsChange`;
`dock.ts` `showPluginIdle` guards on `visiblePlugins.includes(pluginId)` so a
collapsed `media_change` plugin stays collapsed across photo changes. Tests
added for IPC round-trip, worker bridge handler, and renderer event→CommandEvent.
Docs updated in `docs/dev/architecture/overlay.md`. All gates green (pytest,
mypy, ruff, yarn lint/format/build). GitHub issue #765 tracks this.

**#766 — Remote tab mirrors overlay on-screen (auto-hide) visibility (done on
the working tree):** the touch-overlay auto-hide is a transient client-side
CSS fade (`pf-plugin-panel--idle`) that never writes `config.db3`, so the
Remote tab's `visible_plugins`-only tile highlights stayed lit while the dock
icon de-activated. Added a **runtime** channel parallel to the persisted
config channel: new `OnScreenPluginsChangedEvent` in `overlay_ipc.py`
(registered in `_EVENT_TYPES`, `from_dict` list→tuple); the worker handles the
`__set_on_screen_plugins` bridge action → `emit_on_screen_plugins()`; the
renderer republishes it as a new `OverlayVisibilityChangedEvent` DTO (priority
3, **not** `CommandEvent(SET_CONFIG)`, since auto-hide must not persist);
`/ws/state` forwards it via `overlay_visibility_websocket_message`. Frontend:
`setOnScreenPlugins()` in `bridge.ts`; `Dock.emitOnScreen()` (hooked at the end
of `setPluginIdle()` and `render()`, diff-guarded via `sameIdSet`) +
`onScreenPluginIds()` in `dock.ts`; shell wires `onOnScreenPluginsChange`;
`config.ts` adds `onScreenPlugins` ref + `applyOverlayVisibility`; `player.ts`
handles the `OverlayVisibilityChangedEvent` branch; `OverlayPanel.vue`
`isActive()` replaces `visiblePlugins.includes` for the tile highlight (a faded
tile de-highlights but still taps to collapse, matching the dock). Tests added
for IPC round-trip/coercion, worker bridge handler, renderer republish, and WS
serialization + ASGI subscription. Docs updated in `overlay.md`. All gates
green. **#766 fresh-connect replay (done):** the renderer caches the last
`OnScreenPluginsChangedEvent` on-screen set and, on
`CommandEvent(REQUEST_STATE)` (fresh browser connect), replays it as
`OverlayVisibilityChangedEvent` so the Remote tab's `onScreenPlugins` is
seeded with the real (possibly auto-hidden) state instead of falling back to
`visible_plugins`. Previously a fresh connect while a panel was auto-hidden
showed its tile highlighted until the next hide/wake event.

**#765 follow-up — dock→browser live-sync (done):** the `/ws/state` WebSocket
endpoint never subscribed to `OverlayConfigChangedEvent`, so a browser's
`useConfigStore` stayed a REST snapshot (stale `visible_plugins` /
`enabled_plugins`) until a page reload when the touch-overlay dock toggled a
plugin. Fixed end-to-end: `app.py` `websocket_state` now subscribes a
`handle_overlay_config_changed` handler (and unsubscribes it in the `finally`
block) that forwards only the `PUBLIC_WORKFLOW_KEYS["overlay"]` subset
(`enabled`, `idle_hide_seconds`, `enabled_input_types`, `enabled_plugins`,
`visible_plugins`) — the same surface as `GET /workflow-config` — so
settings-scope secrets (`plugin_config` api_keys, `plugin_layout`, `backend`)
never reach an unauthenticated browser. The filtering lives in a pure
module-level helper `overlay_config_websocket_message(event) -> str | None`
(mirrors `system_error_websocket_message`). Frontend: `useConfigStore`
gained `applyOverlayConfig(overlay)` (deep-merges via `mergeConfig` so a
Settings-authenticated user's existing settings-scope keys are preserved);
`player.ts` `onmessage` routes `OverlayConfigChangedEvent` →
`useConfigStore().applyOverlayConfig(data.overlay)`. Tests: three in
`test/api/test_app.py` — pure filtering (secrets stripped), returns `None`
when only settings-scope keys changed, and an ASGI-level drive of `/ws/state`
(httpx has no ws:// support, so the endpoint is driven by hand via
`app(scope, receive, send)`) asserting the registered callback pushes only the
public subset. All gates green; on-device verify still pending (toggle a
plugin via the dock → browser updates without reload; confirm no secrets in
the WS message).

**#767 — sibling-panel reveal regression fix (done):** toggling one dock
plugin (e.g. always-visible `clock`) was revealing an unrelated auto-hidden
plugin (e.g. `text` in `--idle` awaiting a `media_change` wake). Two root
causes, both in the `togglePlugin` path: (1) `dock.ts` `applyPanelLayout`
reset `panel.className` entirely on re-render, wiping the
`pf-plugin-panel--idle` class `showPluginIdle`/the per-panel idle timers had
armed → the panel's CSS transition faded the hidden sibling in; (2)
`shell.ts` `onVisiblePluginsChange` called a full `this.wake()`, which
removes `--idle` from every visible panel and re-arms idle timers, un-hiding
idle siblings for `idle_hide_seconds`. Fixes: `applyPanelLayout` now
captures `wasIdle` before resetting `className` and re-adds `--idle`
after, so `render()` is non-destructive w.r.t. idle state (a brand-new panel
has no `--idle` to preserve; `applyConfig` is followed by a full `wake()`
that reconciles, same as before). `onVisiblePluginsChange` now calls
`this.wake(true, false)` — reveal the dock only, never reset/un-hide
unrelated panels. Touch/keyboard/pointermove paths still call the full
`wake()`. Defensible behavior shift: an `auto_hide` plugin toggled ON via
the dock no longer gets its idle timer armed immediately by the toggle; it
stays visible until the next touch/pointermove/keyboard activity, after
which the full `wake()` arms its timer and it auto-hides normally —
consistent with "focus only on the clicked plugin". No frontend test
runner exists in this project (vitest/jest not configured; `package.json`
scripts are dev/build/lint/format only), so the fix was verified by
`yarn build` (vue-tsc + vite), `yarn lint` (0 errors), and
`yarn format:check`. vitest introduction is a deferred follow-up (the
first case would be a #767 regression test against `Dock.render` panel
reconciliation + `shell.wake` reveal flags). Manual device verification
still pending: (a) hide `clock` while `text` is auto-hidden → `text` stays
hidden; (b) toggle `clock` back on → `clock` reappears without disturbing
`text`; (c) `media_change` still wakes only opted-in `text`; (d) touch the
screen → auto-hidden panels still reveal (full `wake()` path intact).

**#766 — mouse-click reveals all plugins + dock icon stays highlighted when
auto-hidden (done):** two related regressions, both distinct from #767. (1) A
mouse click on the photo was revealing every auto-hidden plugin:
`InputRouter.handlePointer` fired `onActivity()` for any `pointerdown`, and the
shell's `onActivity` called the full `wake()` (`revealPanels=true`), stripping
`--idle` from every panel — correct for touch (tap-to-reveal) but inconsistent
with `onMouseMove`, which already does `wake(true, false)`. Fix: `onActivity`
is now pointer-type-aware (signature `(source: InputType) => void`); the shell
calls `wake(true, false)` for mouse (matching pointermove) and the full
`wake()` for touch/keyboard. Keyboard handlers pass `'keyboard'`. (2) A
plugin's dock icon stayed highlighted while its panel was auto-hidden:
`buildIcon` set `pf-dock-icon--active` from `visiblePlugins` (the toggled-on
config set), which never changes on auto-hide. Fix: the dock now owns idle
state for both the panel and its icon together. `buildIcon` tags each icon
with `data-plugin-id`; new `setPluginIdle(id, idle)` toggles `--idle` on the
panel **and** `--active` on the matching icon (active when shown, not when
idle); the shell's `wake()` per-panel idle loop and `showPluginIdle`
(media_change) route through it; new `syncIconStates()` runs at the end of
`render()` to reconcile rebuilt icons with the panels' preserved `--idle`
classes (#767). Behavior (Option A, per user): dock-icon `--active` tracks
on-screen state — an auto-hidden plugin's icon looks the same as a turned-off
plugin; clicking it still toggles `visiblePlugins` config off. If confusing,
a distinct dimmed "idle" look is a small CSS follow-up. Gates: yarn build
(vue-tsc + vite), yarn lint 0 errors, yarn format:check. Manual device
verification pending: (a) mouse-click photo → dock reveals, auto-hidden panels
stay hidden; (b) touch photo → all panels reveal (unchanged); (c) let photo
info auto-hide → icon loses highlight; (d) `media_change` → photo info wakes +
icon re-highlights; (e) keyboard arrows → full wake; (f) dock transport
buttons → full wake.

**Commit-message convention** codified in `decisionLog.md`: use the `(#NNN)`
trailer form (e.g. `fix(overlay): ... (#755)`); bare ` #NNN` tolerated, not
preferred; `Refs #NNN` not used.

## Current Repo State
- `dev` HEAD: `6ec7c74` (PR #754 squash-merge: WebKitGTK touch overlay + plugin
  system, closes #739 et al.). The `feat/739-webkit-overlay` feature branch is
  deleted (local + remote); all commits are preserved on `dev`. The `main`
  release PR remains deferred (user's call).
- The source tree is centered on the next-gen `main.py`, `core`, `api`, and
  `infrastructure` architecture. Legacy top-level helpers have been relocated:
  `geo_reverse.py` → `infrastructure/geo_reverse.py` (#741), `mat_image.py` →
  `core/utils/mat_image.py` (#742). Broad legacy runtime modules were removed
  during #678. The dead `peripherals` config section is now removed (#749).

## Established Context (post-modernization merge)
All Picframe 2.0 modernization work has merged into `dev` via PR #737. The
codebase now reflects the full target architecture; GitHub Issues and the
Project board remain the authoritative progress source. Key established facts:

- **Architecture:** Clean Architecture / Hexagonal, strict Event-Driven Design
  with immutable DTOs on a thread-safe PriorityQueue bus, dual SQLite repos
  (`config.db3` persistent, `media_cache.db3` rebuildable), HAL ports/adapters,
  FastAPI + Vue 3 control plane, Wayland-only display, pi3d on main thread,
  GStreamer isolated in `gst_worker.py` subprocess IPC.
- **Backend completeness:** playlist manager, playback engine, pi3d renderer,
  GStreamer video renderer with first/last-frame handoff, watchdog media
  monitor (infrastructure adapter), media indexer, hardware input service,
  Home Assistant MQTT adapter, config service with YAML import normalization.
- **Frontend completeness:** Remote, Appearance, Settings, Logs views; domain
  editors with safe path browsing; media-selection filter chips; shuffle
  transport; clock/text overlays; Leaflet maps; i18n (en/de).
- **Quality gates:** `ci.yml` runs ruff, mypy, pytest, frontend drift, package
  build, Conventional Commit PR-title validation on PRs to `dev`. `release.yml`
  uses calver tags, PyPI trusted publishing, and GitHub Releases from
  `dev → main` merges. See `docs/dev/workflow.md`.
- **Frontend lint baseline (#738/#743):** `@typescript-eslint/no-explicit-any`
  is `error`; `errors.ts` provides `getErrorMessage` / `getApiErrorMessage`
  helpers; 5 genuinely-dynamic blobs retain scoped `eslint-disable-next-line`
  with rationale (store `config` ref, `MediaItem.exif`, `SettingsView`
  `localConfig`/`initializeConfig`/`initialized`).

Architectural invariants that must be preserved during future work are listed
in the "Immediate Next Steps / Preserve" section below and in `decisionLog.md`.

## Architectural Invariants To Preserve
These boundaries must not be violated during future work. Full rationale per
ticket is in `decisionLog.md` and the linked GitHub Issues.

- **Core independence:** core logic depends on interfaces, not FastAPI/Vue/
  SQLite/MQTT/pi3d/GStreamer details. OS-specific adapters (watchdog, GPIO)
  stay outside core behind ports (`IMediaMonitor`, `IHardwareInput`).
- **Threading:** pi3d/OpenGL on main thread only; background services use the
  event bus. GStreamer isolated in `gst_worker.py` subprocess with typed JSON
  IPC over a Unix-domain socket.
- **DB injection:** `main.py` chooses DB paths and injects repositories; FastAPI
  /WebSocket must not open cache DB files directly (#637). Shared SQLite
  connection access is serialized with repository-local locks across all
  threads (#696, #708).
- **Matting:** renderer image-preparation concern only — not playlist, DB,
  REST/WebSocket, or `ImageProcessingService` (#619). No persistent matted
  files; videos are never matted (#742 moved `mat_image.py` → `core/utils/`).
- **Geocoding:** reverse geocoding is an infrastructure concern
  (`infrastructure/geo_reverse.py`, #741); addresses keyed/refreshed per active
  locale; overlay date formatting uses `model.locale` explicitly (#693).
- **Portrait pairs:** image-only, composed in memory, one shuffled slot. Videos
  are always single-item fullscreen (#618, #666).
- **Pause state:** `State.PAUSED` is the public paused state; visible pause
  status is renderer-owned; fades freeze while paused; active-video resume is
  in-place GStreamer state change (#701).
- **Hardware inputs:** `hardware_inputs` (BCM pins, payload-free commands only,
  reject `WAKE`/`SLEEP` → use `DISPLAY_ON`/`DISPLAY_OFF`, #705); PIR no-motion
  timers in `HardwareInputService` (#635, #703); saving is a replacement not
  merge (#702); display-power commands idempotent (#704).
- **Wake-on-input (#762):** a purpose-built `IWakeInputListener` port + backend
  `EvdevWakeAdapter` (lazy `evdev`, passive no-grab `/dev/input/event*` read,
  mouse+keyboard only, touch excluded) feeds `WakeOnInputService`, which publishes
  only `Command.DISPLAY_ON` (never `PLAY` — that side-effect stays owned by
  `DisplayPowerManager`) so the display wakes from the `wlr-randr --off`-destroyed
  state where the overlay's JS listeners cannot fire. Gated by the existing
  `overlay.enabled_input_types` (no new config key), idempotent via
  `IDisplayPower.is_on()`, 1 s cooldown debounce, live-reloads on overlay config
  change. `evdev>=1.6.0` is a Linux-only marker dependency (`sys_platform ==
  'linux'`); the installer already adds the `input` group it needs. Additive to,
  and distinct from, the GPIO/PIR `HardwareInputService`.
- **Video handoff:** require `gtk4paintablesink`; 99% opacity redraw handshake at
  EOS; no legacy sink fallbacks; final-frame extraction at indexing time, not
  EOS runtime; geometry from `content_rect` sidecar (#691/#698).
- **Settings UI:** domain editors only (no raw JSON for domain settings); live
  reload where possible; renderer backend toggles behind restart dialog;
  access scopes: none / Settings+Logs+admin / complete (#687).
- **Remote:** browser video preview only in expanded modal (not inline `<video>`,
  #699); brightness commands on commit/debounce (#694); clock hour mode is
  explicit `viewer.clock_format` (#695).
- **VLC:** diagnostic evidence only (#680); never a next-gen runtime dependency.
- **Frontend types:** `@typescript-eslint/no-explicit-any` is `error` (#743);
  use `errors.ts` helpers for catch handlers; keep scoped disables for the 5
  documented dynamic blobs.
- **Workflow:** ticketed changes (issue before code, ticket # in commits,
  commit hash on close); GitHub Issues/board authoritative; Conventional Commit
  PR titles.

## Tooling Note
- The GitHub MCP agent is configured and verified for `helgeerbe/picframe` and
  is the preferred path for GitHub-side workflow steps (issues, PRs, branches,
  commits, reviews, releases, comments). Both read-only and mutating
  operations are now exercised in production: PRs #744/#745/#746 were created,
  reviewed, merged, and closed; issues #736/#738/#741/#742/#743 were created,
  updated, and closed; branches were created/deleted; review comments and
  replies were posted. See `techContext.md` for the full operation list.

## Active Risks / Watch Items
- **Release readiness:** the `dev → main` release PR is deferred (user's call).
  `dev` is +62,857/−9,123 across 280 files vs `main`; `release.yml` will
  auto-tag (calver) + publish to PyPI + create the GitHub Release on push to
  `main`. Verify the release workflow end-to-end before relying on it.
- **Branch protection bypass:** the 3-line Sourcery fixup (`a307cec`) was
  pushed directly to `dev`, bypassing branch protection. This succeeded for the
  owner but may not always succeed; prefer PR-based flow for future fixes.
- **Test reliability:** environment-sensitive (display/media deps and Python
  version may differ from target); local Python 3.14 stack had Starlette/AnyIO
  threadpool deadlocks worked around test-only.
- **Memory Bank staleness:** keep files concise and current; summarize state
  rather than appending dated logs (this update did exactly that).
- **Spec vs. implementation:** some frontend/architecture docs may be
  aspirational; verify against `frontend/src` and `src/picframe` before
  assuming a feature is implemented.
