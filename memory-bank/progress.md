# Progress

## Status Summary
GitHub Issues and the GitHub Project board are the authoritative progress tracker. This file is only a compact local summary for agent restarts.

## Completed / Substantially Implemented
- Phase 0: GStreamer video handoff proof of concept.
- Phase 1: Core image MVP / walking skeleton.
- Modern packaging via `pyproject.toml` and `setuptools_scm`.
- PriorityQueue event bus with immutable DTOs and split publisher/subscriber interfaces.
- Dual SQLite repositories with migrations.
- Playlist/media processing foundation.
- FastAPI control plane with config endpoints, WebSocket state, SPA serving, media serving, and system/maintenance commands.
- Ticket #637 control-plane hardening: Vite builds the Vue SPA into packaged FastAPI assets, `picframe init` copies the compiled UI into the runtime directory, FastAPI serves SPA routes/assets, and WebSocket media DTO location enrichment uses the injected media repository instead of hardcoded cache DB paths.
- Vue 3 SPA foundation with Remote, Appearance, Settings, and Logs views.
- Settings UI fail-safe redesign: Settings now uses dedicated domain editors, safe host path browsing/validation rooted at the Picframe user's home directory, token/chip editors, sort-rule rows, a geocoding location-format builder, color controls, shortcut capture, fixed metadata/extension lists, shader basename selection, password reveal controls, and collapsed Advanced sections.
- Ticket #635 hardware-input configuration: Settings now has a dedicated GPIO Inputs editor, `hardware_inputs` is validated through backend/core config paths, and `HardwareInputService` is wired into the runtime with adapter reconfiguration on Settings changes. PIR `no_motion_delay_seconds` delays no-motion commands and is cancelled by renewed motion.
- Remote Media Selection block for playlist runtime filters; Appearance owns timing controls.
- Remote filter option chips toggle selected terms; normal click appends/toggles with `OR`, Shift-click appends with `AND`, and long tag/location option lists scroll in-place.
- Remote Shuffle moved from Media Selection to an immediate split transport control: the main segment saves `model.shuffle`, the menu persists `model.shuffle_mode`, and missing/invalid modes fall back to `standard`.
- Remote transport controls use a balanced touch-first deck, and helper text icons are clickable/tappable with dialog fallback.
- Config-driven next-gen playlist querying for subdirectory, date range, legacy-compatible location/tag boolean filters, shuffle, recent priority, reshuffle cadence, and safe `sort_cols`.
- Live Remote media-selection count preview with selected-count / folder-scope total-count semantics.
- Legacy display statistics parity in the media cache: `displayed_count` and `last_displayed`, shown in Remote metadata.
- Ticket #618 playlist parity follow-ups for clickable current-media tags in Remote, managed video transition frame cache artifacts, Clear Image Cache API/service wiring, video playback resilience after cache clearing, portrait-pair display items/rendering/Remote UX, pair delete target selection, internal monitor/indexer/processing lifecycle controls, and real-media Raspberry Pi validation.
- Media cache lifecycle cleanup: restart sync skips unchanged files, reindexes only new/changed/restored files, temporary missing files are soft-inactivated and skipped, explicit Remote delete moves originals to `deleted_pictures` and removes cache rows, and display counters are preserved across reindex/restart.
- Ticket #611 clean-architecture cleanup: media monitoring now uses a core `IMediaMonitor` port, watchdog is isolated in an infrastructure adapter, differential sync publishes core `FileChangeEvent`s directly, and indexer config-change wiring uses `set_directories()`.
- Ticket #619 next-gen matting parity: matting Settings fields now flow into renderer config, single images and image-only portrait pairs can be matted in memory with legacy `MatImage`, live video playback remains unmatted, and `ImageProcessingService` no longer owns matting responsibilities.
- Ticket #666 shuffle mode: `standard` keeps current random behavior, `fewer_repeats` uses existing `last_displayed` history after display-slot creation, portrait pairs remain one shuffle slot, and Remote exposes a split shuffle button.
- Ticket #616 cleanup gate: package CLI now targets next-gen `picframe.main`, `SystemErrorEvent` poison-pill semantics are explicit, VLC is no longer a next-gen dependency, integration coverage was added, and manual Picframe validation passed before closeout.
- Ticket #678 audited cleanup: legacy controller/model/start/viewer/HTTP/peripheral/VLC runtime modules and their obsolete tests were removed; MQTT/Home Assistant is now a next-gen infrastructure adapter using event bus, config, and state-query ports.
- Repository hygiene: root-level debug test scripts were removed, `README.md` remains the only root Markdown document, user docs live under `docs/user/`, and developer architecture notes live under `docs/dev/architecture/`.
- Display power/system manager HAL work and Wayland-oriented environment detection.
- Video metadata extraction and frontend display of video technical metadata.
- First/Last Frame Sandwich pattern implementation work is present in recent commit history.
- Video indexing hardening: unprobeable videos, invalid probe JSON, and files with no video stream are skipped/marked inactive; stale placeholder video rows are revalidated; transition-frame cache failures no longer block otherwise playable videos; the GStreamer worker preflights discoverability before creating a sink.
- Raspberry Pi 4 GStreamer hardware playback validation: `GST_V4L2_ENABLE_PROBE=1` exposes `v4l2h264dec` and `v4l2slh265dec`; H.264 1080p and HEVC Main 8-bit 4K paths play with DMABuf and EOS. HEVC Main 8-bit MKV 4K60 plays in the standalone GStreamer `playbin` probe, while MOV/QuickTime 60 fps and Main10/HDR MOV remain guarded.
- GTK4 Wayland video handoff: production playback requires GTK4 `playbin`/GTK-compatible `gtk4paintablesink`, supports fullscreen and custom geometry, uses a 99% GTK4 window-opacity redraw handshake at EOS, gates last-frame reveal promotion on a rendered video frame when sink stats expose it, and waits for video title-card overlay text to fade out before starting GStreamer.
- Ticket #691 video transition-frame handoff: cached first/last frames now honor viewer matting, `blur_edges`, `edge_alpha`, and `background` settings; sidecars store current visible-opening frame geometry (`frame_size`, `coordinate_space`, `content_rect`), playback uses that rect for the live video window across matted, solid-bar, edge-filled, blurred, and fit-display frames, explicit `content_fit` flows through IPC/pipeline construction, and caches regenerate when signatures or geometry metadata are stale.
- Issue #689 worker refactor split GStreamer responsibilities into playback policy, GTK4 presenter, and pipeline builder modules while preserving the existing IPC protocol and user-visible behavior.
- Ticket #690 display geometry apply fix: Wayland fullscreen-host geometry changes avoid in-process pi3d display remapping; the renderer rebuilds image/text/clock components on the existing display surface. Runtime renderer settings are now classified as live refresh, existing-display component rebuild, or explicit service restart. Backend toggles `viewer.use_glx`/`viewer.use_sdl2` use a Settings restart-required dialog with optional `picframe.service` restart only when the managed service is active.
- Legacy `configuration.yaml` import follow-ups #676/#677 are complete: the Settings UI/API path is documented, `viewer.show_text` is normalized into next-gen overlay keys, `mqtt.port` is preserved, and legacy startup-only HTTP keys are intentionally ignored.
- Ticket #687 Settings coverage/live reloads: Settings adds display Fullscreen/Custom geometry, installed-locale dropdown, additional durable renderer/model controls, and fixes `geo_suppress_list` to `viewer`; Remote adds frontend-only media/map enlargement and search-first location filtering with selected chips; backend adds `/api/system/locales` and `/api/media/location-options`; Settings Apply uses component reload/reconnect paths instead of a full service restart.
- Ticket #687 visible-settings audit: `model.recent_n` and `model.reshuffle_num` are confirmed playlist-backed; `model.locale` now feeds reverse-geocoding language; renderer text/clock/blur/video-fit settings now flow into runtime config paths. Runtime logging controls are restored through live `model.log_level`/`model.log_file` handling and a protected Logs tab. Compatibility-only hidden Settings keys are documented: `viewer.display_power`, old menu fields, `model.update_interval`, HTTP SSL fields, legacy HTTP auth fields, and legacy `peripherals.*`. `model.image_attr` remains hidden because MQTT now publishes all normalized current-media attributes.
- Ticket #693 geolocation/locale fix is closed: reverse-geocoded locations and the persistent lookup queue are keyed by normalized language, existing unknown-language cached rows migrate to a `legacy` bucket, GPS media without active-locale address text retry lookup during overlay generation, playlist/API location metadata resolve for `model.locale`, and playback/pi3d overlay dates format through explicit locale handling.
- Ticket #694 brightness hardening is closed: internal display outputs use `brightnessctl`, HDMI/DDC brightness probes VCP 0x10 before writing, command output is included in `brightness_unavailable` errors, repeated identical failures are suppressed, Remote brightness drags preview locally and commits one hardware command on release/change, and docs explain DDC prerequisites plus monitor brightness floors.
- Ticket #695 clock hour mode is closed: Settings exposes 24-hour, 12-hour, and Custom clock choices while persisting only `viewer.clock_format`; locale does not drive clock hour mode.
- Ticket #696 media repository locking is closed: `SQLiteMediaRepository` serializes shared SQLite connection use so API location enrichment no longer races geocoding/indexer/playback access to `media_cache.db3`.
- Ticket #697 media selection performance is closed: indexed filepath/date/location query paths speed playlist rebuilds and selected-count checks while preserving existing Remote/API behavior.
- Ticket #698 fixes beveled/matted video handoff alignment: `content_rect` now comes from the visible video opening after frame/shadow effects instead of the larger logical source plane, transition-frame processing version 6 invalidates version-5 matted sidecars with frozen edge pixels, generated video transition frames black source-influenced pixels outside `content_rect` without changing still-image matting, manual video navigation uses the tokened first-frame handoff path, stale transition completions are ignored, direct fallback uses cached sidecar metadata when available instead of forcing fullscreen playback, and matted/edge-filled or otherwise inset video rects use an opaque GTK host so non-video regions do not reveal stale pi3d pixels on Pi/labwc.
- Ticket #701 Remote pause-state and paused-overlay fix: `PlaybackEngine` now publishes `State.PAUSED` for pause, legacy `PAUSE` toggles back to play when already paused, still-image and in-flight pi3d fade pauses send a `PAUSED` status overlay, image/video-title-card transitions freeze while paused, pending first-frame video handoff is deferred until resume, a started-but-not-yet-promoted pending video is paused/resumed through GStreamer and promoted safely if its first-frame event arrives while paused, active videos call GStreamer pause/resume and show a GTK video-window `PAUSED` label, video resume continues the existing paused pipeline instead of replaying the clip, Remote derives its play/pause icon from backend `StateEvent`s, and display off/on/toggle publish the corresponding pause/play follow-up command.
- Ticket #702 GPIO type-switch persistence fix: saving `hardware_inputs` now
  replaces the old flat `hardware_inputs.*` section before writing normalized
  values, preventing stale PIR/button actions from blocking Settings saves after
  a GPIO input type change.
