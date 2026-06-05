# System Patterns

## Architecture
- Clean Architecture / Hexagonal layering: core playback logic depends on interfaces, not FastAPI, Vue, SQLite, MQTT, pi3d, or GStreamer details.
- Manual dependency injection in `main.py` is the composition root for repositories, services, renderers, HAL adapters, event bus, and web server.
- Strict Event-Driven Architecture: components communicate through immutable event/command DTOs on a thread-safe PriorityQueue event bus.
- Event bus interfaces are split into `IEventPublisher` and `IEventSubscriber` to keep component permissions narrow.
- The runtime separates configuration (`config.db3`, persistent) from media metadata (`media_cache.db3`, rebuildable).
- Filesystem monitoring follows ports/adapters: core services depend on `IMediaMonitor`, while the watchdog-backed adapter lives in infrastructure.

## Playback And Rendering
- `PlaylistManager` owns media querying, filtering, shuffle, and current display-item selection.
- `PlaybackEngine` owns state transitions, timing, command handling, and media-to-renderer orchestration.
- `Pi3dRenderer` should stay presentation-focused: draw what it is commanded to draw, with local renderer state only for rendering concerns such as clock ticks.
- pi3d/OpenGL runs on the main thread; FastAPI, MQTT, media monitoring, geocoding, and hardware input operate in background threads.
- GStreamer video playback runs out of process in `gst_worker.py` and communicates through JSON IPC over a Unix-domain socket.
- A display item is either one media item or an image-only portrait pair. Videos are never paired and always use the fullscreen video path.
- Portrait pairs are composed in memory for rendering; they do not create persistent generated files.

## Video Handoff
- The First/Last Frame Sandwich pattern hides GStreamer startup/shutdown artifacts:
  - Extract/cache first and last video frames under the managed runtime cache directory.
  - Transition into the first frame with pi3d.
  - Start GStreamer after that transition.
  - Swap pi3d's hidden background to the last frame during video playback.
  - Transition out from the last frame when GStreamer reaches EOS.
- Only one renderer should actively own visible display output at a time.
- Clear Image Cache removes generated cache artifacts such as video transition frames, but original media files and media database rows are handled by separate operations.

## Hardware Capability Strategy
- Prefer GStreamer registry and caps negotiation over hardcoded board/codec tables.
- Use preflight media metadata plus decoder pad-template caps intersection to determine hardware compatibility.
- Detect and report software fallback through GStreamer pipeline introspection.
- Skip media that exceeds hardware limits and configured software fallback limits instead of attempting catastrophic playback.

## Configuration And API
- `default_config.yaml` is the seed source for runtime configuration.
- `ConfigService` is the anti-corruption layer between flat SQLite key/value storage and nested API/frontend JSON.
- Pydantic `AppConfig` models validate API payloads and imported YAML.
- Startup-only parameters such as server port stay in CLI/env vars; runtime-mutable config belongs in SQLite and `/api/config`.

## Frontend Patterns
- Vue 3 SPA uses Pinia stores for player state, config state, and system actions.
- WebSocket `/ws/state` handles real-time media/state/error updates and outgoing player commands.
- REST `/api/config` and maintenance/system endpoints handle settings and administrative actions.
- Frontend narrative metadata belongs in the image overlay; technical metadata belongs in a constrained scrollable panel.
- Remote keeps primary media fields backward-compatible and uses `layout` plus `items[]` for pair preview, side-specific details, and pair delete choices.
- User-facing frontend strings should go through vue-i18n and stay synchronized across `en.json` and `de.json`.

## Media Cache Lifecycle
- Restart/differential sync is idempotent for unchanged active files and reindexes only new, changed, or restored files.
- Temporary missing files are marked inactive and skipped during playback; purge is the explicit operation that hard-deletes missing-file rows.
- User-initiated Remote delete moves the original file to `model.deleted_pictures` and then removes the corresponding media cache row.
- Display statistics live in `media_cache.db3` and are preserved on metadata refresh; only actual display recording updates `displayed_count` and `last_displayed`.

## Filesystem Monitoring
- `WatchdogMediaMonitor` is the infrastructure adapter for create/modify/delete/move events and differential sync.
- Differential sync publishes `FileChangeEvent` directly; `MediaIndexerService` decides whether each file needs metadata extraction.
- Monitor directory changes go through `IMediaMonitor.set_directories()` rather than direct mutable adapter state.

## Testing And Quality
- TDD is expected for new work: adapt or add tests with the implementation.
- Quality gates are pytest, mypy strict mode, ruff, frontend type checks, and relevant integration/manual checks.
- Hardware/display-sensitive tests may require a real Wayland session or an appropriate headless compositor.
