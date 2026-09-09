# Active Context

## Current Focus
**PR #754 (WebKitGTK touch overlay + plugin system) squash-merged to `dev`
as `6ec7c74`.** Nine issues closed manually: #739, #750, #751, #752, #757,
#758, #759, #760, #761. The feature branch `feat/739-webkit-overlay` has been
deleted; all work is now on `dev`.

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
