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
  validation on PRs to `dev`/`v2-dev`) and `release.yml` (calendar-version
  `YYYY.MM.DD[.postN]` tag, PyPI trusted publishing, GitHub Release with
  PR-title changelog from `dev → main` merges). The changelog builder config
  uses Conventional Commit type categories and PR links.
  `PULL_REQUEST_TEMPLATE.md` documents Conventional Commit titles and ticket
  linking. `docs/dev/workflow.md` is the developer workflow reference and is
  linked from `docs/README.md`. Branch protection rules are configured on
  GitHub: `helgeerbe` is a bypass actor (always) on both the
  `dev (incl v2-dev)` and `main` rulesets so the owner can self-merge PRs
  without review, while other maintainers still require 1 approving review;
  CI status checks remain required for all actors.

## Current / In Progress
- Phase 2 Control Plane/UI remains the broad current phase in local documentation; #648 is closed after the playlist-filter and Remote media-selection slice was implemented and verified.
- Video engine integration remains an active architectural stream: caps-driven hardware discovery, fallback observability, software fallback limits, and Raspberry Pi/labwc validation of the GTK4 handoff behavior.
- #691 is merged into `v2-dev`, pushed to `origin/v2-dev`, and closed. Additional Raspberry Pi/labwc validation of the handoff behavior remains useful target coverage.
- #635 remains open for Raspberry Pi manual validation and final closeout decision after implementation verification.

## Next
- Continue caps-driven hardware capability discovery in the GStreamer worker, with Pi V4L2 probing enabled before worker startup.
- Validate more H.264 1080p60 and HEVC container variants before relaxing additional guards.
- Surface software fallback / unsupported-media decisions as events visible to logs and the UI.
- Continue Raspberry Pi/labwc validation of GTK4 video handoff timing, especially EOS redraw behavior and custom display geometry.
- Reconcile frontend specification with actual implemented UI and fill gaps only through tracked issues.
- Keep legacy import documentation aligned with the explicit UI/API import path rather than adding a separate `picframe migrate` command unless a new tracked requirement asks for headless migration.