- Ticket #703 PIR startup no-motion fix: enabled PIR inputs with delayed mapped
  `no_motion` actions now start that timer when hardware monitoring starts or
  reloads, so a quiet room after boot can still turn the display off.
- Ticket #704 display-power idempotency fix: repeated `DISPLAY_ON` while the
  display is already live no longer publishes a duplicate `PLAY`, and repeated
  `DISPLAY_OFF` while already blanked no longer publishes a duplicate `PAUSE`.
- Ticket #705 GPIO action cleanup: unsupported legacy-style `WAKE`/`SLEEP`
  selections are removed from the active command enum and Settings GPIO dropdown
  and rejected by backend hardware input validation; PIR screen power remains
  `DISPLAY_ON`/`DISPLAY_OFF`.
- Ticket #708 config repository locking fix: `SQLiteConfigRepository` now
  serializes all shared SQLite connection use with an `RLock`, including
  migrations, reads, writes, directory operations, and close, preventing
  long-running playback/API races that can surface as `sqlite3.InterfaceError`
  during live config reads.
- Ticket #714 overlay date fallback fix: `PlaybackEngine._generate_text_string()`
  now uses the media item's `last_modified` timestamp when `exif_datetime` is
  missing or None, so images without EXIF dates still display a date in the text
  overlay. Raised by paddywwoof in Discussion #682.
