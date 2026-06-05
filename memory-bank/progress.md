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
- Vue 3 SPA foundation with Remote, Filters, and Settings views.
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
- Display power/system manager HAL work and Wayland-oriented environment detection.
- Video metadata extraction and frontend display of video technical metadata.
- First/Last Frame Sandwich pattern implementation work is present in recent commit history.
- Legacy `configuration.yaml` import follow-ups #676/#677 are complete: the Settings UI/API path is documented, `viewer.show_text` is normalized into next-gen overlay keys, `mqtt.port` is preserved, and legacy startup-only HTTP keys are intentionally ignored.

## Current / In Progress
- Phase 2 Control Plane/UI remains the broad current phase in local documentation; #648 is closed after the playlist-filter and Remote media-selection slice was implemented and verified.
- Video engine integration remains an active architectural stream: subprocess GStreamer, IPC event routing, dynamic hardware discovery, fallback limits, and target-hardware validation.
- Ticket #666 is implemented and manually Remote-validated: split shuffle button works, mode persists, and automated verification is green.

## Next
- Complete caps-driven hardware capability discovery in the GStreamer worker.
- Surface software fallback / unsupported-media decisions as events visible to logs and the UI.
- Validate video handoff on target Wayland/Raspberry Pi hardware.
- Reconcile frontend specification with actual implemented UI and fill gaps only through tracked issues.
- Keep legacy import documentation aligned with the explicit UI/API import path rather than adding a separate `picframe migrate` command unless a new tracked requirement asks for headless migration.

## Known Verification State
- Frontend build is green with `npm run build`.
- Backend pytest is green in the local Python 3.14.4 `.venv`: 298 passed, 1 skipped, 1 GI deprecation warning with `.venv/bin/python -m pytest -q`.
