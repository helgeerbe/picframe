# Active Context

  This file tracks the project's current status, including recent changes, current goals, and open questions.
  2026-04-28 11:37:00 - Log of updates made.

* [2026-04-28 11:37:00] - Established GitHub Issues and Projects as the single source of truth for task tracking.
* [2026-04-28 09:26:00] - Completed Phase 0 Technical Spike. Shifting focus to Phase 1 Core Image MVP.

## Current Focus

*   Phase 2 Planning: Restructuring Phase 2 into Subphases (2A, 2B, 2C) and aligning GitHub issues.
*   Next up: Implementing the CLI (`init` and `run` commands) and `EnvironmentBootstrapper` (Subphase 2B).

## Recent Changes
- **[2026-04-30 14:50:00] - Completed Ticket #649 (Phase 2B: System Actions)**: Implemented host-level reboot/shutdown, media deletion (move to `deleted_pictures`), and database purging via WebUI and EventBus.

*   [2026-04-29 10:15:00] - Approved architecture for Phase 2 subphases (2A: HAL, 2B: Web/CLI, 2C: Rendering Parity).
*   [2026-04-29 10:15:00] - Approved CLI design (`picframe init` for user-space bootstrapping in `~/.picframe/`) and rejected `sudo` system dependency installation in favor of native OS packages.
*   [2026-04-28 13:34:00] - Started Task 1.5 (Issue #600): PlaylistManager & ImageProcessingService. Moved issue to "In Progress" on the GitHub project board.
*   [2026-04-28 13:28:00] - Completed Task 1.4 (Issue #599): Implemented Unified MetadataExtractor for images, ensuring feature parity with the original implementation.
*   [2026-04-28 13:19:00] - Started Task 1.4 (Issue #599): Unified MetadataExtractor (Images).
*   [2026-04-28 13:10:00] - Completed Task 1.3 (Issue #598): Implemented Dual-Database Repositories (`SQLiteConfigRepository`, `SQLiteMediaRepository`) and a standardized `MigrationManager`. All code is fully tested, type-checked, and documented.
*   [2026-04-28 13:00:00] - Started Task 1.3 (Issue #598): Dual-Database Repositories & Migrations.
*   [2026-04-28 12:25:00] - Completed Task 1.2 (Issue #597): Implemented the thread-safe `PriorityQueue` Event Bus with `IEventPublisher`/`IEventSubscriber` interfaces and defined core Immutable DTO `Events`.
*   [2026-04-28 12:11:00] - Completed Task 1.1 (Issue #596): Modernized packaging to PEP 621 using `pyproject.toml` and `setuptools_scm`. Removed legacy packaging files and macOS dependencies.
*   [2026-04-28 11:37:00] - Updated memory bank to reflect that GitHub Issues and the GitHub Project board are the authoritative source of truth for project state and task tracking. Added detailed subtasks to all Phase 1 GitHub issues.
*   [2026-04-28 11:14:00] - Initialized the `v2-dev` branch, pushed to origin, and successfully generated all Phase 1-4 WBS tasks as GitHub Issues using the GitHub CLI, applying the `next gen` label to each. The primary codebase refactoring phase has officially commenced.
*   [2026-04-28 10:17:00] - Manage the Picframe 2.0 modernization within the existing repository using a dedicated, long-lived feature branch (`v2-dev`).
*   [2026-04-28 10:09:00] - Migrated the Work Breakdown Structure (WBS) to GitHub Issues. Created issue and PR templates to enforce the Definition of Done and ensure all modernization tasks are labeled with `next gen`.
*   [2026-04-28 09:53:00] - Updated architecture documentation and implementation guidelines to enforce strict versioning for all database schemas (`config.db3` and `media_cache.db3`) and establish a standardized migration mechanism.
*   [2026-04-28 09:26:00] - Successfully completed Phase 0 (Video Handoff PoC), proving GStreamer is a solid solution for GPU-accelerated video playback with seamless pi3d handoff. The PoC also provides valuable hints for the later replacement of the VLC player.

## Open Questions/Issues

*   
## [2026-04-28 14:42:00] - Gap Analysis Completed
*   Conducted a gap analysis between the new `PlaylistManager`/`ImageProcessingService` and the legacy `Model`/`ImageCache`.
*   Implemented immediate fixes in `PlaylistManager` to handle missing files and return a placeholder image.
*   Created GitHub issues #618 and #619 to track deferred features (portrait pairs, filtering, sorting, matting, text overlays) for Phase 2.

## [2026-04-28 14:42:00] - Gap Analysis Completed
*   Conducted a gap analysis between the new `PlaylistManager`/`ImageProcessingService` and the legacy `Model`/`ImageCache`.
*   Implemented immediate fixes in `PlaylistManager` to handle missing files and return a placeholder image.
*   Created GitHub issues #618 and #619 to track deferred features (portrait pairs, filtering, sorting, matting, text overlays) for Phase 2.

## [2026-04-28 15:01:00] - Starting Task 1.6
*   **Current Focus:** Refactoring `ViewerDisplay` to `Pi3dRenderer` (Issue #601).
*   **Next Steps:** Extract OpenGL/pi3d drawing logic from legacy `ViewerDisplay` and implement the `execute(RenderCommand)` interface.

## [2026-04-28 15:46:00] - Starting Task 1.7
*   **Current Focus:** PlaybackEngine & Composition Root (Issue #602).
*   **Next Steps:** Implement the `PlaybackEngine` state machine (IDLE, PLAYING, TRANSITIONING) and create `main.py` to wire all components together and start the application loops.

## [2026-04-29 09:04:00] - Completed Task 1.7 & Phase 1 Test Run
*   **Completed:** Implemented `PlaybackEngine` and `main.py` (Composition Root). Created Phase 2 tracking tickets for technical debt (#628, #631).
*   **Issue:** Test run over SSH hangs at `pi3d.Display.create()`. `Ctrl+C` fails to terminate cleanly due to the hang.
*   **Root Cause:** `pi3d` requires a physical display context (DRM/KMS or Wayland) which is not available in a standard headless SSH session.
*   **Next Steps:** Resolve the display context issue (e.g., run with `DISPLAY=:0` or directly on the Pi) to verify the "Walking Skeleton".

## [2026-04-29 09:41:00] - Resolved Wayland Display Issues
## [2026-04-29 13:07:00] - Starting Phase 2B: The Web Control Plane & CLI
## [2026-04-29 13:21:00] - Completed Task 2B.1: CLI and EnvironmentBootstrapper
*   **Completed:** Successfully executed the main application over SSH using the correct Wayland environment variables.
*   **Fix:** Updated `main.py` to pass `"use_sdl2": True` to the `Pi3dRenderer` configuration, allowing `pi3d` to use the SDL2 backend for window creation in the Ubuntu VM development environment.
*   **Fix:** Identified that the active Wayland display socket was `wayland-0` (not `wayland-1`). Running with `WAYLAND_DISPLAY=wayland-0 XDG_RUNTIME_DIR=/run/user/1000` resolved the remote execution issues.
*   **Status:** The pi3d Wayland rendering integration is now working correctly, confirming that the recent troubleshooting and fixes applied to the OpenGL texture loading processes were successful. The Phase 1 "Walking Skeleton" is fully operational.
## [2026-04-29 14:44:00] - Starting Task 2B.3: Vue.js SPA Development (Issue #604)

## [2026-04-29 15:45:00] - Completed Vue.js SPA Development
- Successfully implemented the Vue 3 Single Page Application (Task 2B.3 / Issue #604).
- Developed the "Remote" view with playback controls and metadata display.
- Developed the dynamic "Settings" view with JSON schema parsing and i18n support.
- Configured the Vite build pipeline to output static assets directly to `src/picframe/html` for FastAPI integration.
- Current focus shifts to setting up the FastAPI backend (Task 2B.2 / Issue #603) to serve the SPA and provide REST/WebSocket endpoints.

## [2026-04-29 15:45:00] - Completed Vue.js SPA Development
- Successfully implemented the Vue 3 Single Page Application (Task 2B.3 / Issue #604).
- Developed the "Remote" view with playback controls and metadata display.
- Developed the dynamic "Settings" view with JSON schema parsing and i18n support.
- Configured the Vite build pipeline to output static assets directly to `src/picframe/html` for FastAPI integration.
- Current focus shifts to setting up the FastAPI backend (Task 2B.2 / Issue #603) to serve the SPA and provide REST/WebSocket endpoints.
## [2026-04-30 12:04:52] - Completed Issue #645: Media Delivery and Fallback Image Implementation

## [2026-04-30 14:53:00] - Planning Phase 2C: Rendering Parity & Enhancements
*   **Current Focus:** Designing the architectural refactoring of the `pi3d` rendering engine based on feedback from Paddy (pi3d author).
*   **Key Changes:**
    *   Decomposing `Pi3dRenderer` into specialized components (`ImageRenderer`, `TextRenderer`, `ClockRenderer`, `OverlayRenderer`).
    *   Implementing a formal State Machine for the render loop to handle slide lifecycles cleanly.
    *   Introducing a local `PriorityQueue` for synchronous render events to avoid main EventBus delays.
    *   Optimizing CPU/energy usage by skipping `pi3d.Display.loop_running()` when the screen is static.
*   **Next Steps:** Create GitHub issues for these architectural changes and begin implementation.
## [2026-04-30 12:04:52] - Completed Issue #645: Media Delivery and Fallback Image Implementation
