# Active Context

## Current Focus
The current implementation focus is Phase 2 next-gen control-plane parity cleanup after ticket #618. Phase 3-style GStreamer integration remains the next major architectural stream.

## Current Repo State
- Branch: `v2-dev`, tracking `origin/v2-dev`.
- Known local modification before this Memory Bank update: `.gitignore` ignores `.Codexrules`.
- `.Codexrules` is a local instruction file and is ignored by git.
- The source tree contains both legacy modules and the newer `src/picframe/core` architecture.

## Recently Established Context
- Architecture docs confirm Clean Architecture, strict EDA, dual SQLite databases, HAL ports/adapters, FastAPI/Vue control plane, and Wayland-only display targeting.
- `architecture_gst_hw_discovery.md` and `architecture_hw_limits.md` refine video playback toward GStreamer registry/caps-driven hardware discovery and threshold-based software fallback rejection.
- `Frontend_Specification.md` defines a Vue 3 SPA with Remote, Filters, and Settings views; REST config/maintenance endpoints; WebSocket state; i18n; Leaflet maps; and separate narrative vs. technical metadata presentation.
- Issue #648 is closed after implementing Remote media-selection controls, legacy-compatible location/tag filter expressions, live match counts, playlist filtering/sorting, timing propagation, filter-options API, shuffle transport control refinements, and displayed-count metadata.
- Issues #676 and #677 are closed after documenting legacy `configuration.yaml` import and normalizing supported legacy keys through `/api/config/import-yaml`.
- Recent #618 work added clickable current-media tags in Remote, managed cache storage for generated video transition frames, Clear Image Cache API/service wiring, playback guards so videos continue after generated frames are cleared, image-only portrait-pair display items/rendering/Remote UX, pair delete target selection, internal monitor/indexer/processing lifecycle controls, and real-media Raspberry Pi validation.
- Recent media-cache lifecycle cleanup keeps restart sync idempotent, preserves display counters across reindex, soft-inactivates temporarily missing media, and hard-removes cache rows only after explicit user delete or purge.

## Immediate Next Steps
- Preserve the #618 portrait-pair decisions: videos remain single-item fullscreen and pairs apply only to images.
- Align future video work with caps-driven GStreamer discovery and fallback observability.
- Keep the GStreamer worker IPC protocol explicit and typed.
- Keep backend pytest green while Python 3.14 compatibility shims remain test-only.
- Continue using GitHub Issues/project board as the authoritative task state.

## Active Risks / Watch Items
- Test reliability is environment-sensitive because display/media dependencies and Python version may differ from the target.
- The local Python 3.14 stack exposed Starlette/AnyIO threadpool deadlocks; tests currently work around this without changing production paths.
- Memory Bank files previously accumulated repeated history; future updates should summarize current state rather than append long dated logs.
- Some frontend specification details may be aspirational; verify against `frontend/src` before assuming a feature is implemented.
- Some architecture docs describe intended design; verify against `src/picframe` before making code changes.
