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
- Remote Shuffle moved from Media Selection to an immediate transport control that saves `model.shuffle` directly.
- Remote transport controls use a balanced touch-first deck, and helper text icons are clickable/tappable with dialog fallback.
- Config-driven next-gen playlist querying for subdirectory, date range, legacy-compatible location/tag boolean filters, shuffle, recent priority, reshuffle cadence, and safe `sort_cols`.
- Live Remote media-selection count preview with selected-count / folder-scope total-count semantics.
- Legacy display statistics parity in the media cache: `displayed_count` and `last_displayed`, shown in Remote metadata.
- Display power/system manager HAL work and Wayland-oriented environment detection.
- Video metadata extraction and frontend display of video technical metadata.
- First/Last Frame Sandwich pattern implementation work is present in recent commit history.
- Legacy `configuration.yaml` import follow-ups #676/#677 are complete: the Settings UI/API path is documented, `viewer.show_text` is normalized into next-gen overlay keys, `mqtt.port` is preserved, and legacy startup-only HTTP keys are intentionally ignored.

## Current / In Progress
- Phase 2 Control Plane/UI remains the broad current phase in local documentation; #648 is closed after the playlist-filter and Remote media-selection slice was implemented and verified.
- Video engine integration is the practical current focus: subprocess GStreamer, IPC event routing, dynamic hardware discovery, and fallback limits.

## Next
- Validate remaining #618 playlist parity behavior on Ubuntu VM, then Pi hardware when available.
- Complete caps-driven hardware capability discovery in the GStreamer worker.
- Surface software fallback / unsupported-media decisions as events visible to logs and the UI.
- Validate video handoff on target Wayland/Raspberry Pi hardware.
- Reconcile frontend specification with actual implemented UI and fill gaps only through tracked issues.
- Keep legacy import documentation aligned with the explicit UI/API import path rather than adding a separate `picframe migrate` command unless a new tracked requirement asks for headless migration.

## Known Verification State
- Frontend build is green with `npm run build`.
- Backend pytest is green in the local Python 3.14.4 `.venv`: 219 passed, 1 skipped, 1 GI deprecation warning with `.venv/bin/python -m pytest -q`.
