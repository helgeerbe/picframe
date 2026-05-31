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
- Display power/system manager HAL work and Wayland-oriented environment detection.
- Video metadata extraction and frontend display of video technical metadata.
- First/Last Frame Sandwich pattern implementation work is present in recent commit history.

## Current / In Progress
- Phase 2 Control Plane/UI remains the broad current phase in local documentation.
- Video engine integration is the practical current focus: subprocess GStreamer, IPC event routing, dynamic hardware discovery, and fallback limits.

## Next
- Complete caps-driven hardware capability discovery in the GStreamer worker.
- Surface software fallback / unsupported-media decisions as events visible to logs and the UI.
- Validate video handoff on target Wayland/Raspberry Pi hardware.
- Reconcile frontend specification with actual implemented UI and fill gaps only through tracked issues.

## Known Verification State
- Frontend no-emit type check has passed locally.
- Backend pytest is green in the local Python 3.14.4 `.venv`: 205 passed, 1 skipped, 1 GI deprecation warning with `.venv/bin/python -m pytest -q`.
