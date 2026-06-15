# Active Context

## Current Focus
The active branch is `gtk4`, focused on the next-gen GTK4/GStreamer Wayland
video handoff: avoid EOS flicker, preserve fullscreen and custom display
geometry, and keep text overlays out of the surface revealed when video starts
or stops.

## Current Repo State
- Branch: `gtk4`.
- `.Codexrules` is a local instruction file and is ignored by git.
- The source tree is centered on the next-gen `main.py`, `core`, `api`, and `infrastructure` architecture; broad legacy runtime modules were removed during #678 while reusable helpers such as matting/geocoding remain where still imported.

## Recently Established Context
- Architecture docs confirm Clean Architecture, strict EDA, dual SQLite databases, HAL ports/adapters, FastAPI/Vue control plane, and Wayland-only display targeting.
- `docs/dev/architecture/video-gst-hw-discovery.md` and `docs/dev/architecture/video-hw-limits.md` refine video playback toward GStreamer registry/caps-driven hardware discovery and threshold-based software fallback rejection.
- `docs/dev/architecture/frontend.md` defines a Vue 3 SPA with Remote, Filters, and Settings views; REST config/maintenance endpoints; WebSocket state; i18n; Leaflet maps; and separate narrative vs. technical metadata presentation.
- Issue #648 is closed after implementing Remote media-selection controls, legacy-compatible location/tag filter expressions, live match counts, playlist filtering/sorting, timing propagation, filter-options API, shuffle transport control refinements, and displayed-count metadata.
- Issues #676 and #677 are closed after documenting legacy `configuration.yaml` import and normalizing supported legacy keys through `/api/config/import-yaml`.
- Recent #618 work added clickable current-media tags in Remote, managed cache storage for generated video transition frames, Clear Image Cache API/service wiring, playback guards so videos continue after generated frames are cleared, image-only portrait-pair display items/rendering/Remote UX, pair delete target selection, internal monitor/indexer/processing lifecycle controls, and real-media Raspberry Pi validation.
- Recent media-cache lifecycle cleanup keeps restart sync idempotent, preserves display counters across reindex, soft-inactivates temporarily missing media, and hard-removes cache rows only after explicit user delete or purge.
- Recent #611 cleanup moved watchdog media monitoring behind a core `IMediaMonitor` port; watchdog now lives in infrastructure and differential sync emits core `FileChangeEvent`s directly.
- Ticket #619 is now narrowed to next-gen matting parity: existing Settings fields drive renderer-only in-memory matting for single images and image-only portrait pairs, while videos remain unmatted and no persistent mat cache artifacts are created.
- Ticket #666 adds persistent shuffle modes: `standard` remains default/fallback, `fewer_repeats` uses existing `last_displayed` history, and the Remote control is a split shuffle toggle plus mode menu.
- Ticket #616 made next-gen the installed CLI path, removed VLC as a next-gen dependency, hardened `SystemErrorEvent` poison-pill behavior, and opened the cleanup path completed in #678.
- Ticket #678 replaces legacy controller-based MQTT with a next-gen Home Assistant MQTT infrastructure adapter and removes unreachable legacy runtime modules/tests. MQTT exposes playback/display/config state, targeted current-media delete, reboot, and shutdown; purge and clear-cache remain UI/REST only.
- Ticket #637 hardening confirms the FastAPI/Vue static asset path is implemented and keeps WebSocket media DTO location enrichment behind injected repository ports rather than hardcoded cache DB paths.
- Ticket #635 adds first-class GPIO hardware input configuration: the Settings UI edits `hardware_inputs`, backend/core validation rejects invalid mappings, and `HardwareInputService` applies changes at runtime through the HAL adapter. PIR no-motion delay is handled in core and cancels on renewed motion.
- Recent Settings UI redesign replaces the generic schema text-field renderer with domain-specific editors and safe path browsing/validation rooted at the Picframe user's home directory. Low-level runtime options remain editable in collapsed Advanced sections only when runtime support exists. Shader values are selected/stored as basenames without `.fs`/`.vs`, media extensions use fixed supported lists, and geocoding `key_list` is edited as ordered location parts with fallback chips.
- Ticket #687 decisions: Settings display geometry is Fullscreen/Custom, `model.locale` uses installed host locales from `locale -a` and drives reverse-geocoding language, Remote location filtering is search-first with selected chips, large tag lists switch to search, current media/map can be enlarged frontend-only, and Settings avoids duplicate live workflow rows owned by Remote.
- Ticket #687 live reload boundary: renderer config updates restart only pi3d when needed; MQTT reconnects live; media monitor reloads `pic_dir`, link-following, and media extensions; display power retargets `viewer.display_hdmi`; GStreamer accepts live video setting updates for future play commands; full service restart remains manual troubleshooting only.
- Ticket #687 Settings policy: visible controls must have runtime/startup behavior and tests. `model.log_level` and `model.log_file` are visible again because runtime logging applies level/file changes live and feeds the protected Logs tab. Compatibility-only keys stay importable but hidden from live Settings: `viewer.display_power`, old menu fields, `model.update_interval`, HTTP SSL fields, legacy `http.auth`/`username`/`password`, and legacy `peripherals.*`. `model.image_attr` is hidden by design because next-gen MQTT publishes the complete normalized current-media attribute payload.
- Ticket #687 access/logging decision: Basic Auth is stored as plaintext JSON under `${PICFRAME_DATA}/basic_auth.json` with three UI scopes: none, Settings/Logs/admin actions, or complete website. Settings/admin scope leaves Remote/Filters public through the allowlisted workflow-config API; complete-website scope also protects the SPA, static assets, media APIs, workflow API, and live web sockets. After authentication, Settings receives the saved plaintext password for inspection/editing; deleting `basic_auth.json` is the recovery path and disables password protection. Successful HTTP Basic Auth sets an HttpOnly `picframe_auth` cookie so protected WebSocket handshakes can authenticate reliably. REST bearer tokens and MQTT bearer-token payloads are deferred; MQTT security remains broker credentials plus optional TLS.
- Recent video hardening treats failed `ffprobe`, invalid probe JSON, or no video stream as unplayable during indexing; stale video cache rows with incomplete metadata are revalidated and marked inactive if extraction fails. GStreamer worker startup now preflights discoverability before sink creation and avoids requesting fullscreen when a render rectangle is supplied.
- Raspberry Pi 4/labwc video validation now shows GStreamer exposes `v4l2h264dec` and `v4l2slh265dec` when `GST_V4L2_ENABLE_PROBE=1` is set before worker startup. H.264 1080p and HEVC Main 8-bit 4K playback are validated with DMABuf; HEVC Main10/HDR MOV and MOV/QuickTime 60 fps remain guarded.
- Production Wayland video now prefers GTK4 `playbin` + `gtk4paintablesink` inside a borderless transparent GTK4 host. Fullscreen playback fills the host; custom geometry uses a fullscreen transparent host and places the video paintable at `viewer.display_x/y/w/h`. The worker dims the GTK4 window to 99% opacity at EOS so pi3d can redraw behind it before the video window closes; fallback remains `waylandsink` with explicit render rectangles.
- The GTK4 video path hides its own cursor. Custom non-fullscreen geometry is labwc-oriented because Cage is fullscreen-kiosk oriented. Picframe-owned labwc rules give the pi3d SDL window a stable `picframe-pi3d` identifier and apply configured `MoveTo`/`ResizeTo` geometry before the window maps.
- Video first-frame handoff now behaves like a title card: pi3d blends in the cached first frame, honors `viewer.show_text_tm`, fades text out, drains clean redraw frames, then starts GStreamer. The last-frame reveal is promoted only after worker sink stats confirm at least one rendered video frame when those stats are available.
- Installer and user docs require GTK4 packages `gir1.2-gtk-4.0` and `gstreamer1.0-gtk4`; GTK3/`gtkwaylandsink` is no longer a production dependency.
- Video transition caches now use the first decoded frame and a tail-decoded final EOS frame, with fixed duration-offset sampling only as the final fallback.

