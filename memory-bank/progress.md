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
- Vue 3 SPA foundation with Remote, Filters, and Settings views.
- Settings UI fail-safe redesign: Settings now uses dedicated domain editors, safe host path browsing/validation rooted at the Picframe user's home directory, token/chip editors, sort-rule rows, a geocoding location-format builder, color controls, shortcut capture, fixed metadata/extension lists, shader basename selection, password reveal controls, and collapsed Advanced sections.
- Ticket #635 hardware-input configuration: Settings now has a dedicated GPIO Inputs editor, `hardware_inputs` is validated through backend/core config paths, and `HardwareInputService` is wired into the runtime with adapter reconfiguration on Settings changes. PIR `no_motion_delay_seconds` delays no-motion commands and is cancelled by renewed motion.
- Remote Media Selection block for playlist runtime filters and timing controls.
- Remote filter option chips toggle selected terms; normal click appends/toggles with `OR`, Shift-click appends with `AND`, and long tag/location option lists scroll in-place.
- Remote Shuffle moved from Media Selection to an immediate split transport control: the main segment saves `model.shuffle`, the menu persists `model.shuffle_mode`, and missing/invalid modes fall back to `standard`.
- Remote transport controls use a balanced touch-first deck, and helper text icons are clickable/tappable with dialog fallback.
- Config-driven next-gen playlist querying for subdirectory, date range, legacy-compatible location/tag boolean filters, shuffle, recent priority, reshuffle cadence, and safe `sort_cols`.
- Live Remote media-selection count preview with selected-count / folder-scope total-count semantics.
- Legacy display statistics parity in the media cache: `displayed_count` and `last_displayed`, shown in Remote metadata.
- Ticket #618 playlist parity follow-ups for clickable current-media tags in Remote, managed video transition frame cache artifacts, Clear Image Cache API/service wiring, video playback resilience after cache clearing, portrait-pair display items/rendering/Remote UX, pair delete target selection, internal monitor/indexer/processing lifecycle controls, and real-media Raspberry Pi validation.
- Media cache lifecycle cleanup: restart sync skips unchanged files, reindexes only new/changed/restored files, temporary missing files are soft-inactivated and skipped, explicit Remote delete moves originals to `deleted_pictures` and removes cache rows, and display counters are preserved across reindex/restart.
- Ticket #611 clean-architecture cleanup: media monitoring now uses a core `IMediaMonitor` port, watchdog is isolated in an infrastructure adapter, differential sync publishes core `FileChangeEvent`s directly, and indexer config-change wiring uses `set_directories()`.
- Ticket #619 next-gen matting parity: matting Settings fields now flow into renderer config, single images and image-only portrait pairs can be matted in memory with legacy `MatImage`, video paths remain unmatted, and `ImageProcessingService` no longer owns matting responsibilities.
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
- Issue #689 worker refactor split GStreamer responsibilities into playback policy, GTK4 presenter, and pipeline builder modules while preserving the existing IPC protocol and user-visible behavior.
- Legacy `configuration.yaml` import follow-ups #676/#677 are complete: the Settings UI/API path is documented, `viewer.show_text` is normalized into next-gen overlay keys, `mqtt.port` is preserved, and legacy startup-only HTTP keys are intentionally ignored.
- Ticket #687 Settings coverage/live reloads: Settings adds display Fullscreen/Custom geometry, installed-locale dropdown, additional durable renderer/model controls, and fixes `geo_suppress_list` to `viewer`; Remote adds frontend-only media/map enlargement and search-first location filtering with selected chips; backend adds `/api/system/locales` and `/api/media/location-options`; Settings Apply uses component reload/reconnect paths instead of a full service restart.
- Ticket #687 visible-settings audit: `model.recent_n` and `model.reshuffle_num` are confirmed playlist-backed; `model.locale` now feeds reverse-geocoding language; renderer text/clock/blur/video-fit settings now flow into runtime config paths. Runtime logging controls are restored through live `model.log_level`/`model.log_file` handling and a protected Logs tab. Compatibility-only hidden Settings keys are documented: `viewer.display_power`, old menu fields, `model.update_interval`, HTTP SSL fields, legacy HTTP auth fields, and legacy `peripherals.*`. `model.image_attr` remains hidden because MQTT now publishes all normalized current-media attributes.

## Current / In Progress
- Phase 2 Control Plane/UI remains the broad current phase in local documentation; #648 is closed after the playlist-filter and Remote media-selection slice was implemented and verified.
- #687 implementation is in verification/closeout: Settings coverage, live reloads, Remote enlargement/filtering, `model.image_attr` compatibility docs, live logging, Logs tab, three-scope Basic Auth with cookie-backed WebSocket auth plus documented password recovery, and legacy peripherals documentation are being verified before commit/issue closeout.
- Video engine integration remains an active architectural stream: caps-driven hardware discovery, fallback observability, software fallback limits, and Raspberry Pi/labwc validation of the GTK4 handoff behavior.
- #635 remains open for Raspberry Pi manual validation and final closeout decision after implementation verification.

## Next
- Continue caps-driven hardware capability discovery in the GStreamer worker, with Pi V4L2 probing enabled before worker startup.
- Validate more H.264 1080p60 and HEVC container variants before relaxing additional guards.
- Surface software fallback / unsupported-media decisions as events visible to logs and the UI.
- Continue Raspberry Pi/labwc validation of GTK4 video handoff timing, especially EOS redraw behavior and custom display geometry.
- Reconcile frontend specification with actual implemented UI and fill gaps only through tracked issues.
- Keep legacy import documentation aligned with the explicit UI/API import path rather than adding a separate `picframe migrate` command unless a new tracked requirement asks for headless migration.

## Known Verification State
- Frontend build is green with `npm run build`.
- Backend pytest is green in the local Python 3.14.4 `.venv`: 338 passed, 1 GI deprecation warning with `.venv/bin/python -m pytest -q`.
- Latest video hardening verification on this workspace: touched-file Ruff passed, and `.venv/bin/python -m pytest test/core/metadata/test_video_strategy.py test/core/services/test_media_indexer.py test/core/renderers test/core/engine/test_playback.py` passed with 123 tests.
- Latest #680/#668 target diagnostics: docs/user/video-format-validation.md summarizes VLC and GStreamer file matrices, including Pi V4L2 probing, DMABuf hardware success, validated HEVC MKV 4K60, and guarded MOV/Main10 paths.
