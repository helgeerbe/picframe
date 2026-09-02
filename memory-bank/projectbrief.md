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
- Branch: `dev` (integration branch, post-`v2-dev → dev` merge via PR #737).
  The long-lived `v2-dev` branch is superseded and deleted (commits preserved
  on `dev`); `main` remains the release branch.
- Phases 0–2 are complete and merged into `dev`. The full target architecture
  (Clean Architecture, strict EDA, dual SQLite, FastAPI + Vue 3 control plane,
  Wayland-only pi3d rendering, GStreamer subprocess video) is in place.
- Current state: post-merge cleanup complete; 3 deferred follow-up refactors
  landed (#741 geo_reverse → infrastructure, #742 mat_image → core/utils,
  #743 `no-explicit-any` warn → error).
- Next: the `dev → main` release PR (deferred, user's call).

## Memory Bank Maintenance Policy
- Keep each core Memory Bank file concise and current; prefer rewriting stale sections over appending dated logs.
- Store detailed design in `docs/dev/architecture/`; user-facing docs live in `docs/user/`. Memory Bank should point to those documents and preserve only the decisions needed after a reset.
- Keep `activeContext.md` focused on the present: current focus, next steps, known risks, and verification state.
- Keep `decisionLog.md` as a compact index of major decisions, not a full rationale archive.
