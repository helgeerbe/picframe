# Decision Log

This is a compact index of durable project decisions. Detailed rationale lives in `docs/dev/architecture/`, `docs/user/manual.md`, and GitHub Issues.

## Durable Decisions
- Use the existing repository with long-lived modernization branch `v2-dev`.
- Use GitHub Issues and the GitHub Project board as the authoritative task and progress source.
- Every code change must have a GitHub ticket; every commit message for code changes must include the ticket number; closing a code-change ticket must reference the implementing commit hash.
- Build Picframe 2.0 around Clean Architecture / Hexagonal boundaries.
- Use a strict Event-Driven Architecture with immutable DTOs and a thread-safe PriorityQueue event bus.
- Keep event publishing and subscription as separate interfaces.
- Split playlist selection from playback state orchestration.
- Store persistent user settings in `config.db3` and rebuildable media metadata in `media_cache.db3`.
- Version both databases and apply migrations through a standardized migration manager.
- Serialize shared SQLite repository connection access with repository-local
  `RLock`s; playback, API, MQTT, logging, hardware, indexing, and geocoding
  threads must not enter the same SQLite connection concurrently.
- Seed configuration from `default_config.yaml`; expose nested JSON through `ConfigService` and Pydantic API models.
- Legacy `configuration.yaml` migration uses the explicit Settings UI / `/api/config/import-yaml` path, not a startup migration or CLI command; compatibility normalization maps supported renamed runtime keys and ignores startup-only HTTP fields managed by CLI/env.
- The installed `picframe` console script belongs to the next-gen CLI (`picframe.main`) with `init` and `run`; the legacy direct `configuration.yaml` startup path is no longer public.
- Serve the compiled Vue SPA directly through FastAPI; Vite outputs production assets into `src/picframe/html`.
- Keep server port and DB path overrides as startup CLI/env concerns, not mutable runtime settings.
- Use Wayland as the display protocol target; X11 is not supported.
- Run pi3d rendering on the main thread and keep it presentation-focused.
- Use a local renderer state machine and local render queue for high-frequency render concerns.
- Isolate GStreamer into `gst_worker.py` subprocess IPC.
- Prefer GStreamer registry/caps negotiation over hardcoded Raspberry Pi hardware tables.
- Enforce a software decode ceiling with graceful skip/error events for unsupported video.
- Use the First/Last Frame Sandwich pattern for seamless image/video handoff.
- On Wayland, GTK4 `gtk4paintablesink` playback is mandatory; if GTK4 presentation is unavailable, publish `gtk_presentation_unavailable` instead of falling back to legacy sinks.
- Fullscreen video fills the GTK4 host. Raspberry Pi/labwc uses a transparent fixed host for fullscreen plain videos so playback-status overlays can sit above the live paintable; inset/custom video rectangles use an opaque fixed host with the cached backdrop when available or `viewer.background` as fallback. GNOME/VM uses an opaque fullscreen host colored from `viewer.background`. Custom non-fullscreen video places the paintable at the renderer-reported `viewer.display_x/y/w/h` rectangle.
- At EOS, dim the GTK4 video window to 99% opacity, wake pi3d to redraw, then close the video window. Do not add GStreamer alpha handoff tricks or legacy sink fallbacks to the production path.
- Video first-frame handoff is a title-card render action: if overlay text is generated, `viewer.show_text_tm` is honored, text fades out to zero, and clean redraw frames drain before GStreamer starts.
- Promote the cached last-frame reveal only after the worker reports a rendered video frame when sink stats provide that signal.
- Cache the final video transition frame by seeking near EOS and decoding a short tail window to the actual final decoded frame; keep fixed duration-offset sampling only as fallback.
- Include video transition-frame visual processing in cache freshness. Managed cache filenames use a short signature hash over source, display, background, matting, and edge-fill inputs; legacy sidecar frame names are reused only when `.meta.json` contains the current processing signature.
- Treat the generated video transition-frame sidecar as the live video geometry contract: `frame_size`, `coordinate_space=frame_pixels`, and visible video-opening `content_rect` define the live video window for every generated frame type. Beveled/shadowed mat pixels may overlap cached frames and should inset `content_rect` so the video does not cover frame shadows. Manual next/previous navigation must use the same tokened handoff geometry as timed playback; stale transition completions are ignored, and direct fallback may use cached metadata to avoid fullscreen regressions. GTK host backdrops fill non-video regions behind the live paintable; explicit `content_fit` carries fill/contain intent through IPC and pipeline construction.
- Keep black-gap cleanup video-only: generated matted video transition frames may replace source-influenced pixels outside `content_rect` with a black-source render, but normal still-image matting remains unchanged.
- Enable `GST_V4L2_ENABLE_PROBE=1` for the GStreamer worker on Raspberry Pi/Compute Module hardware so V4L2 hardware decoder elements are discoverable before Gst initializes.
- Treat VLC as a diagnostic reference only: VLC's FFmpeg DRM/V4L2-request plus `wl_dmabuf` success does not relax Picframe's GStreamer guards until an equivalent GStreamer path is validated. HEVC Main 8-bit 60 fps support is path-specific: validated MKV may use hardware playbin, while MOV/QuickTime 60 fps remains guarded.
- Treat failed `ffprobe`, invalid video probe JSON, or absence of a video stream as unplayable at indexing time. Such videos are excluded from active playlists and stale cache rows are marked inactive; transition-frame cache failure is best-effort only and does not exclude an otherwise playable video.
- The GStreamer worker must preflight URI discoverability before creating a playback sink, and an explicit render rectangle takes precedence over sink fullscreen requests.
- Use Vue 3, Pinia, Vue Router, Tailwind CSS, vue-i18n, and Leaflet for the SPA.
- Keep frontend map display independent from backend-rendered text overlays.
- Keep frontend narrative metadata over the media and technical metadata in a constrained panel.
- Runtime media-selection controls belong in the Remote view; durable library/viewer settings such as `pic_dir`, raw `sort_cols`, advanced playlist knobs, and `mat_images` stay in Settings.
- Shuffle on/off is separate from shuffle mode: `model.shuffle` is the immediate Remote transport toggle, `model.shuffle_mode` persists the selected mode, missing/invalid modes fall back to `standard`, and config changes rebuild playback through the existing model-change flow.
- Helper text affordances must work by click/tap first; hover tooltips are only an enhancement for pointer devices.
- Remote location/tag filters preserve legacy boolean syntax: English `AND`/`OR`/`NOT` operators, parentheses, and adjacent words as one phrase.
- Remote media-selection match counts are previews only until Apply; `total_count` is the active file count in the selected subdirectory, or in `pic_dir` when no subdirectory is selected.
- Use `State.PAUSED` as the explicit public pause state. Remote/MQTT/WebSocket clients should not infer pause from `IDLE`; `PAUSE` remains a legacy toggle when already paused; pi3d-owned fades must freeze without publishing transition completion while paused; active video resume must resume the existing GStreamer pipeline in place so geometry and playback position are preserved; and display-power toggle should publish play/pause from the HAL final display state.
- Next-gen media cache schema can be changed directly while unreleased; delete/rebuild local media DBs instead of carrying migrations for unpublished schema changes.
- Restore legacy display statistics as rebuildable media-cache metadata (`displayed_count`, `last_displayed`) and expose it as read-only Remote media information.
- Keep temporary missing media, explicit user deletes, and purge separate: missing media is soft-inactivated for NAS resilience, Remote delete moves the original and removes its cache row, and purge hard-deletes rows for files that remain missing.
- Keep filesystem watching as an infrastructure adapter behind `IMediaMonitor`; core consumes `FileChangeEvent`s and must not import watchdog.
- `SystemErrorEvent` is the canonical poison-pill event. Subscriber callback failures are logged and converted to one `SystemErrorEvent`; failures while handling `SystemErrorEvent` are logged without recursive error publication.
- Keep Home Assistant MQTT as a supported next-gen integration, but implement it as an infrastructure adapter over event bus/config/state-query ports. MQTT exposes reboot/shutdown and targeted delete, but not purge DB or clear-cache.
- Remove legacy controller/model/start/viewer/HTTP/peripheral/VLC runtime modules from next-gen after import scans; keep reusable helpers only where next-gen still imports them.
- Text overlay date falls back to the media item's `last_modified` filesystem timestamp when EXIF datetime is missing or None, so images without embedded dates (e.g., stock photos, app exports) still show a date (#714, from Discussion #682).
- Clock overlay extra text is source-driven by `viewer.clock_extra_source`:
  `off` shows nothing, `clock_txt` reads `/dev/shm/clock.txt` on each clock
  refresh, and `ui_text` shows `viewer.clock_extra_text`. The extra line shares
  the clock font/size/opacity/justification and only draws when non-empty (#716).

## Maintenance Decision
- Memory Bank files should stay concise and current. Do not append full chronological task logs here; summarize the current working state and link back to source docs/issues.
