## PictureFrame powered by pi3d

![picframe logo](https://github.com/helgeerbe/picframe/wiki/images/Picframe_Logo.png)

- [PictureFrame powered by pi3d](#pictureframe-powered-by-pi3d)
- [What Is PictureFrame?](#what-is-pictureframe)
- [History of PictureFrame](#history-of-pictureframe)
- [Highlights of PictureFrame](#highlights-of-pictureframe)
- [Quick Install](#quick-install)
- [Documentation](#documentation)
- [Acknowledgement](#acknowledgement)

## What Is PictureFrame?

This is a viewer for a raspberry powered picture frame. For remote control it provides a local web UI and an optional [Home Assistant](https://www.home-assistant.io/) integration via MQTT discovery.

- https://github.com/helgeerbe/picframe
- Paddy Gaunt, Jeff Godfrey, Helge Erbe
- Licence: MIT
- Next-generation development targets Raspberry Pi / Linux hosts with the FastAPI/Vue control plane and pi3d/GStreamer playback stack.

## History of PictureFrame

When I started 2019 my DIY project building a raspberry powered digital picture frame I came across Wolfgang's website [www.thedigitalpictureframe.com](https://www.thedigitalpictureframe.com/). I ran my frame with the [pi3d PictureFrame2020.py](https://github.com/pi3d/pi3d_demos) viewer, but always missed a more deeply integration to my smart home server running [Home Assistant](https://www.home-assistant.io/).As my personel corona project I decided to rewrite the viewer to my needs. Hoping  someone can make use of it.


## Highlights of PictureFrame

- Viewer
  - blend effects
  - auto mat generation
  - photo metadata overlays (title, location, date, ...)
  - live clock
  - automatic pairing of portrait images
  - optional local hardware input support
- Filter by
  - IPTC tags
  - location
  - directories
  - date
- Remote Control
  - FastAPI/Vue web UI with WebSocket live state
  - optional Home Assistant MQTT discovery and control
  - turn on/off display
  - next/prev/pause image
  - shuffle play
  - toggle metadata overlays
  - toggle clock visibility
  - retrieve image meta info (exif, IPTC)
  - reboot or shut down the host from Settings or Home Assistant

## Quick Install

For Raspberry Pi OS / Debian-style systems, download the installer from GitHub,
make it executable, and run it with `sudo`:

```bash
curl -fsSL \
  https://raw.githubusercontent.com/helgeerbe/picframe/main/docs/user/install_picframe.sh \
  -o install_picframe.sh
chmod +x install_picframe.sh
sudo ./install_picframe.sh
```

To install from the next-generation development branch, change `main` to
`v2-dev` in the URL:

```bash
curl -fsSL \
  https://raw.githubusercontent.com/helgeerbe/picframe/v2-dev/docs/user/install_picframe.sh \
  -o install_picframe.sh
chmod +x install_picframe.sh
sudo ./install_picframe.sh
```

The current helper script installs system packages, creates a Python virtual
environment, installs Picframe, and runs `picframe init --force`. The
next-generation installer tracked in issue #667 will add source/branch
selection, locale provisioning, and optional systemd boot startup.

## Next-Gen CLI

The installed `picframe` command now uses the next-generation runtime:

```bash
picframe init
picframe run
```

`picframe init` bootstraps user-space state under `~/.picframe`, including
`config.db3`, `media_cache.db3`, packaged data assets, matting resources, and
the compiled web UI. `picframe run` starts the FastAPI/Vue web control plane,
media indexing, playback engine, pi3d renderer, and GStreamer video worker.

Legacy `configuration.yaml` files are imported from the Settings UI after
initialization; direct `picframe configuration.yaml` startup is no longer the
public CLI path.

## Home Assistant / MQTT

MQTT is optional in the next-generation runtime. When `mqtt.use_mqtt` is
enabled, Picframe publishes Home Assistant discovery entities for playback,
display, selected configuration values, current media state, targeted
current-media delete actions, and host reboot/shutdown.

Maintenance actions that clean generated or database state remain in the web
UI/REST control plane: **Purge Media Database** and **Clear Image Cache** are
not exposed as MQTT/Home Assistant entities.

## Documentation

Local documentation is split by audience:

- [Documentation index](docs/README.md)
- [User manual](docs/user/manual.md)
- [Install helper script](docs/user/install_picframe.sh)
- [Architecture overview](docs/dev/architecture/overview.md)
- [Frontend architecture notes](docs/dev/architecture/frontend.md)
- [GStreamer hardware discovery notes](docs/dev/architecture/video-gst-hw-discovery.md)
- [Video hardware limits notes](docs/dev/architecture/video-hw-limits.md)

Historical project documentation can also be found at the project's
[wiki](https://github.com/helgeerbe/picframe/wiki).

Please note that PictureFrame may change significantly during its development.
Bug reports, comments, feature requests and fixes are most welcome!

To find out what's new or improved have a look at the [changelog](https://github.com/helgeerbe/picframe/wiki/Changelog).

## Acknowledgement

[glenvorel](https://github.com/glenvorel) Thanks for the new keyboard, mouse and touch screen support.

Many Thanks to Wolfgang [www.thedigitalpictureframe.com](https://www.thedigitalpictureframe.com/) for your inspiring work. 

A special Thank to Paddy Gaunt one of the authors of the [pi3d](https://github.com/pi3d/pi3d_demos) project. You are doing a great job!

Last but no least a big Thank You to Jeff Godfrey. Your auto mat feature and database driven cache is an outstanding piece of code.
