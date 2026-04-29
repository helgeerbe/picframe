# Progress

**Note: The authoritative source of truth for project progress, task status, and detailed subtasks is the [GitHub Project Board](https://github.com/users/helgeerbe/projects/3/views/2) and GitHub Issues. This file serves as a high-level summary.**

This file tracks the project's progress using a task list format.
2026-04-28 11:37:00 - Log of updates made.

* [2026-04-28 09:26:00] - Marked Phase 0 as complete.

## Completed Tasks

*   [2026-04-28 09:26:00] - Phase 0: Technical Spike (Video Handoff PoC)
*   [2026-04-23 11:19:00] - Architectural Planning & Documentation (Clean Architecture, EDA, Dual-Database, HAL, Frontend Spec)

## Current Tasks

*   [x] Phase 0: Technical Spike (Video Handoff PoC)
    *   [x] Task 0.1: Develop standalone PoC script
    *   [x] Task 0.2: Implement pi3d image to first-frame blend
    *   [x] Task 0.3: Integrate GStreamer with HW decoding & Z-order
    *   [x] Task 0.4: Implement EOS detection
    *   [x] Task 0.5: Implement last-frame to next image blend
    *   [x] Task 0.6: Capture performance metrics
*   [x] Phase 1: Core Image MVP (The "Walking Skeleton")
    *   [x] Task 1.0: Phase 1 Readiness & Prerequisites
    *   [x] Task 1.1: Modernize packaging (PEP 621)
    *   [x] Task 1.2: Implement PriorityQueue Event Bus
    *   [x] Task 1.3: Implement Dual-Database Repositories
    *   [x] Task 1.4: Implement Unified MetadataExtractor (Images)
    *   [x] Task 1.5: Implement PlaylistManager & ImageProcessingService
    *   [x] Task 1.6: Refactor ViewerDisplay to Pi3dRenderer
    *   [x] Task 1.7: Implement PlaybackEngine & Composition Root

## Next Steps

*   [ ] Phase 2: Control Plane & UI
    *   [ ] Task 2.1: Implement FastAPI backend
    *   [ ] Task 2.2: Develop Vue.js SPA
    *   [ ] Task 2.3: Refactor MQTT client
    *   [ ] Task 2.4: Implement HardwareInputService
*   [ ] Phase 3: Video Engine Integration
    *   [ ] Task 3.1: Extend MetadataExtractor for Video
    *   [ ] Task 3.2: Create GstVideoRenderer
    *   [ ] Task 3.3: Implement IPC command handling
    *   [ ] Task 3.4: Implement pi3d <-> GStreamer handoff logic
*   [ ] Phase 4: Advanced System Services & Polish
    *   [ ] Task 4.1: Implement MediaMonitorService
    *   [ ] Task 4.2: Implement SchedulerService
    *   [ ] Task 4.3: Implement DisplayPowerManager
    *   [ ] Task 4.4: Implement SystemManager
    *   [ ] Task 4.5: Implement Configuration Migration Adapter
    *   [ ] Task 4.6: Comprehensive integration testing & cleanup