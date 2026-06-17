# System Patterns

## Architecture
- Clean Architecture / Hexagonal layering: core playback logic depends on interfaces, not FastAPI, Vue, SQLite, MQTT, pi3d, or GStreamer details.
- Manual dependency injection in `main.py` is the composition root for repositories, services, renderers, HAL adapters, event bus, and web server.
- Strict Event-Driven Architecture: components communicate through immutable event/command DTOs on a thread-safe PriorityQueue event bus.
- Event bus interfaces are split into `IEventPublisher` and `IEventSubscriber` to keep component permissions narrow.
- The runtime separates configuration (`config.db3`, persistent) from media metadata (`media_cache.db3`, rebuildable).
- Filesystem monitoring follows ports/adapters: core services depend on `IMediaMonitor`, while the watchdog-backed adapter lives in infrastructure.
- The package console script enters the next-gen composition root (`picframe.main`); legacy controller/model/start/viewer/HTTP/peripheral/VLC runtime modules have been removed after audited import scans.
- Home Assistant MQTT is an infrastructure adapter that depends on the event bus, config repository, and `ISystemStateQuery`; it must not import legacy controller/model/viewer code.
- `SystemErrorEvent` is the poison-pill event for critical errors and subscriber failures; event-bus error handling must avoid recursive poison-pill loops.
- GPIO hardware inputs are configured as `hardware_inputs` and validated in core before persistence or runtime use. Keyboard/touch `peripherals` remain a separate legacy-compatible config section.

## Playback And Rendering
- `PlaylistManager` owns media querying, filtering, shuffle mode behavior, and current display-item selection.
- `PlaybackEngine` owns state transitions, timing, command handling, and media-to-renderer orchestration.
- `Pi3dRenderer` should stay presentation-focused: draw what it is commanded to draw, with local renderer state only for rendering concerns such as clock ticks.
- pi3d/OpenGL runs on the main thread; FastAPI, MQTT, media monitoring, geocoding, and hardware input operate in background threads.
- GStreamer video playback runs out of process in `gst_worker.py` and communicates through JSON IPC over a Unix-domain socket. The worker delegates playback policy to `gst_playback_policy.py`, GTK4 presentation state to `gtk_video_presenter.py`, and GTK pipeline construction to `gst_pipeline_builder.py`.
- A display item is either one media item or an image-only portrait pair. Videos are never paired and always use the fullscreen video path.
- Portrait pairs are composed in memory for rendering; they do not create persistent generated files.
- Shuffle mode is applied after display slots are built so portrait pairs remain one shuffled slot; `fewer_repeats` uses existing `last_displayed` history and creates no new media DB fields.
- Matting is a renderer image-preparation concern. It wraps EXIF-corrected single images or image-only portrait pairs before pi3d texture creation, creates no persistent files in the current implementation, and never applies to videos.

## Video Handoff
- The First/Last Frame Sandwich pattern hides GStreamer startup/shutdown artifacts:
  - Extract/cache the first decoded video frame and a tail-decoded final EOS frame under the managed runtime cache directory.
  - Render the first frame with pi3d as a video title card. If overlay text is present, wait through text fade-in, `viewer.show_text_tm`, fade-out to zero alpha, and clean redraw drain before starting GStreamer.
  - Preload pi3d's hidden background with the last frame before playback starts.
  - Promote the hidden last-frame reveal only after the GStreamer worker reports that a real video frame has rendered when sink stats expose that count.
  - At EOS, dim the GTK4 video window to 99% opacity, wake pi3d to redraw behind it, then close the video window.
  - Transition out from the last frame when GStreamer reaches EOS.
- On Wayland, require the GTK4 `playbin`/GTK-compatible `gtk4paintablesink` presentation path inside a borderless fullscreen GTK4 host. Raspberry Pi/labwc uses a transparent host; GNOME/VM uses an opaque host colored from `viewer.background`. Fullscreen rectangles fill the host; custom non-fullscreen rectangles place the paintable at the renderer-reported `viewer.display_x/y/w/h` rectangle. The GTK4 video surface hides the cursor during playback.
- If GTK4 or `gtk4paintablesink` is unavailable, publish a GTK presentation system error instead of falling back to legacy sinks.
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
- WebSocket media DTO enrichment uses event payload data first and injected repository ports for cache lookups; the API layer must not open hardcoded `media_cache.db3` paths.
- REST `/api/config` and maintenance/system endpoints handle settings and administrative actions.
- MQTT/Home Assistant exposes playback/display/config controls, targeted delete, reboot, and shutdown; purge DB and clear-cache remain UI/REST maintenance actions.
- Settings UI should use domain-specific controls for runtime config instead of generic JSON/string fields. Host path browsing is backed by FastAPI filesystem endpoints and is restricted to the current user's home directory. Shader settings store the basename without `.fs`/`.vs`, fixed-list settings such as media extensions and image metadata attributes should not permit arbitrary additions in the UI, and geocoding `key_list` should be edited as ordered location parts with fallback priorities rather than global free-form chips.
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

## Hardware Inputs
- `HardwareInputService` translates HAL input events to payload-free `CommandEvent`s and reloads mappings after `hardware_inputs` config changes.
- `IHardwareInput.configure()` is the HAL boundary for runtime GPIO mapping updates; Raspberry Pi GPIO details stay in the infrastructure adapter.
- Hardware input mappings use BCM pin numbers and reject duplicate pins, unsupported actions, and commands that require payloads.
- PIR no-motion grace periods are core service timers (`no_motion_delay_seconds`), not GPIO adapter behavior. Renewed `motion_detected` cancels a pending delayed `no_motion` command.

## Testing And Quality
- TDD is expected for new work: adapt or add tests with the implementation.
- Quality gates are pytest, mypy strict mode, ruff, frontend type checks, and relevant integration/manual checks.
- Hardware/display-sensitive tests may require a real Wayland session or an appropriate headless compositor.