## Immediate Next Steps
- Preserve the #618 portrait-pair decisions: videos remain single-item fullscreen and pairs apply only to images.
- Keep filesystem watchers and other OS-specific adapters outside core; use ports such as `IMediaMonitor` for core service dependencies.
- Preserve the #619 matting boundary: matting lives in renderer image preparation, not playlist, DB, REST/WebSocket, or `ImageProcessingService`.
- Preserve the #666 shuffle boundary: shuffle mode is config/playback ordering only, uses no new media DB fields, and applies after display slots are built so portrait pairs stay together.
- Preserve the #678 cleanup boundary: MQTT/Home Assistant is supported through the next-gen adapter, while legacy HTTP query control, old pi3d menu/touch UI, and VLC runtime are not carried forward.
- Preserve the #637 control-plane boundary: `main.py` chooses DB paths and injects repositories; FastAPI/WebSocket must not detect or open cache DB files directly.
- Preserve the #635 hardware-input boundary: GPIO mappings live in `hardware_inputs`, keyboard/touch shortcuts may remain compatibility config under `peripherals` but are not live Settings controls, only payload-free commands are allowed from hardware events, and PIR no-motion timers stay in `HardwareInputService`.
- Preserve the Settings UI safety boundary: do not reintroduce raw JSON/text controls for domain settings when a constrained picker/chip/token/segmented control can express the same config safely.
- Preserve the #687 Apply boundary: do not add an automatic `systemctl restart picframe.service` path for Settings Apply, and do not add a new passwordless sudo rule for service restart as part of this ticket.
- Preserve the #687 access boundary: Basic Auth supports explicit none, Settings/Logs/admin, and complete-website scopes. Do not add bearer-token REST or MQTT authentication in this ticket.
- Preserve Pi worker V4L2 probing and caps-driven GStreamer discovery while keeping unsupported-media skips as warnings/completions rather than generic system errors.
- Preserve the GTK4-backed Wayland handoff boundary: prefer `gtk4paintablesink`, use the 99% GTK4 window opacity redraw handshake at EOS, keep GStreamer alpha/videoconvert handoff tricks out of production, and fall back to explicit `waylandsink` render rectangles when GTK4 or geometry confirmation is unavailable.
- Keep final-frame extraction at indexing/cache time using tail decoding, not at video EOS runtime.
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
