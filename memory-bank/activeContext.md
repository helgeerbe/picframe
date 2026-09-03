# Active Context

## Current Focus
Implementing **issue #739** — the WebKitGTK touch overlay + plugin system — on
feature branch `feat/739-webkit-overlay` (cut from `dev` `4217f6e`). The six
locked design decisions are recorded in `decisionLog.md` (out-of-process
worker mirroring `gst_worker.py`, opacity-based hide/wake with
`idle_hide_seconds`, `OverlayConfig` Pydantic model, `wlr-layer-shell`,
`file://` load model, `OverlayConfigChangedEvent` distinct from
`RENDER_UPDATE_OVERLAY`, parallel Pointer+keyboard input, Vite multi-page).

**Prerequisite done:** issue **#749** (remove dead legacy `peripherals` config
section) is implemented and committed (`5924130`) on the feature branch.

**Phase 0 DONE + committed** (`4393ffd`, pushed to `origin`): #739 task list
items 1–7, TDD throughout, all gates green. The config + port + API foundation
is in place: `overlay` section in `default_config.yaml`, Pydantic `OverlayConfig`
on `AppConfig`, `ConfigService` overlay read-whitelist + scoped
`update_plugin_config` + `OverlayConfigChangedEvent` publishing,
`PluginDescriptor` core DTO + `validate_plugin_config`/`plugin_config_defaults`,
`IOverlayController` port, `PluginLoader` adapter, and the three overlay API
endpoints. Also fixed a pre-existing seed bug
(`viewer.clock_extra_source: off` → `'off'` YAML 1.1 bool coercion).

**Phase 1 backend DONE (committed, pending push):** #739 items **9, 12, 13**
complete + tested (40 new tests, all gates green: ruff, ruff format 161 files,
mypy strict 87 files, **pytest 873 passed**):
- `core/renderers/overlay_ipc.py` — overlay IPC protocol (SetOpacity/SetConfig/
  Reload/Shutdown commands; Ready/Input/Error events) + parser.
- `core/renderers/webkit_overlay_renderer.py` — `WebKitOverlayRenderer`
  (`IOverlayController` IPC client): spawns `overlay_worker.py` via
  `subprocess.Popen`, AF_UNIX socket IPC, listener thread republishing worker
  `InputEvent` → `CommandEvent`, subscribes to `OverlayConfigChangedEvent`
  (forward SetConfig) + `RenderCommand` (video reveal actions → opacity),
  graceful-degradation probe publishing `SystemErrorEvent(code="webkit_unavailable")`.
- `infrastructure/overlay/overlay_worker.py` — out-of-process worker: guarded
  `gi`/Gtk/WebKit import, GLib MainLoop + WebKitGTK WebView + JS bridge
  (`window.picframe`), GTK-free IPC plumbing (`handle_command`/`_serve`)
  unit-tested headless.
- `main.py` — composition-root wiring behind `overlay.enabled` +
  `is_available()`; `overlay_controller` injected into `create_app`;
  start/stop in both shutdown paths.

**Phase 1 still open:** task **8** — worker uses a plain borderless `Gtk.Window`
(transparent) rather than `wlr-layer-shell`, and the Phase-1 spike
(`file://`→`ws://localhost` cross-origin WS + `wlr-layer-shell` on labwc) still
needs a real Wayland display to validate. Tasks **10** (overlay HTML shell,
Vite multi-page → `src/picframe/html/overlay/`) and **11** (pointer + keyboard
input routing) are the next chunk (frontend/WebKit-dependent).

Then Phase 2 (frontend Remote/Appearance panels), Phase 3 (built-in plugins),
Phase 4 (tests + docs).

## Current Repo State
- Branch: `feat/739-webkit-overlay`, HEAD `4393ffd` (Phase 0) + uncommitted
  Phase 1 backend changes (items 9/12/13), pushed to `origin` (through `4393ffd`).
- Cut from `dev` at `4217f6e` (chore: remove stale v2-dev references, #747).
  `dev` tip is `4217f6e`; `main` release PR remains deferred.
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
