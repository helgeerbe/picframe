# Progress

This file tracks the project's progress using a task list format.
2026-04-23 11:19:00 - Log of updates made.

*

## Completed Tasks

*   [2026-04-23 11:19:00] - Architectural Planning & Documentation (Clean Architecture, EDA, Dual-Database, HAL, Frontend Spec)

## Current Tasks

*   [ ] Phase 0: Technical Spike (Video Handoff PoC)
    *   [ ] Task 0.1: Develop standalone PoC script
    *   [ ] Task 0.2: Implement pi3d image to first-frame blend
    *   [ ] Task 0.3: Integrate GStreamer with HW decoding & Z-order
    *   [ ] Task 0.4: Implement EOS detection
    *   [ ] Task 0.5: Implement last-frame to next image blend
    *   [ ] Task 0.6: Capture performance metrics
*   [ ] Phase 1: Core Image MVP (The "Walking Skeleton")
    *   [ ] Task 1.1: Modernize packaging (PEP 621)
    *   [ ] Task 1.2: Implement PriorityQueue Event Bus
    *   [ ] Task 1.3: Implement Dual-Database Repositories
    *   [ ] Task 1.4: Implement Unified MetadataExtractor (Images)
    *   [ ] Task 1.5: Implement PlaylistManager & ImageProcessingService
    *   [ ] Task 1.6: Refactor ViewerDisplay to Pi3dRenderer
    *   [ ] Task 1.7: Implement PlaybackEngine & Composition Root

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