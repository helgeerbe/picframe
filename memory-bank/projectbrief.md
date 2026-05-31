# Project Brief

## Purpose
Picframe 2.0 modernizes the Raspberry Pi digital picture frame into a modular, event-driven appliance. The system displays photos and videos with smooth transitions, exposes local-network control through a web UI and MQTT, and remains reliable on Raspberry Pi/Wayland hardware.

## Scope
- Modernize the legacy synchronous viewer into a Clean Architecture / Hexagonal design.
- Keep the core playback domain independent from FastAPI, Vue, SQLite, MQTT, pi3d, and GStreamer implementation details.
- Support image playback through pi3d and video playback through GStreamer with seamless handoff.
- Store runtime configuration in `config.db3` and ephemeral media metadata in `media_cache.db3`.
- Provide a Vue 3 SPA served by FastAPI for remote control, settings, metadata, maps, and maintenance actions.

## Non-Negotiables
- Wayland is the supported display server protocol; X11 is not a target.
- pi3d/OpenGL work belongs on the main thread; background services communicate through the event bus.
- GStreamer must be isolated out of process because native media stacks can crash or leak.
- User configuration is persistent; media cache data is rebuildable.
- GitHub Issues and the GitHub Project board are the authoritative task tracker. Memory Bank files are a concise local context cache.

## Current Modernization Shape
- Branch: `v2-dev`.
- Phase 0 and Phase 1 are complete at the architecture/memory-bank level.
- Phase 2 Control Plane/UI work is partly complete.
- Current technical focus is video engine integration: GStreamer subprocess IPC, hardware capability discovery, caps-driven fallback decisions, and first/last-frame handoff.

## Memory Bank Maintenance Policy
- Keep each core Memory Bank file concise and current; prefer rewriting stale sections over appending dated logs.
- Store detailed design in `Architecture_Solution_Document.md`, `architecture_*.md`, and `Frontend_Specification.md`; Memory Bank should point to those documents and preserve only the decisions needed after a reset.
- Keep `activeContext.md` focused on the present: current focus, next steps, known risks, and verification state.
- Keep `decisionLog.md` as a compact index of major decisions, not a full rationale archive.
