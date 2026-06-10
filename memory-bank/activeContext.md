# Active Context

## Current Focus
The current implementation focus is next-gen control-plane parity cleanup plus
GStreamer/video reliability hardening. Caps-driven hardware discovery remains
an active architectural stream, but invalid/unplayable video filtering is now
implemented at indexing time.

## Current Repo State
- Branch: `v2-dev`, tracking `origin/v2-dev`.
- Known local modification before this Memory Bank update: `.gitignore` ignores `.Codexrules`.
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
- Recent Settings UI redesign replaces the generic schema text-field renderer with domain-specific editors and safe path browsing/validation rooted at the Picframe user's home directory. Low-level runtime options remain editable in collapsed Advanced sections. Shader values are selected/stored as basenames without `.fs`/`.vs`, image attributes and media extensions use fixed supported lists, and geocoding `key_list` is edited as ordered location parts with fallback chips.
- Recent video hardening treats failed `ffprobe`, invalid probe JSON, or no video stream as unplayable during indexing; stale video cache rows with incomplete metadata are revalidated and marked inactive if extraction fails. GStreamer worker startup now preflights discoverability before sink creation and avoids requesting fullscreen when a render rectangle is supplied.
- Raspberry Pi 4/labwc video validation now shows GStreamer exposes `v4l2h264dec` and `v4l2slh265dec` when `GST_V4L2_ENABLE_PROBE=1` is set before worker startup. H.264 1080p and HEVC Main 8-bit 4K playback are validated with DMABuf; HEVC Main10/HDR MOV and MOV/QuickTime 60 fps remain guarded.

## Immediate Next Steps
- Preserve the #618 portrait-pair decisions: videos remain single-item fullscreen and pairs apply only to images.
- Keep filesystem watchers and other OS-specific adapters outside core; use ports such as `IMediaMonitor` for core service dependencies.
- Preserve the #619 matting boundary: matting lives in renderer image preparation, not playlist, DB, REST/WebSocket, or `ImageProcessingService`.
- Preserve the #666 shuffle boundary: shuffle mode is config/playback ordering only, uses no new media DB fields, and applies after display slots are built so portrait pairs stay together.
- Preserve the #678 cleanup boundary: MQTT/Home Assistant is supported through the next-gen adapter, while legacy HTTP query control, old pi3d menu/touch UI, and VLC runtime are not carried forward.
- Preserve the #637 control-plane boundary: `main.py` chooses DB paths and injects repositories; FastAPI/WebSocket must not detect or open cache DB files directly.
- Preserve the #635 hardware-input boundary: GPIO mappings live in `hardware_inputs`, keyboard/touch shortcuts stay in `peripherals`, only payload-free commands are allowed from hardware events, and PIR no-motion timers stay in `HardwareInputService`.
- Preserve the Settings UI safety boundary: do not reintroduce raw JSON/text controls for domain settings when a constrained picker/chip/token/segmented control can express the same config safely.
- Preserve Pi worker V4L2 probing and caps-driven GStreamer discovery while keeping unsupported-media skips as warnings/completions rather than generic system errors.
- Use the issue #680 VLC results as diagnostic evidence only; do not reintroduce VLC as a next-gen runtime dependency.
- Keep the GStreamer worker IPC protocol explicit and typed.
- Keep backend pytest green while Python 3.14 compatibility shims remain test-only.
- Continue using GitHub Issues/project board as the authoritative task state.

## Active Risks / Watch Items
- Test reliability is environment-sensitive because display/media dependencies and Python version may differ from the target.
- The local Python 3.14 stack exposed Starlette/AnyIO threadpool deadlocks; tests currently work around this without changing production paths.
- Memory Bank files previously accumulated repeated history; future updates should summarize current state rather than append long dated logs.
- Some frontend specification details may be aspirational; verify against `frontend/src` before assuming a feature is implemented.
- Some architecture docs describe intended design; verify against `src/picframe` before making code changes.