- Ticket #716 clock extra text support: `viewer.clock_extra_source`
  (off/clock_txt/ui_text) and `viewer.clock_extra_text` are added to the Viewer
  Pydantic model, OverlayConfig DTO, renderer config propagation, clock renderer
  implementation, legacy YAML import mapping, `default_config.yaml`, and
  frontend `configSchema.json`. The clock
  renderer reads `/dev/shm/clock.txt` when the source is `clock_txt` and shows
  the UI-configured string when the source is `ui_text`; `off` shows no extra
  line. Tests cover DTO propagation, renderer behavior for all three sources,
  legacy import mapping, and frontend schema presence.
- Ticket #719 alpha-test bug fixes (reported by Paddy/@paddywwoof):
  (1) `text_renderer.py` gradient sprite z-order fixed — gradient moved behind
  text (z=0.3 vs text z=0.1; status overlay z=0.05 in front), full-render-height
  texture scaled on GPU via `sprite.scale()` so it is not rebuilt when band
  height changes; (2) `clock_extra_source` is now propagated through
  `OverlayConfig` in `playback.py`, and `ClockRenderer` re-reads
  `/dev/shm/clock.txt` dynamically on each `has_changed()`/`draw()` call; (3)
  `ImageMetadataStrategy` and `VideoMetadataStrategy` fall back to
  `last_modified` at indexing time when no EXIF/creation date is found, so the
  DB always has a valid `exif_datetime` and date-range SQL filters work
  without runtime fallbacks. Tests updated for text renderer, clock renderer,
  image strategy, video strategy, and playback. A follow-up fix added
  `clock_extra_text` to the clock renderer's visual signature so the clock
  block is invalidated when only the text changes (not just the source); test
  coverage added for the rebuild-on-text-change case.
