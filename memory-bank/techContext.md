# Tech Context

## Backend
- Python package under `src/picframe`, built with PEP 621 metadata in `pyproject.toml`.
- Runtime target: Python >= 3.11. The local `.venv` currently reports Python 3.14.4.
- Runtime dependencies include pi3d, Pillow, PyYAML, paho-mqtt, FastAPI, Uvicorn, watchdog, python-multipart, gpiozero, numpy, and media/image helpers. Watchdog is isolated in the filesystem infrastructure adapter; VLC is no longer a next-gen runtime dependency.
- Developer tooling is configured for pytest, mypy strict mode, and ruff.

## Frontend
- Vue 3 SPA in `frontend/`.
- Stack: Vite, TypeScript, Pinia, Vue Router, vue-i18n, Tailwind CSS, Heroicons, Material Design Icons, Leaflet / Vue Leaflet, axios, native WebSocket.
- Vite builds directly into `src/picframe/html` so FastAPI can serve the compiled SPA.
- Primary routes: Remote, Filters, Settings.

## Runtime Components
- The installed `picframe` console script points to the next-gen CLI in `picframe.main`.
- `picframe init` bootstraps user-space state under `~/.picframe/`.
- `picframe run` starts repositories, event bus, state tracker, optional Home Assistant MQTT adapter, HAL adapters, media monitor/indexer, pi3d renderer, GStreamer video renderer, playback engine, and FastAPI server.
- Config database defaults to `<base_dir>/data/config.db3`; media cache defaults to `<base_dir>/data/media_cache.db3`; generated cache artifacts live under `<base_dir>/data/cache`.
- `PICFRAME_DIR`, `PICFRAME_PORT`, `PICFRAME_CONFIG_DB`, `PICFRAME_MEDIA_DB`, and `PICFRAME_HTML_DIR` can override defaults.
- Runtime matting resources are copied from package data into `<base_dir>/data/mat`; the next-gen renderer uses them in memory and does not write matted-image cache files.

## Display And Media Constraints
- Wayland is the only supported display protocol.
- pi3d rendering must stay on the main thread.
- GStreamer video playback runs in `gst_worker.py` and communicates over Unix-domain-socket IPC.
- Hardware decoding decisions should be based on GStreamer registry/caps negotiation, not board-name hardcoding.
- Software decode fallback is capped by `viewer.max_software_decode_resolution`.

## Verification Notes
- Frontend type checking has passed with `npm exec vue-tsc -- -b --noEmit`.
- Backend pytest now passes in the local Python 3.14.4 `.venv`: `.venv/bin/python -m pytest -q` reported 301 passed, 1 GI deprecation warning on 2026-06-05.
- Current tests include Python 3.14 compatibility shims for Starlette/AnyIO test hangs and avoid real socket binding in API server unit tests.
