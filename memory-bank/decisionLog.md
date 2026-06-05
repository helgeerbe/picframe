# Decision Log

This is a compact index of durable project decisions. Detailed rationale lives in `Architecture_Solution_Document.md`, `architecture_*.md`, `Frontend_Specification.md`, and GitHub Issues.

## Durable Decisions
- Use the existing repository with long-lived modernization branch `v2-dev`.
- Use GitHub Issues and the GitHub Project board as the authoritative task and progress source.
- Build Picframe 2.0 around Clean Architecture / Hexagonal boundaries.
- Use a strict Event-Driven Architecture with immutable DTOs and a thread-safe PriorityQueue event bus.
- Keep event publishing and subscription as separate interfaces.
- Split playlist selection from playback state orchestration.
- Store persistent user settings in `config.db3` and rebuildable media metadata in `media_cache.db3`.
- Version both databases and apply migrations through a standardized migration manager.
- Seed configuration from `default_config.yaml`; expose nested JSON through `ConfigService` and Pydantic API models.
- Legacy `configuration.yaml` migration uses the explicit Settings UI / `/api/config/import-yaml` path, not a startup migration or CLI command; compatibility normalization maps supported renamed runtime keys and ignores startup-only HTTP fields managed by CLI/env.
- Serve the compiled Vue SPA directly through FastAPI; Vite outputs production assets into `src/picframe/html`.
- Keep server port and DB path overrides as startup CLI/env concerns, not mutable runtime settings.
- Use Wayland as the display protocol target; X11 is not supported.
- Run pi3d rendering on the main thread and keep it presentation-focused.
- Use a local renderer state machine and local render queue for high-frequency render concerns.
- Isolate GStreamer into `gst_worker.py` subprocess IPC.
- Prefer GStreamer registry/caps negotiation over hardcoded Raspberry Pi hardware tables.
- Enforce a software decode ceiling with graceful skip/error events for unsupported video.
- Use the First/Last Frame Sandwich pattern for seamless image/video handoff.
- Use Vue 3, Pinia, Vue Router, Tailwind CSS, vue-i18n, and Leaflet for the SPA.
- Keep frontend map display independent from backend-rendered text overlays.
- Keep frontend narrative metadata over the media and technical metadata in a constrained panel.
- Runtime media-selection controls belong in the Remote view; durable library/viewer settings such as `pic_dir`, raw `sort_cols`, advanced playlist knobs, and `mat_images` stay in Settings.
- Shuffle on/off is separate from shuffle mode: `model.shuffle` is the immediate Remote transport toggle, `model.shuffle_mode` persists the selected mode, missing/invalid modes fall back to `standard`, and config changes rebuild playback through the existing model-change flow.
- Helper text affordances must work by click/tap first; hover tooltips are only an enhancement for pointer devices.
- Remote location/tag filters preserve legacy boolean syntax: English `AND`/`OR`/`NOT` operators, parentheses, and adjacent words as one phrase.
- Remote media-selection match counts are previews only until Apply; `total_count` is the active file count in the selected subdirectory, or in `pic_dir` when no subdirectory is selected.
- Next-gen media cache schema can be changed directly while unreleased; delete/rebuild local media DBs instead of carrying migrations for unpublished schema changes.
- Restore legacy display statistics as rebuildable media-cache metadata (`displayed_count`, `last_displayed`) and expose it as read-only Remote media information.
- Keep temporary missing media, explicit user deletes, and purge separate: missing media is soft-inactivated for NAS resilience, Remote delete moves the original and removes its cache row, and purge hard-deletes rows for files that remain missing.
- Keep filesystem watching as an infrastructure adapter behind `IMediaMonitor`; core consumes `FileChangeEvent`s and must not import watchdog.

## Maintenance Decision
- Memory Bank files should stay concise and current. Do not append full chronological task logs here; summarize the current working state and link back to source docs/issues.
