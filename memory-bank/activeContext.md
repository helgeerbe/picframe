# Active Context

## Current Focus
The active branch is `v2-dev`. The latest ticketed change is #719, which fixes
three bugs reported by Paddy (@paddywwoof) during alpha testing of #714/#715/#716
(Discussion #682): (1) the gradient sprite z-order/PIL/1px-width issues in
`text_renderer.py`, (2) `/dev/shm/clock.txt` not showing because
`clock_extra_source` was not propagated through `OverlayConfig` and the clock
renderer did not re-read the file dynamically, and (3) the date fallback for
non-EXIF images not working because the DB stored `None` instead of falling back
to `last_modified` at indexing time. Issues #714/#715/#716 are now fully
functional after the #719 fixes.

## Current Repo State
- Branch: `v2-dev`; #719 is the latest local implementation context.
- `.Codexrules` is a local instruction file and is ignored by git.
- The source tree is centered on the next-gen `main.py`, `core`, `api`, and `infrastructure` architecture; broad legacy runtime modules were removed during #678 while reusable helpers such as matting/geocoding remain where still imported.

## Recently Established Context
- Architecture docs confirm Clean Architecture, strict EDA, dual SQLite databases, HAL ports/adapters, FastAPI/Vue control plane, and Wayland-only display targeting.
- `docs/dev/architecture/video-gst-hw-discovery.md` and `docs/dev/architecture/video-hw-limits.md` refine video playback toward GStreamer registry/caps-driven hardware discovery and threshold-based software fallback rejection.
- `docs/dev/architecture/frontend.md` defines a Vue 3 SPA with Remote, Appearance, Settings, and Logs views; REST config/maintenance endpoints; WebSocket state; i18n; Leaflet maps; and separate narrative vs. technical metadata presentation.
- Issue #648 is closed after implementing Remote media-selection controls, legacy-compatible location/tag filter expressions, live match counts, playlist filtering/sorting, timing propagation, filter-options API, shuffle transport control refinements, and displayed-count metadata.
- Issues #676 and #677 are closed after documenting legacy `configuration.yaml` import and normalizing supported legacy keys through `/api/config/import-yaml`.
- Recent #618 work added clickable current-media tags in Remote, managed cache storage for generated video transition frames, Clear Image Cache API/service wiring, playback guards so videos continue after generated frames are cleared, image-only portrait-pair display items/rendering/Remote UX, pair delete target selection, internal monitor/indexer/processing lifecycle controls, and real-media Raspberry Pi validation.
- Recent media-cache lifecycle cleanup keeps restart sync idempotent, preserves display counters across reindex, soft-inactivates temporarily missing media, and hard-removes cache rows only after explicit user delete or purge.
- Recent #611 cleanup moved watchdog media monitoring behind a core `IMediaMonitor` port; watchdog now lives in infrastructure and differential sync emits core `FileChangeEvent`s directly.
- Ticket #619 is now narrowed to next-gen matting parity: existing Settings fields drive renderer-only in-memory matting for single images and image-only portrait pairs. Live video playback is not frame-by-frame matted; only cached video transition/backdrop frames can use matting/edge processing.
- Ticket #666 adds persistent shuffle modes: `standard` remains default/fallback, `fewer_repeats` uses existing `last_displayed` history, and the Remote control is a split shuffle toggle plus mode menu.
- Ticket #616 made next-gen the installed CLI path, removed VLC as a next-gen dependency, hardened `SystemErrorEvent` poison-pill behavior, and opened the cleanup path completed in #678.
- Ticket #678 replaces legacy controller-based MQTT with a next-gen Home Assistant MQTT infrastructure adapter and removes unreachable legacy runtime modules/tests. MQTT exposes playback/display/config state, targeted current-media delete, reboot, and shutdown; purge and clear-cache remain UI/REST only.
- Ticket #637 hardening confirms the FastAPI/Vue static asset path is implemented and keeps WebSocket media DTO location enrichment behind injected repository ports rather than hardcoded cache DB paths.
- Ticket #635 adds first-class GPIO hardware input configuration: the Settings UI edits `hardware_inputs`, backend/core validation rejects invalid mappings, and `HardwareInputService` applies changes at runtime through the HAL adapter. PIR no-motion delay is handled in core and cancels on renewed motion.
- Recent Settings UI redesign replaces the generic schema text-field renderer with domain-specific editors and safe path browsing/validation rooted at the Picframe user's home directory. Low-level runtime options remain editable in collapsed Advanced sections only when runtime support exists. Shader values are selected/stored as basenames without `.fs`/`.vs`, media extensions use fixed supported lists, and geocoding `key_list` is edited as ordered location parts with fallback chips.
- Ticket #687 decisions: Settings display geometry is Fullscreen/Custom, `model.locale` uses installed host locales from `locale -a` and drives reverse-geocoding language, Remote location filtering is search-first with selected chips, large tag lists switch to search, current media/map can be enlarged frontend-only, and Settings avoids duplicate live workflow rows owned by Remote.
- Ticket #687/#690 live reload boundary: most renderer config updates apply live or rebuild image/text/clock components on the existing pi3d display; MQTT reconnects live; media monitor reloads `pic_dir`, link-following, and media extensions; display power retargets `viewer.display_hdmi`; GStreamer accepts live video setting updates for future play commands. Renderer backend toggles `viewer.use_glx` and `viewer.use_sdl2`, plus geometry changes that would remap the actual pi3d/SDL host window, are explicit service-restart boundaries.
- Ticket #687 Settings policy: visible controls must have runtime/startup behavior and tests. `model.log_level` and `model.log_file` are visible again because runtime logging applies level/file changes live and feeds the protected Logs tab. Compatibility-only keys stay importable but hidden from live Settings: `viewer.display_power`, old menu fields, `model.update_interval`, HTTP SSL fields, legacy `http.auth`/`username`/`password`, and legacy `peripherals.*`. `model.image_attr` is hidden by design because next-gen MQTT publishes the complete normalized current-media attribute payload.
- Ticket #687 access/logging decision: Basic Auth is stored as plaintext JSON under `${PICFRAME_DATA}/basic_auth.json` with three UI scopes: none, Settings/Logs/admin actions, or complete website. Settings/admin scope leaves Remote/Appearance public through the allowlisted workflow-config API; complete-website scope also protects the SPA, static assets, media APIs, workflow API, and live web sockets. After authentication, Settings receives the saved plaintext password for inspection/editing; deleting `basic_auth.json` is the recovery path and disables password protection. Successful HTTP Basic Auth sets an HttpOnly `picframe_auth` cookie so protected WebSocket handshakes can authenticate reliably. REST bearer tokens and MQTT bearer-token payloads are deferred; MQTT security remains broker credentials plus optional TLS.
- Recent video hardening treats failed `ffprobe`, invalid probe JSON, or no video stream as unplayable during indexing; stale video cache rows with incomplete metadata are revalidated and marked inactive if extraction fails. GStreamer worker startup now preflights discoverability before sink creation and avoids requesting fullscreen when a render rectangle is supplied.
- Issue #689 refactor split the GStreamer worker internals: `gst_playback_policy.py` owns hardware/software decisions, `gtk_video_presenter.py` owns GTK4 host/window/picture behavior, and `gst_pipeline_builder.py` owns GTK playbin and GTK-compatible pipeline construction. `gst_worker.py` now focuses on IPC, lifecycle, telemetry, retry, and bus events.
- Raspberry Pi 4/labwc video validation now shows GStreamer exposes `v4l2h264dec` and `v4l2slh265dec` when `GST_V4L2_ENABLE_PROBE=1` is set before worker startup. H.264 1080p and HEVC Main 8-bit 4K playback are validated with DMABuf; HEVC Main10/HDR MOV and MOV/QuickTime 60 fps remain guarded.
- Production Wayland video requires GTK4 `gtk4paintablesink` inside a borderless fullscreen GTK4 host. Raspberry Pi/labwc uses a transparent fixed host for fullscreen plain videos so a pause label can be drawn above the live paintable; inset/custom video rectangles use an opaque fixed host, with the cached first frame behind the live paintable when sidecar metadata provides a backdrop and `viewer.background` as the fallback fill. GNOME/VM uses an opaque host colored from `viewer.background`. Fullscreen playback fills the host; custom geometry places the video paintable at the renderer-reported `viewer.display_x/y/w/h` rectangle. The worker dims the GTK4 window to 99% opacity at EOS so pi3d can redraw behind it before the video window closes; missing GTK4 presentation is reported as `gtk_presentation_unavailable`.
- The GTK4 video path hides its own cursor. Custom non-fullscreen geometry is labwc-oriented because Cage is fullscreen-kiosk oriented. Picframe-owned labwc rules give the pi3d SDL window a stable `picframe-pi3d` identifier and apply configured `MoveTo`/`ResizeTo` geometry before the window maps.
- Video first-frame handoff now behaves like a title card: pi3d blends in the cached first frame, honors `viewer.show_text_tm`, fades text out, drains clean redraw frames, then starts GStreamer. The last-frame reveal is promoted only after worker sink stats confirm at least one rendered video frame when those stats are available.
- Installer and user docs require GTK4 packages `gir1.2-gtk-4.0` and `gstreamer1.0-gtk4`; GTK3/`gtkwaylandsink` is no longer a production dependency.
- Video transition caches now use the first decoded frame and a tail-decoded final EOS frame, with fixed duration-offset sampling only as the final fallback.
- Video transition frames mirror still-image edge behavior: cached first/last frames honor matting, `blur_edges`, `edge_alpha`, and `background`; sidecars store `frame_size`, `coordinate_space=frame_pixels`, and the visible video-opening `content_rect`; playback uses that rect for the live video window for every generated frame type. Video-only matted transition-frame generation now blacks source-influenced pixels outside `content_rect`, while normal still-image matting remains unchanged. Beveled/shadowed mats intentionally inset the live video window so frame shadows remain visible, and the cached first frame is used as an opaque GTK backdrop when sidecar metadata marks matting or edge fill. If backdrop metadata lacks a stored path, playback uses the cached first-frame path as the backdrop path. Manual next/previous video navigation uses the same tokened first-frame handoff path, stale transition completions are ignored, and direct fallback uses cached sidecar metadata when it is available. Cache freshness includes both processing signatures and current geometry metadata in managed filename hashes or legacy sidecar `.meta.json`; processing version 6 invalidates version-5 matted frames with frozen edge pixels.
- Ticket #693 makes reverse-geocoded location text locale-aware: cache and queue keys include the normalized language from `model.locale`, old cache rows migrate to a `legacy` language bucket, playlist/API lookups request the active language, GPS media without an active-locale address re-enqueue lookups during overlay generation, and overlay date strings use the configured locale.
- Ticket #694 hardens brightness control: HDMI/DDC brightness is capability-probed before write, DSI/eDP/LVDS outputs use `brightnessctl`, command stderr/stdout is surfaced in `brightness_unavailable` errors, repeated identical brightness failures are suppressed, and the Remote slider sends only committed brightness values to hardware.
- Ticket #695 adds an explicit Settings clock hour mode: 24-hour writes `%H:%M`, 12-hour writes `%-I:%M %p`, Custom preserves and edits the raw `viewer.clock_format`, and the renderer/backend contract remains unchanged.
- Ticket #696 hardens media-cache repository threading: all `SQLiteMediaRepository` connection use is serialized with an `RLock`, including location lookups used by API media DTO enrichment.
- Ticket #697 improves media selection performance for large libraries: media-cache migrations add active filepath/date indexes and a rounded-coordinate location expression index; playlist folder scope uses filepath range predicates; standard shuffle happens in Python without SQL `RANDOM()`; count queries avoid location joins unless filtering by resolved location.
- Ticket #699 adds the Remote browser-memory boundary for videos: WebSocket media DTOs expose `media_type`, normal Remote video previews request only `/media/poster`, poster lookup can reuse existing managed-cache first frames when the exact transition key changes, missing poster caches show a lightweight play placeholder, expanded media uses native `<video preload="metadata">`, and `/media` explicitly supports single HTTP byte ranges. Browser codec support remains best-effort; GStreamer playback on the frame remains authoritative.
- Ticket #701 makes pause state explicit and visible: Remote sends `PAUSE`/`PLAY` but updates its icon from backend `StateEvent`s; `PlaybackEngine` publishes `PAUSED` instead of using `IDLE` as a pause alias, sends a pi3d `PAUSED` status overlay for still images and in-flight pi3d fades, freezes image/video-title-card transitions while paused, defers pending first-frame video handoff until resume, pauses/resumes a pending video if GStreamer has already started before first-frame promotion, promotes the first-frame event safely while still paused, active videos call GStreamer pause/resume plus a GTK video-window `PAUSED` label, resumed videos continue the existing paused pipeline instead of replaying the clip, and display off/on/toggle map to pause/play through `DisplayPowerManager`.
- Ticket #702 hardens GPIO config replacement: when `hardware_inputs` is saved,
  Picframe removes previous `hardware_inputs.*` flat keys before writing the
  normalized section so stale PIR actions cannot survive a switch to button, and
  stale button actions cannot survive a switch to PIR.
- Ticket #703 starts delayed PIR `no_motion` timers when hardware monitoring is
  enabled or reloaded, while preserving motion cancellation and reload/stop
  timer cleanup.
- Ticket #704 makes display power on/off idempotent: `DISPLAY_ON` only turns the
  display on and publishes `PLAY` when the tracked display state was off, and
  `DISPLAY_OFF` only turns it off and publishes `PAUSE` when the tracked state
  was on. `DISPLAY_TOGGLE` continues to use the final adapter state.
- Ticket #705 removes unsupported legacy-style `WAKE`/`SLEEP` selections from
  GPIO hardware input configuration and from the active `Command` enum.
  GPIO-facing validation and Settings options expose only supported payload-free
  runtime commands; PIR screen power should use `DISPLAY_ON` and `DISPLAY_OFF`.
- Ticket #708 hardens persistent config repository threading: all
  `SQLiteConfigRepository` connection use is serialized with an `RLock`,
  matching the media repository pattern and preventing playback/control-plane
  races such as `sqlite3.InterfaceError` while reading live viewer settings.
- Ticket #714 fixes missing date overlay for images without EXIF datetime:
  `PlaybackEngine._generate_text_string()` now falls back to the media item's
  `last_modified` timestamp when `exif_datetime` is absent or None, so stock
  images and graphics-app exports still show a date. Suggested by paddywwoof in
  Discussion #682.
- Ticket #716 ports `/dev/shm/clock.txt` support to v2 and adds
  `viewer.clock_extra_source` (off/clock_txt/ui_text) and
  `viewer.clock_extra_text` so the clock overlay can optionally show a line of
  extra text below the time. `clock_renderer.py` reads `/dev/shm/clock.txt` when
  the source is `clock_txt`, the OverlayConfig DTO carries both fields, legacy
  `configuration.yaml` import maps `viewer.clock_extra_source`/`clock_extra_text`
  and `viewer.clock_extra_text`, `playback.py` propagates the source/text into
  renderer config, and the frontend `configSchema.json` exposes them as
  advanced viewer settings. A follow-up fix added `clock_extra_text` to the
  clock renderer's visual signature so the clock block is invalidated when
  only the text changes (not just the source).
- Ticket #719 fixes alpha-test bugs reported by Paddy (@paddywwoof):
  (1) `text_renderer.py` gradient sprite z-order — gradient moved behind text
  (z=0.3 vs text z=0.1; status overlay z=0.05 in front), full-render-height
  texture scaled on GPU so it is not rebuilt when band height changes; (2)
  `clock_extra_source` is now propagated through `OverlayConfig` in
  `playback.py` and `ClockRenderer` re-reads `/dev/shm/clock.txt` on each
  `has_changed()`/`draw()` call for dynamic updates; (3) `ImageMetadataStrategy`
  and `VideoMetadataStrategy` now fall back to `last_modified` at indexing time
  when no EXIF/creation date is found, so the DB always has a valid
  `exif_datetime` and date-range SQL filters work without runtime fallbacks.
  The z-order fix (Paddy's Discussion #682 feedback) resolved the default
  gradient (`text_bkg_hgt=0.25`) occluding the text overlay.

## Immediate Next Steps
- Preserve the #618 portrait-pair decisions: videos remain single-item fullscreen and pairs apply only to images.
- Keep filesystem watchers and other OS-specific adapters outside core; use ports such as `IMediaMonitor` for core service dependencies.
- Preserve the #619 matting boundary: matting lives in renderer image preparation, not playlist, DB, REST/WebSocket, or `ImageProcessingService`.
- Preserve the #666 shuffle boundary: shuffle mode is config/playback ordering only, uses no new media DB fields, and applies after display slots are built so portrait pairs stay together.
- Preserve the #678 cleanup boundary: MQTT/Home Assistant is supported through the next-gen adapter, while legacy HTTP query control, old pi3d menu/touch UI, and VLC runtime are not carried forward.
- Preserve the #637 control-plane boundary: `main.py` chooses DB paths and injects repositories; FastAPI/WebSocket must not detect or open cache DB files directly.
- Preserve the #635 hardware-input boundary: GPIO mappings live in `hardware_inputs`, keyboard/touch shortcuts may remain compatibility config under `peripherals` but are not live Settings controls, only payload-free commands are allowed from hardware events, and PIR no-motion timers stay in `HardwareInputService`.
- Preserve the Settings UI safety boundary: do not reintroduce raw JSON/text controls for domain settings when a constrained picker/chip/token/segmented control can express the same config safely.
- Preserve the Settings Apply boundary: use live reload/component rebuild where possible, but keep renderer backend toggles (`viewer.use_glx`, `viewer.use_sdl2`) behind the explicit restart-required dialog. Only offer automatic `picframe.service` restart when the managed service is active and sudoers permits `sudo -n systemctl restart picframe.service`; otherwise save for a manual restart.
- Preserve the #687 access boundary: Basic Auth supports explicit none, Settings/Logs/admin, and complete-website scopes. Do not add bearer-token REST or MQTT authentication in this ticket.
- Preserve Pi worker V4L2 probing and caps-driven GStreamer discovery while keeping unsupported-media skips as warnings/completions rather than generic system errors.
- Preserve the GTK4-backed Wayland handoff boundary: require `gtk4paintablesink`, use the 99% GTK4 window opacity redraw handshake at EOS, keep GStreamer alpha handoff tricks and legacy sink fallbacks out of production, and report GTK presentation infrastructure failures explicitly.
- Keep final-frame extraction at indexing/cache time using tail decoding, not at video EOS runtime.
- Preserve the #691/#698 geometry contract: the generated first/last transition frame defines the live video rectangle through visible-opening sidecar `content_rect`; bevel/highlight/shadow pixels may overlap cached frame pixels and should inset the live video rectangle so the video does not cover frame shadows. When sidecar metadata provides `host_backdrop_path`, the GTK host should be opaque and render that cached frame behind the live paintable; explicit `content_fit` carries the fill intent through IPC/GTK pipeline construction.
- Preserve the #693 locale contract: reverse-geocoded addresses must be keyed or refreshed per active language, and overlay date formatting must explicitly use `model.locale` rather than relying on whichever process locale is already active.
- Preserve the #694 brightness boundary: Remote may preview slider movement locally, but hardware brightness commands should be sent only on commit/debounce; HDMI/DDC brightness should be attempted only after capability checks, and display power remains the route for a fully black screen when a monitor enforces a brightness floor.
- Preserve the #695 clock boundary: clock hour mode is an explicit display preference backed by `viewer.clock_format`; do not infer or mutate it from `model.locale`.
- Preserve the #696 repository boundary: shared SQLite connection access in `SQLiteMediaRepository` must stay serialized across API, playback, indexer, and geocoding threads.
- Preserve the #697 performance boundary: keep Remote/Settings APIs and playlist filter semantics unchanged while using indexable media-cache queries and Python-side shuffle.
- Preserve the #699 browser-preview boundary: normal Remote video previews must not mount `<video>` or request the full `/media` video URL; only the expanded media modal may stream video bytes.
- Preserve the #701 pause-state boundary: `State.PAUSED` is the public paused state for WebSocket/MQTT/Remote clients; `PAUSE` remains a legacy toggle when already paused; visible paused status is renderer-owned (`status_text` on pi3d, GTK pause label above active video); pi3d-owned image fades and video first-frame handoff fades must freeze while paused; a pending video whose GStreamer pipeline has already started must still receive pause/resume commands before first-frame promotion; active video resume must be an in-place GStreamer pipeline state change so it keeps geometry and playback position; display toggle should resolve play/pause from the HAL final `is_on()` state.
- Preserve the #702 hardware-input persistence boundary: saving the full
  `hardware_inputs` section is a replacement operation over the flat config
  store, not a merge that leaves removed nested action keys behind.
- Preserve the #703 PIR startup boundary: an enabled PIR input with a mapped
  delayed `no_motion` action starts that timer on monitoring start/reload; a
  later `motion_detected` event cancels it, and stop/reload cancels pending
  timers.
- Preserve the #704 display-power idempotency boundary: repeated `DISPLAY_ON` or
  `DISPLAY_OFF` commands that do not change tracked display state should not
  forward duplicate playback `PLAY`/`PAUSE` commands.
- Preserve the #705 GPIO command boundary: `WAKE` and `SLEEP` are not supported
  GPIO action choices; use `DISPLAY_ON`/`DISPLAY_OFF` for PIR-driven display
  power instead.
- Preserve the #708 repository boundary: shared SQLite connection access in
  both `SQLiteConfigRepository` and `SQLiteMediaRepository` must stay serialized
  across playback, API, MQTT, indexer, hardware, logging, and geocoding threads.
- Use the issue #680 VLC results as diagnostic evidence only; do not reintroduce VLC as a next-gen runtime dependency.
- Keep the GStreamer worker IPC protocol explicit and typed.
- Keep backend pytest green while Python 3.14 compatibility shims remain test-only.
- Continue using GitHub Issues/project board as the authoritative task state.
- Keep code-change workflow ticketed: create/use a GitHub issue before code changes, include the issue number in every commit message, and reference the implementing commit hash when closing the issue.

## Active Risks / Watch Items
- Test reliability is environment-sensitive because display/media dependencies and Python version may differ from the target.
- The local Python 3.14 stack exposed Starlette/AnyIO threadpool deadlocks; tests currently work around this without changing production paths.
- Memory Bank files previously accumulated repeated history; future updates should summarize current state rather than append long dated logs.
- Some frontend specification details may be aspirational; verify against `frontend/src` before assuming a feature is implemented.
- Some architecture docs describe intended design; verify against `src/picframe` before making code changes.
