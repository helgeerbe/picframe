# Active Context

## Current Focus
The current architectural focus is Phase 3-style video engine integration, especially GStreamer subprocess IPC, event routing, hardware capability discovery, software fallback policy, and seamless pi3d/GStreamer handoff.

## Current Repo State
- Branch: `v2-dev`, tracking `origin/v2-dev`.
- Known local modification before this Memory Bank update: `.gitignore` ignores `.Codexrules`.
- `.Codexrules` is a local instruction file and is ignored by git.
- The source tree contains both legacy modules and the newer `src/picframe/core` architecture.

## Recently Established Context
- Architecture docs confirm Clean Architecture, strict EDA, dual SQLite databases, HAL ports/adapters, FastAPI/Vue control plane, and Wayland-only display targeting.
- `architecture_gst_hw_discovery.md` and `architecture_hw_limits.md` refine video playback toward GStreamer registry/caps-driven hardware discovery and threshold-based software fallback rejection.
- `Frontend_Specification.md` defines a Vue 3 SPA with Remote, Filters, and Settings views; REST config/maintenance endpoints; WebSocket state; i18n; Leaflet maps; and separate narrative vs. technical metadata presentation.

## Immediate Next Steps
- Align implementation with caps-driven GStreamer discovery and fallback observability.
- Keep the GStreamer worker IPC protocol explicit and typed.
- Re-run backend tests in a suitable local environment; sandbox pytest currently hangs during even small API tests.
- Continue using GitHub Issues/project board as the authoritative task state.

## Active Risks / Watch Items
- Test reliability is environment-sensitive because display/media dependencies and Python version may differ from the target.
- Memory Bank files previously accumulated repeated history; future updates should summarize current state rather than append long dated logs.
- Some frontend specification details may be aspirational; verify against `frontend/src` before assuming a feature is implemented.
- Some architecture docs describe intended design; verify against `src/picframe` before making code changes.
