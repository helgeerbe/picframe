# Product Context

## Product Goal
Picframe is an appliance-like digital picture frame for Raspberry Pi. It should feel dependable in daily use: photos and videos rotate smoothly, the display can be controlled from the local network, and setup/maintenance are accessible without editing files by hand.

## Primary Users
- Owners of Raspberry Pi picture frames who want a polished always-on slideshow.
- Home Assistant / MQTT users who want smart-home integration.
- Maintainers and contributors modernizing the legacy viewer without losing existing feature depth.

## Core User Workflows
- View a continuous slideshow of images and supported videos.
- Use the web Remote to play, pause, skip, adjust brightness, power the display, delete media, and inspect current metadata.
- Use Settings to edit configuration, import/export config, purge stale database entries, clear cache, reboot, or shut down.
- See location context through an OpenStreetMap component when GPS metadata is present.
- Toggle backend-rendered clock/text overlays independently from frontend metadata display.

## Experience Principles
- It should "just work" on Raspberry Pi hardware without users configuring GStreamer element names.
- The UI should show useful media context while keeping the current image/video central.
- Missing metadata, missing media, unsupported files, or failed system commands should degrade gracefully and surface clear errors.
- Expensive work such as metadata extraction, reverse geocoding, media scans, and video initialization must not block playback.

## Product Boundaries
- Local-network appliance UX is prioritized over cloud-first workflows.
- Wayland is the display target; X11 compatibility is not part of the product direction.
- GitHub Issues and the project board remain the authoritative status source; this Memory Bank is a working summary.