## Known Verification State
- Latest backend verification on `v2-dev` (2026-06-19): `.venv/bin/python -m pytest` passed with 640 tests and 1 GI deprecation warning.
- Latest frontend verification on `v2-dev` (2026-06-19): `npm run build` passed, with only sandbox stream-fd warnings before Vite completed.
- Latest video hardening verification on this workspace: touched-file Ruff passed, and `.venv/bin/python -m pytest test/core/metadata/test_video_strategy.py test/core/services/test_media_indexer.py test/core/renderers test/core/engine/test_playback.py` passed with 123 tests.
- Latest #691 cleanup verification: `.venv/bin/python -m pytest test/core/utils/test_video_frame_extractor.py test/core/engine/test_playback.py test/core/renderers/test_gst_pipeline_builder.py test/core/renderers/test_gst_video_renderer.py test/core/renderers/test_gst_worker.py test/core/renderers/test_gtk_video_presenter.py` passed with 190 tests; targeted Ruff correctness check passed.
- Latest #693 target verification: `.venv/bin/python -m pytest test/core/repositories/test_sqlite_media.py test/core/services/test_geocoding_worker.py test/core/services/test_locale_utils.py test/core/services/test_renderer_config.py test/core/engine/test_playback.py test/core/renderers/test_pi3d_renderer.py test/api/test_app.py` passed with 189 tests; `git diff --check` and targeted Ruff on the new locale helper tests passed.
- Latest #694 target verification: `.venv/bin/python -m pytest test/infrastructure/os/test_wayland_power.py test/test_remote_brightness_controls.py` passed with 13 tests; targeted Ruff for the touched Python files passed.
- Latest #695 target verification: `.venv/bin/python -m pytest test/test_settings_clock_format_controls.py` passed with 2 tests; targeted Ruff for the new source guard passed.
- Latest #696 target verification: `.venv/bin/python -m pytest test/core/repositories/test_sqlite_media.py` passed with 23 tests; targeted Ruff for the touched media repository files passed.
- Latest #697 target verification: `.venv/bin/python -m pytest test/core/repositories/test_sqlite_media.py test/core/services/test_playlist.py test/api/test_app.py` passed with 96 tests; targeted Ruff for the touched Python files passed.
- Latest #698 target verification: `.venv/bin/python -m pytest test/core/utils/test_mat_image.py test/core/utils/test_video_frame_extractor.py test/core/engine/test_playback.py test/core/renderers/test_pi3d_renderer.py test/core/events/test_dto.py` passed with 164 tests; full `.venv/bin/python -m pytest` passed with 645 tests and 1 GI deprecation warning; targeted Ruff for touched Python files and `git diff --check` passed.
- Latest #699 verification: full `.venv/bin/python -m pytest` passed with 662 tests and 1 GI deprecation warning; focused `.venv/bin/python -m pytest test/api/test_app.py test/test_remote_brightness_controls.py` passed with 67 tests; targeted Ruff for touched Python files passed; `npm run build` passed with the known sandbox stream-fd warnings before Vite completed; `git diff --check` passed.
- Latest #701 paused-overlay verification: focused resume regression tests (`test_parse_resume_command`, `test_pause_resume_video`, `test_resume_request_resumes_existing_pipeline`, `test_pause_request_prevents_async_done_from_resuming_pipeline`) passed with 4 tests after adding explicit resume IPC. Focused fade-freeze and text-timer regressions for animation controller, playback pause/resume, and pi3d renderer passed with 7 tests; broader `.venv/bin/python -m pytest test/core/renderers/test_animation_controller.py test/core/renderers/test_pi3d_renderer.py test/core/engine/test_playback.py` passed with 130 tests. The expanded #701 suite `.venv/bin/python -m pytest test/core/renderers/test_animation_controller.py test/core/renderers/test_gst_worker.py test/core/renderers/components/test_text_renderer.py test/core/renderers/test_pi3d_renderer.py test/core/engine/test_playback.py test/core/renderers/test_gst_video_renderer.py test/core/renderers/test_gtk_video_presenter.py` passed with 234 tests; targeted Ruff for touched Python files passed. The latest pending-video pause race guard `.venv/bin/python -m pytest test/core/engine/test_playback.py test/core/renderers/test_animation_controller.py test/core/renderers/test_pi3d_renderer.py test/core/renderers/test_gst_video_renderer.py test/core/renderers/test_gst_worker.py test/core/renderers/test_gtk_video_presenter.py` passed with 226 tests; full `.venv/bin/python -m pytest` passed with 690 tests and 1 GI deprecation warning.
- Latest #705 verification: backend hardware-input validation and the Settings
  GPIO source guard reject/exclude unsupported `WAKE`/`SLEEP` selections while
  preserving `DISPLAY_ON`/`DISPLAY_OFF`; the active `Command` enum no longer
  includes the legacy names; focused event/hardware/API pytest passed with 101
  tests; full `.venv/bin/python -m pytest` passed with 699 tests and 1 GI
  deprecation warning; targeted Ruff, `npm run build`, and `git diff --check`
  passed.
- Latest #708 verification: `.venv/bin/python -m pytest` passed with 700 tests
  and 1 GI deprecation warning; targeted Ruff for
  `src/picframe/core/repositories/sqlite_config.py` and
  `test/core/repositories/test_sqlite_config.py` passed; `git diff --check`
  passed.
- Latest #714 verification: targeted
  `.venv/bin/python -m pytest test/core/engine/test_playback.py` passed; ruff
  format/check and mypy on touched files passed; `git diff --check` passed.
- Latest #716 verification: full `.venv/bin/python -m pytest` passed with 721
  tests and 1 GI deprecation warning; targeted
  `.venv/bin/python -m pytest test/core/renderers/components/test_clock_renderer.py
  test/core/events/test_dto.py test/core/engine/test_playback.py test/api/test_app.py`
  passed; ruff format/check passed after import ordering fix; `git diff --check`
  passed.
- Latest #680/#668 target diagnostics: docs/user/video-format-validation.md summarizes VLC and GStreamer file matrices, including Pi V4L2 probing, DMABuf hardware success, validated HEVC MKV 4K60, and guarded MOV/Main10 paths.
- Latest #719 verification: full `.venv/bin/python -m pytest` passed with 753
  tests and 1 GI deprecation warning; focused text/clock renderer tests passed
  with 30 tests including the z-order fix and the rebuild-on-text-change case;
  `ruff check` and `mypy` passed clean on touched files; `git diff --check`
  passed. Remaining: docs z-order convention, frontend rebuild, commit, push,
  ticket close, and Discussion #682 comment.
