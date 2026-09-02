# Decision Log

This is a compact index of durable project decisions. Detailed rationale lives in `docs/dev/architecture/`, `docs/user/manual.md`, and GitHub Issues.

## Durable Decisions
- Use the existing repository for the Picframe 2.0 modernization (originally on a long-lived modernization branch, since merged to `dev` via PR #737 and deleted).
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
- The GStreamer worker subprocess must enforce `GDK_BACKEND=wayland` so GTK4 never falls back to X11/Xwayland (which green-screens / segfaults on Raspberry Pi 5 under labwc). When `WAYLAND_DISPLAY` is missing, the renderer dynamically detects a single `wayland-*` socket in `XDG_RUNTIME_DIR` and warns on zero/multiple. The worker logs display env vars before GTK4 init (#710).
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
- `viewer.show_text_on_video` (default `False`) gates the metadata text overlay on video media. When `False`, the playback engine suppresses only the text overlay for video handoffs via `dataclasses.replace()` so clock and status overlays are preserved and GStreamer starts without waiting for `show_text_tm` fade-out. When `True`, video title-card text behaves like still-image text (fade-in, `show_text_tm`, fade-out, clean redraw, then GStreamer starts).
- `Pi3dRenderer.execute()` must copy `show_text` from the incoming `OverlayConfig` so video media suppression reaches the renderer's overlay state (#726 bugfix).
- `Pi3dRenderer._handle_state_event` must preserve the current `show_text` value through `CurrentMediaChangedEvent` by passing it to `_build_overlay_config()` instead of resetting it from `self._config.show_text_enabled` (#726 bugfix).
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
- Clock renderer visual signature must include `clock_extra_text` so changing
  only the text (not the source) invalidates and rebuilds the clock block (#719
  follow-up fix).
- Text overlay gradient sprite must set z via `position()` only (not the
  constructor), pass numpy arrays directly to `pi3d.Texture` (no PIL
  conversion), and use a full-render-height texture scaled on the GPU (#719).
  Z-order convention: status overlay z=0.05 (front), text z=0.1, gradient
  z=0.3 (behind text), image z=5.0. The gradient is drawn behind the text so it
  no longer occludes it; the status overlay sits in front of text.
- `clock_extra_source` must propagate through `OverlayConfig` in `playback.py`,
  and `ClockRenderer` must re-read `/dev/shm/clock.txt` dynamically on each
  `has_changed()`/`draw()` call (#719).
- `ImageMetadataStrategy` and `VideoMetadataStrategy` must fall back to
  `last_modified` at indexing time when no EXIF/creation date is found, so the
  DB always stores a valid `exif_datetime` and date-range SQL filters work
  without runtime fallbacks (#719).
- CI/CD and developer workflow decisions (#706):
  - CI pipeline (`ci.yml`) runs ruff, mypy, pytest, frontend bundle drift,
    package build, and Conventional Commit PR-title validation on PRs to
    `dev`; it replaces legacy `test.yml`/`python-publish.yml`.
  - Releases (`release.yml`) use calendar-version tags `YYYY.MM.DD[.postN]`,
    PyPI trusted publishing, and GitHub Releases with PR-title changelog
    categories from `dev → main` merges.
  - PR titles must follow Conventional Commits; the PR body must reference the
    tracking ticket via `Closes`/`Fixes`/`Refs`.
  - `docs/dev/workflow.md` is the developer workflow reference.
  - Branch protection: `helgeerbe` is a bypass actor (always) on both the
    `dev` and `main` rulesets so the owner can self-merge PRs
    without review; other maintainers still require 1 approving review; CI
    status checks remain required for all actors.

- Purge also cleans orphaned directory rows: `PURGE_FILES` now calls
  `PlaylistManager.purge_orphaned_directories()`, which queries active
  directory IDs from the media repository and removes directory rows in the
  config repository that no longer have any non-deleted media referencing them
  (#724).
- XMP subject parsing must accept both Bag/li and Seq/li containers, and
  handle single-string `li` values as well as lists. ACDSee Photo Studio on
  Mac writes keywords under Seq/li instead of the common Bag/li; Bag/li
  remains the preferred path when both are present (#725).

- Use the GitHub MCP agent for all GitHub operations (issues, PRs, branches, commits, releases, comments, reviews, searches) on `helgeerbe/picframe`; prefer it over shell `gh` or manual web edits. Verified read-only live on 2026-09-01; mutating operations exercised in production during the post-merge cleanup (PRs #744/#745/#746 created/merged, issues #736/#738/#741/#742/#743 created/closed, branches created/deleted, review comments/replies posted).

- `v2-dev → dev` transition (PR #737): the full Picframe 2.0 modernization
  merged into `dev`, making `dev` the integration branch. The long-lived
  `v2-dev` branch is superseded and deleted (local + remote, `cb69484`;
  commits preserved on `dev`). `main` remains the release branch; `release.yml`
  auto-tags (calver), publishes to PyPI, and creates a GitHub Release on
  `dev → main` merge.

- Reverse geocoding is an infrastructure concern: `geo_reverse.py` moved from
  the top-level package to `infrastructure/geo_reverse.py` (#741, PR #744),
  keeping geocoding network/IO details out of core behind the existing port.

- Matting helper `mat_image.py` moved from the top-level package to
  `core/utils/mat_image.py` (#742, PR #745), colocating it with the other
  renderer utility modules in core.

- Frontend `@typescript-eslint/no-explicit-any` is `error`, not `warn` (#743,
  PR #746). Catch handlers use `catch (e: unknown)` with typed
  `frontend/src/utils/errors.ts` helpers (`getErrorMessage` reads `.message`
  from `Error`/plain objects; `getApiErrorMessage` unwraps API error shapes).
  Five genuinely-dynamic blobs retain scoped `eslint-disable-next-line` with
  rationale: store `config` ref, `MediaItem.exif`, and `SettingsView`
  `localConfig`/`initializeConfig` param/`initialized`. New frontend catch
  handlers must use `unknown` + the `errors.ts` helpers, never bare `any`.

- Direct pushes to `dev` bypassing branch protection may succeed for the owner
  (bypass actor) but are not guaranteed; the 3-line Sourcery fixup (`a307cec`)
  was pushed directly as a one-off. Prefer the PR-based flow for future fixes.

## Maintenance Decision
- Memory Bank files should stay concise and current. Do not append full chronological task logs here; summarize the current working state and link back to source docs/issues.
