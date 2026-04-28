# Active Context

  This file tracks the project's current status, including recent changes, current goals, and open questions.
  2026-04-28 11:37:00 - Log of updates made.

* [2026-04-28 11:37:00] - Established GitHub Issues and Projects as the single source of truth for task tracking.
* [2026-04-28 09:26:00] - Completed Phase 0 Technical Spike. Shifting focus to Phase 1 Core Image MVP.

## Current Focus

*   Phase 1: Core Image MVP (The "Walking Skeleton") - Modernizing packaging and setting up the core event-driven architecture.

## Recent Changes

*   [2026-04-28 12:11:00] - Completed Task 1.1 (Issue #596): Modernized packaging to PEP 621 using `pyproject.toml` and `setuptools_scm`. Removed legacy packaging files and macOS dependencies.
*   [2026-04-28 11:37:00] - Updated memory bank to reflect that GitHub Issues and the GitHub Project board are the authoritative source of truth for project state and task tracking. Added detailed subtasks to all Phase 1 GitHub issues.
*   [2026-04-28 11:14:00] - Initialized the `v2-dev` branch, pushed to origin, and successfully generated all Phase 1-4 WBS tasks as GitHub Issues using the GitHub CLI, applying the `next gen` label to each. The primary codebase refactoring phase has officially commenced.
*   [2026-04-28 10:17:00] - Manage the Picframe 2.0 modernization within the existing repository using a dedicated, long-lived feature branch (`v2-dev`).
*   [2026-04-28 10:09:00] - Migrated the Work Breakdown Structure (WBS) to GitHub Issues. Created issue and PR templates to enforce the Definition of Done and ensure all modernization tasks are labeled with `next gen`.
*   [2026-04-28 09:53:00] - Updated architecture documentation and implementation guidelines to enforce strict versioning for all database schemas (`config.db3` and `media_cache.db3`) and establish a standardized migration mechanism.
*   [2026-04-28 09:26:00] - Successfully completed Phase 0 (Video Handoff PoC), proving GStreamer is a solid solution for GPU-accelerated video playback with seamless pi3d handoff. The PoC also provides valuable hints for the later replacement of the VLC player.

## Open Questions/Issues

*   