- Ticket #706 CI/CD and developer workflow modernization: legacy
  `test.yml` (flake8 push), `python-publish.yml` (tag-triggered), and the
  placeholder `pr-checks.yml` are replaced by `ci.yml` (ruff, mypy, pytest,
  frontend bundle drift, package build, Conventional Commit PR title
  validation on PRs to `dev`) and `release.yml` (calendar-version
  `YYYY.MM.DD[.postN]` tag, PyPI trusted publishing, GitHub Release with
  PR-title changelog from `dev → main` merges). The changelog builder config
  uses Conventional Commit type categories and PR links.
  `PULL_REQUEST_TEMPLATE.md` documents Conventional Commit titles and ticket
  linking. `docs/dev/workflow.md` is the developer workflow reference and is
  linked from `docs/README.md`. Branch protection rules are configured on
  GitHub: `helgeerbe` is a bypass actor (always) on both the
  `dev` and `main` rulesets so the owner can self-merge PRs
  without review, while other maintainers still require 1 approving review;
  CI status checks remain required for all actors.
- Ticket #724 purge orphaned directory rows: `PURGE_FILES` now calls
  `PlaylistManager.purge_orphaned_directories()`, which queries active
  directory IDs from the media repository and removes directory rows in the
  config repository that no longer have any non-deleted media referencing them.
  - Ticket #725 XMP subject Seq/li fallback: `ImageMetadataStrategy._get_xmp_data()`
  now extracts XMP subject keywords from either Bag/li (common) or Seq/li
  (ACDSee Photo Studio on Mac) via a new static `_extract_xmp_subject_tags()`
  helper, and handles both list and single-string `li` values. Tests cover
  Bag/li list, Seq/li list, Bag/li single string, Seq/li single string,
  missing-both, and Bag-preferred-over-Seq cases. The fix preserves existing
  Bag/li behavior as the first-choice path.
- Ticket #726 `viewer.show_text_on_video` (default `False`): when disabled,
  the playback engine suppresses only the metadata text overlay for video
  media via `dataclasses.replace()` so clock and status overlays are preserved
  and GStreamer starts without waiting for `show_text_tm` fade-out. The setting
  flows through `RendererConfig`, `default_config.yaml`, API `ViewerConfig`,
  live-update keys in `app.py`, MQTT Home Assistant switch discovery,
  `configSchema.json`, the `TextOverlayControls` Vue component, and en/de i18n
  strings. Tests cover the renderer config mapping, playback handoff overlay
  suppression, and pi3d renderer behavior. Two bugfixes were included: (1)
  `Pi3dRenderer.execute()` now copies `show_text` from the incoming overlay, and
  (2) `_handle_state_event` preserves `show_text=False` through
  `CurrentMediaChangedEvent` instead of resetting it from config. Merged via
  PR #733 (squash-merged into `v2-dev`, feature branch deleted).
- Ticket #710 GStreamer worker Wayland enforcement (two stages): (1)
  limited-range YUV thumbnail extraction fixed on `v2-dev` in commit b66a9134
  via the `-strict unofficial` ffmpeg flag in `VideoFrameExtractor`; (2) the
  green-screen / segfault from the GStreamer worker falling back to Xwayland
  fixed by `GstVideoRenderer._worker_environment()` enforcing
  `GDK_BACKEND=wayland`, dynamically detecting a single `wayland-*` socket in
  `XDG_RUNTIME_DIR` when `WAYLAND_DISPLAY` is missing (warns on zero/multiple),
  logging display env vars before GTK4 init, and hinting at a GTK4/Wayland
  display-init failure for signal-killed workers. Merged via PR #731
  (squash-merged into `v2-dev`, commit 69b2445, feature branch deleted). The
  reporter's on-device crash was not re-confirmed; merged on owner judgment.
