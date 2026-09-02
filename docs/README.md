# Picframe Documentation

Documentation is split by audience.

## Quick Install

Download and run the current installer helper from GitHub:

```bash
curl -fsSL \
  https://raw.githubusercontent.com/helgeerbe/picframe/main/docs/user/install_picframe.sh \
  -o install_picframe.sh
chmod +x install_picframe.sh
sudo ./install_picframe.sh
```

Use `--branch v2-dev` when validating next-generation installer changes:

```bash
sudo ./install_picframe.sh --branch v2-dev
```

Add `--enable-service` to create and enable the optional `picframe.service`
systemd boot service.

When Picframe is running, open the Web Control Plane at
`http://<picframe-host>:9000/`. The Remote and Settings views are served by the
FastAPI backend, and API docs are available at `/docs`.

## User Docs

- [User manual](user/manual.md)
- [Video format validation](user/video-format-validation.md)
- [Install helper script](user/install_picframe.sh)

## Developer Docs

- [Developer workflow](dev/workflow.md)
- [Architecture overview](dev/architecture/overview.md)
- [Frontend architecture notes](dev/architecture/frontend.md)
- [GStreamer hardware discovery notes](dev/architecture/video-gst-hw-discovery.md)
- [Video hardware limits notes](dev/architecture/video-hw-limits.md)

## Phase 2B Documentation Coverage

The next-generation CLI and Web Control Plane documentation covers:

- `picframe init` and `picframe run` usage in the README and user manual.
- The `~/.picframe` runtime layout, including `config.db3`,
  `media_cache.db3`, generated cache files, packaged renderer assets, and the
  compiled SPA.
- Web Control Plane access at `http://<picframe-host>:9000/`, Remote and
  Settings view responsibilities, REST API docs at `/docs`, and live
  synchronization over `/ws/state`.
- Developer architecture updates, including the component diagram and
  responsibility table in the architecture overview.

The video hardware documents describe target architecture for ongoing
GStreamer hardening. Treat them as design notes, not as a guarantee that every
detail is already implemented.
