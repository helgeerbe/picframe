# Active Context

  This file tracks the project's current status, including recent changes, current goals, and open questions.
  2026-04-28 11:37:00 - Log of updates made.

* [2026-04-28 11:37:00] - Established GitHub Issues and Projects as the single source of truth for task tracking.
* [2026-04-28 09:26:00] - Completed Phase 0 Technical Spike. Shifting focus to Phase 1 Core Image MVP.

## Current Focus

*   **GStreamer Subprocess IPC & Event Routing:** Addressing Issue #609. Transitioning the GStreamer video renderer from an in-process model to an out-of-process subprocess model. Implementing a robust IPC protocol (Unix Domain Sockets) to handle commands (play, pause, stop) and route GStreamer bus messages (EOS, ERROR, warnings) back to the main application's Event Bus.

## Recent Changes
- **[2026-05-07 21:15:00] - Architectural Assessment for Issue #609**: Completed the technical assessment and gap analysis for moving GStreamer to a subprocess. Updated `Architecture_Solution_Document.md` and `architecture_gst_hw_discovery.md` to reflect the new IPC-driven architecture and hardware discovery isolation.
- **[2026-05-07 16:00:00] - Completed Ticket #663 (GStreamer Hardware Decoding & VM Fallback)**: Fixed video orientation using `waylandsink`'s `rotate-method`. Implemented dynamic hardware probing in `install_picframe.sh` for GStreamer dependencies. Validated software fallback on VMs lacking hardware decoding. Designed a "Zero-Touch Python Orchestrator" to replace the bash script and created a GitHub issue to track it. Updated architecture documentation.
- **[2026-05-07 12:30:00] - Completed Ticket #607 (Video Metadata UI Integration & Refactoring)**: Updated `RemoteView.vue` to display video metadata (duration, codec, pixel format, framerate, bitrate). Fixed WebSocket payload filtering in `app.py` to include these fields. Refactored UI by extracting text overlay controls into a new `FiltersView.vue` component. Updated Vue Router, main navigation (`App.vue`), and synchronized `en.json` and `de.json` localization files.
- **[2026-05-07 11:14:00] - Completed Ticket #613 (DisplayPowerManager Implementation)**: Updated `wayland_power.py`, `hal_factory.py`, and `main.py` to inject an `IEventPublisher` and broadcast `SystemErrorEvent`s on subprocess failures.
- **[2026-05-07 11:14:00] - Completed Ticket #614 (Documentation and Installation Script)**: Merged configuration and prerequisites into `manual.md`, added `install_picframe.sh` for automated setup.
- **[2026-05-07 11:14:00] - Completed Ticket #630 (Load display_output from config)**: Updated `main.py` to retrieve `display_output` from the configuration repository instead of hardcoding it.
- **[2026-05-07 11:14:00] - Completed Ticket #633 (HALFactory Environment Detection)**: Replaced naive `sys.platform` checks with robust runtime hardware probing in `hal_factory.py` and updated adapter initialization in `main.py`.
- **[2026-05-04 20:08:00] - Completed Ticket #661 (Fix UI Media Playback: Resolve Stuck Placeholder Image and Missing EXIF Metadata)**: Diagnosed and fixed data mapping discrepancies in the WebSocket `/ws/state` endpoint. Updated `RemoteView.vue` to extract and render camera-specific EXIF data (ISO, aperture, exposure time, focal length, camera make/model) using `@mdi/js` icons. Synchronized `en.json` and `de.json` localization files. Updated `Frontend_Specification.md` with UI/UX design principles.
- **[2026-05-04 18:23:00] - Completed Ticket #621 ([Task 2C.1]: Decouple Dynamic Overlays (Clock & Text) from Core Renderer)**: Implemented dynamic text generation logic in `PlaybackEngine` to extract metadata fields based on live configuration and pass them to the renderer via `RenderCommand`.
- **[2026-05-04 18:18:00] - Completed Ticket #657 (Refactor Configuration API to use Service Layer and Pydantic Validation)**: Refactored `app.py` to use `ConfigService` for flattening/unflattening configuration data and implemented Pydantic models for strict validation of incoming configuration payloads.
- **[2026-05-04 18:15:00] - Completed Ticket #659 (Epic: Centralized Configuration Initialization and Database Seeding)**: Implemented central `default_config.yaml`, aligned Pydantic models, enhanced bootstrapper with interactive prompts and DB seeding, implemented `MigrationManager`, and removed hardcoded defaults.
- **[2026-05-04 18:11:00] - Completed Ticket #660 (Implement Video Metadata Strategy and Extension Separation)**: Separated image and video extensions in configuration (`configSchema.json`, `models.py`, `default_config.yaml`). Implemented `VideoMetadataStrategy` for video metadata extraction. Updated `MediaIndexerService` to route files to the correct strategy based on extension. Fixed typing issues and updated unit tests.
- **[2026-05-03 20:04:00] - Completed Ticket #655 (Implement REST endpoints for Configuration Management)**: Implemented `GET /api/config` and `PUT /api/config` in `src/picframe/api/app.py`. The endpoints interact with `IConfigRepository` to serve structured configuration matching the frontend schema and publish `SET_CONFIG` events upon updates. Added comprehensive unit tests and ensured strict `mypy` and `ruff` compliance.
- **[2026-05-03 19:35:00] - Completed Ticket #656 (Directory Scanning and ImageProcessingService Integration)**: Implemented `MediaMonitorService` with `watchdog` for real-time file system monitoring, mount point detection, and fast differential sync. Updated `ImageProcessingService` with an asynchronous worker pool for metadata extraction. Fixed `pi3d` mocking issues in tests and ensured strict `mypy` and `ruff` compliance.
- **[2026-05-02 13:40:00] - Completed Backend Event Plumbing for SET_CONFIG (Ticket #647)**: Actual pi3d text rendering deferred to Phase 2C (Ticket #621).
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
## [2026-05-02 13:18:00] - Completed Frontend UI for Text Overlay Controls (Ticket #647) and MapComponent (Ticket #652). Backend tasks remain.
*   **Current Focus:** Designing the architectural refactoring of the `pi3d` rendering engine based on feedback from Paddy (pi3d author).
*   **Key Changes:**
    *   Decomposing `Pi3dRenderer` into specialized components (`ImageRenderer`, `TextRenderer`, `ClockRenderer`, `OverlayRenderer`).
    *   Implementing a formal State Machine for the render loop to handle slide lifecycles cleanly.
    *   Introducing a local `PriorityQueue` for synchronous render events to avoid main EventBus delays.
    *   Optimizing CPU/energy usage by skipping `pi3d.Display.loop_running()` when the screen is static.
*   **Next Steps:** Create GitHub issues for these architectural changes and begin implementation.
## [2026-04-30 12:04:52] - Completed Issue #645: Media Delivery and Fallback Image Implementation
## [2026-05-07 23:52:00] - Fixed Mypy error in Pi3dRenderer
- Replaced `if self._event_publisher:` with `if self._event_publisher is not None:` to satisfy Mypy strict optional checking when emitting `TransitionCompletedEvent`.
## [2026-05-07 23:58:00] - Fixed TransitionCompletedEvent emission logic
- Updated `Pi3dRenderer.render_frame` to use `self._was_transitioning` instead of `self._last_render_state` to reliably detect when a transition (including text animation) has fully completed and reached the `STATIC` state. This ensures the `TransitionCompletedEvent` is emitted, which triggers the video player to start.