- **`v2-dev → dev` transition (PR #737):** the full Picframe 2.0 modernization
  merged into `dev`. Pre-merge cleanup issues #736 (frontend lint/format) and
  #738 (ESLint + Prettier + CI gate baseline) closed.
- **#741 — geo_reverse relocation:** moved `geo_reverse.py` →
  `infrastructure/geo_reverse.py` (PR #744, `b5e8a1f`). Reverse geocoding is now
  an infrastructure concern behind the existing geocoding port.
- **#742 — mat_image relocation:** moved `mat_image.py` →
  `core/utils/mat_image.py` (PR #745, `989f186`). Matting helper now lives with
  the other renderer utility modules in core.
- **#743 — no-explicit-any tightening:** `@typescript-eslint/no-explicit-any`
  raised from `warn` → `error` (PR #746, `9b86cf8`). 52 warnings converted to
  `unknown`/typed via new `errors.ts` helpers (`getErrorMessage`,
  `getApiErrorMessage`); 20 `catch (e: any)` → `catch (e: unknown)`; 5
  genuinely-dynamic blobs kept with scoped disables + rationale. A Sourcery
  review nit on `getErrorMessage` was addressed in follow-up commit `a307cec`.
- **#749 — remove dead `peripherals` config section** (prerequisite for #739,
  branch `feat/739-webkit-overlay`, `5924130`): removed the unused legacy
  `peripherals` block from backend models/config/service/app, frontend
  `configSchema.json`/locales, tests, and docs; SPA rebuilt. Note: Pydantic v2
  default `extra='ignore'` silently drops unknown YAML keys (no validation
  error), so the issue's "blocks `picframe init`" wording is imprecise — the
  real failure mode is silent default-drop. `update_nested_config` has no write
  whitelist (persists any section); only `get_nested_config` filters on read.
  Tests were updated to use the `http` section instead of `peripherals`.

## Current / In Progress
- **#739 — WebKitGTK touch overlay + plugin system** (feature branch
  `feat/739-webkit-overlay`, cut from `dev` `4217f6e`). Six locked design
  decisions recorded in `decisionLog.md`. Prerequisite **#749** (remove dead
  `peripherals` config section) is complete and committed (`5924130`):
  `peripherals` removed from backend models/config/service/app, frontend
  `configSchema.json`/locales, tests, and docs; SPA rebuilt; all gates green
  (ruff, ruff format, mypy, pytest 801 passed, yarn lint/format/tsc/build);
  pushed to `origin`. Currently in Step 0d (memory-bank refresh) before
  starting Phase 0 (#739 task list items 1–7): `overlay` section in
  `default_config.yaml`, `OverlayConfig` Pydantic model, `ConfigService`
  flatten/unflatten + whitelist, `PluginDescriptor` DTO + `IOverlayController`
  port, plugin manifest loader, overlay API endpoints,
  `OverlayConfigChangedEvent`.

## Next
- **#739 Phase 0** (next): the config + port + API foundation (items 1–7
  above), TDD throughout. Then Phases 1–4 (worker + IPC, composition-root
  wiring, frontend panels, built-in plugins, docs).
- **`dev → main` release PR** (deferred, user's call): `dev` is
  +62,857/−9,123 across 280 files vs `main`. Pushing to `main` triggers
  `release.yml` (calver auto-tag + PyPI trusted publishing + GitHub Release
  with PR-title changelog categories). Verify the release workflow
  end-to-end before relying on it.
- **Done:** superseded `v2-dev` branch deleted (local + remote, `cb69484`);
  all commits preserved on `dev`.

## Known Verification State
- Backend: `.venv/bin/python -m pytest` ran green (801 passed) on
  `feat/739-webkit-overlay` after #749. ruff, ruff format, and mypy strict
  were clean. (Earlier `dev` baseline: 753 tests on the `v2-dev` line before the
  merge; counts grew through the modernization and should be re-verified
  before the release.)
- Frontend: `yarn build` + `yarn lint` + `yarn format:check` + `vue-tsc -b`
  pass clean on `feat/739-webkit-overlay` after #749.
- Current `feat/739-webkit-overlay` head: `5924130` (refactor(#749): remove
  dead legacy `peripherals` config section).
- Current `dev` head: `4217f6e` (chore: remove stale v2-dev references, #747).

