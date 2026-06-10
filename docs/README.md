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

## User Docs

- [User manual](user/manual.md)
- [Video format validation](user/video-format-validation.md)
- [Install helper script](user/install_picframe.sh)

## Developer Docs

- [Architecture overview](dev/architecture/overview.md)
- [Frontend architecture notes](dev/architecture/frontend.md)
- [GStreamer hardware discovery notes](dev/architecture/video-gst-hw-discovery.md)
- [Video hardware limits notes](dev/architecture/video-hw-limits.md)

The video hardware documents describe target architecture for ongoing
GStreamer hardening. Treat them as design notes, not as a guarantee that every
detail is already implemented.
