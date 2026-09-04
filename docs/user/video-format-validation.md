# Video Format Validation

This page records the video formats validated during Raspberry Pi 4 hardware
playback work for issue #668. Treat it as an observed compatibility matrix for
the tested target, not a general guarantee for every Raspberry Pi model or OS
image.

## Tested Target

- Hardware: Raspberry Pi 4 Model B Rev 1.2, aarch64
- Display session: labwc on Wayland
- GStreamer: 1.26.2
- VLC reference package: 3.0.23, Raspberry Pi OS/Debian package
  `1:3.0.23-0+deb13u1+rpt2`
- Picframe launch style: `dbus-run-session labwc --session ...`
- GStreamer hardware decoder discovery on this Pi requires
  `GST_V4L2_ENABLE_PROBE=1` before the GStreamer worker starts.
- Hardware H.264 decoder observed with probe enabled: `v4l2h264dec`
- Hardware HEVC decoder observed with probe enabled: `v4l2slh265dec`
- VLC diagnostic logs for issue #680 were captured under
  `/tmp/picframe-vlc-logs` on the target Pi.

## Official Raspberry Pi Hardware Decode Envelopes

Picframe uses these official model envelopes as a conservative first gate, then
requires GStreamer to expose the matching V4L2 decoder before selecting a
hardware pipeline. If either side is missing or the stream exceeds the listed
resolution/fps, Picframe only attempts software playback when
`viewer.max_software_decode_resolution` allows it; otherwise the video is
skipped with an `unsupported_media` warning.

| Raspberry Pi model family | H.264 hardware decode | HEVC/H.265 hardware decode | Picframe behavior |
| --- | --- | --- | --- |
| Pi 5 / Compute Module 5 | None; H.264 is software decoded on Pi 5 | 3840x2160@60 | HEVC may use `v4l2slh265dec`; H.264 is software-gated. |
| Pi 4 / Pi 400 / Compute Module 4 | 1920x1080@60 | 3840x2160@60 | Requires `v4l2h264dec` or `v4l2slh265dec`; keeps the Pi 4 Wayland HEVC presentation guards below. |
| Pi 3 / Compute Module 3 | 1920x1080@30 | None listed | H.264 above 30 fps or above 1080p is software-gated or skipped; HEVC is software-gated. |
| Pi Zero 2 W | 1920x1080@30 | None listed | H.264 above 30 fps or above 1080p is software-gated or skipped; HEVC is software-gated. |
| Pi Zero / Zero W / Zero WH | 1920x1080@30 when a matching V4L2 decoder is exposed | None listed | H.264 hardware is used only if GStreamer exposes `v4l2h264dec` or `v4l2slh264dec`; otherwise it is software-gated. |

Sources: Raspberry Pi processor documentation for Pi 5, Raspberry Pi 4 product
specifications, Raspberry Pi 3 B+ product brief, Raspberry Pi Zero 2 W product
brief, and GStreamer V4L2 stateless decoder documentation for
`v4l2slh264dec`/`v4l2slh265dec`.

## VLC Reference Finding

VLC is used here only as a diagnostic reference for issue #680. It is not a
Picframe runtime dependency and the current GStreamer guards should not be
relaxed until an equivalent GStreamer path is proven on the same hardware.

The installed VLC plugin set includes `avcodec`, `drm_avcodec`, `wl_dmabuf`,
`wl_shm`, `gles2`, and V4L2 modules. Under the same labwc/Wayland environment,
the successful VLC path is FFmpeg DRM/V4L2-request decode into the Wayland
DMABuf video output:

- H.264 1080p60 uses `h264_v4l2m2m`, `drm_prime`, and `wl_dmabuf`.
- HEVC Main/Main10 files use DRM video acceleration with `hevc_v4l2request`
  and `wl_dmabuf`.
- Forced `gles2` output can run, but representative tests showed late frames.
- Forced `wl_shm` output was much worse on this target and aborted in the
  labwc batch, so shared-memory copy is not the path to emulate.

## Good Paths

| File | Container / codec | Resolution | Observed path | Result |
| --- | --- | --- | --- | --- |
| `cropped.mp4` | MP4 / H.264 | 1728x1080 | `hardware_direct`, `v4l2h264dec`, DMABuf | Plays smoothly on Pi 4. |
| `DJI_0347.MP4` | MP4 / H.264 | 1920x1080 | `hardware_direct`, `v4l2h264dec`, DMABuf | Plays smoothly on Pi 4 and reaches EOS. |
| `unistudios_4k_h265.mp4` | MP4 / HEVC Main 8-bit | 3840x2160 | `hardware_playbin`, `v4l2slh265dec`, DMABuf | Plays smoothly through `playbin` + `waylandsink` and reaches EOS. |
| `bbb-3840x2160-cfg02.mkv` | MKV / HEVC Main 8-bit | 3840x2160, 60 fps | `hardware_playbin`, `v4l2slh265dec`, DMABuf | Plays smoothly in the standalone GStreamer `playbin` probe with `GST_V4L2_ENABLE_PROBE=1`. |
| `SampleVideo_720x480_1mb.mp4` | MP4 / H.264 | 640x480, 25 fps | Software-friendly path | Small bundled sample remains suitable for baseline playback checks. |

## Hardware Candidates Needing Picframe Validation

| File | Container / codec | Resolution | Notes |
| --- | --- | --- | --- |
| `6402b77c-b61f-4a06-96ca-c8420a2becf4.mp4` | MP4 / H.264 | 1920x1080, 60 fps | VLC plays this through `h264_v4l2m2m` + DMABuf. With `GST_V4L2_ENABLE_PROBE=1`, GStreamer exposes `v4l2h264dec`; Picframe validation is still pending. |

## Guarded Or Skipped Paths

| File | Container / codec | Resolution | Decision | Reason |
| --- | --- | --- | --- | --- |
| `vietnam.mp4` | MP4 / H.264 | 1920x1200 | Skip or software gate | Exceeds the safe Pi 4 H.264 hardware envelope of 1920x1080. Software playback is only attempted when `viewer.max_software_decode_resolution` allows it. |
| `136222-764387540_medium.mp4` | MP4 / H.264 | 2560x1440, 30 fps | Skip or software gate | Exceeds the safe Pi 4 H.264 hardware envelope. |
| `unistudiosglobe.mp4` | MP4 / H.264 | 3840x2160, 29.97 fps | Skip or software gate | Exceeds the safe Pi 4 H.264 hardware envelope. |
| `IMG_0103.MOV` | MOV / HEVC Main10 / HLG | 1920x1080 | Skip on Pi 4 Wayland | Hardware decode is available, but the decoded 10-bit/HDR format did not present smoothly through tested Wayland, GL, or RGBA conversion paths. |
| `IMG_0099.MOV` | MOV / HEVC Main10 / HLG | 1920x1080 | Skip on Pi 4 Wayland | Same presentation limitation as `IMG_0103.MOV`. |
| `test_h265.mov` | MOV / HEVC Main10 | 1920x1080, 60 fps | Skip on Pi 4 Wayland | Main10 presentation path remains unsupported on the tested Pi 4 display stack. |
| `test_265_8.mov` | MOV / HEVC Main 8-bit | 1920x1080, 60 fps | Skip on Pi 4 Wayland | GStreamer `playbin` still fails immediately with `cannot have a wl_buffer` even with `GST_V4L2_ENABLE_PROBE=1`. |
| `output_pi4_ready.mp4` | MP4 | Unknown | Discovery failure | `ffprobe` reported `moov atom not found`; Picframe should skip it as unsupported/broken media. |

## Software Candidates

| File | Container / codec | Resolution | Notes |
| --- | --- | --- | --- |
| `big-buck-bunny_trailer-.webm` | WebM / VP8 | 640x360, 25 fps | Small enough for software playback when the required GStreamer VP8 decoder is installed. |

## VLC Reference Results

These rows summarize VLC default playback logs captured under labwc/Wayland.
They explain the hardware capability VLC proves, not current Picframe behavior.

| File | VLC decoder / output | VLC log result | Picframe implication |
| --- | --- | --- | --- |
| `SampleVideo_720x480_1mb.mp4` | `h264_v4l2m2m` + `drm_prime` + `wl_dmabuf` (`DPV0`) | No late/drop/error lines in the default log. | Hardware can handle small H.264 through VLC's FFmpeg M2M path. |
| `6402b77c-b61f-4a06-96ca-c8420a2becf4.mp4` | `h264_v4l2m2m` + `drm_prime` + `wl_dmabuf` (`DPV0`) | No late/drop/error lines in the default log. | VLC proves a Pi H.264 1080p60 hardware path; GStreamer now exposes `v4l2h264dec` when V4L2 probing is enabled. |
| `136222-764387540_medium.mp4` | H.264 software `avcodec` + `wl_dmabuf` (`I420`) | `h264_v4l2m2m` fails for 2560x1440; many late/drop lines. | Keep Picframe's over-limit H.264 guard. |
| `unistudiosglobe.mp4` | H.264 software `avcodec` + `wl_dmabuf` (`I420`) | `h264_v4l2m2m` fails for 3840x2160; many late/drop lines. | Keep Picframe's over-limit H.264 guard. |
| `unistudios_4k_h265.mp4` | HEVC DRM video acceleration + `wl_dmabuf` (`DPS8`) | No late/drop/error lines in the default log. | Confirms HEVC Main 8-bit 4K30 is a good target for the current `hardware_playbin` path. |
| `bbb-3840x2160-cfg02.mkv` | HEVC DRM video acceleration + `wl_dmabuf` (`DPS8`) | Default log completed with limited lateness; forced `wl_dmabuf` had no late/drop/error lines. | GStreamer `playbin` also plays this smoothly with `GST_V4L2_ENABLE_PROBE=1`; it is no longer part of the broad HEVC 60 fps guard. |
| `test_265_8.mov` | HEVC DRM video acceleration + `wl_dmabuf` (`DPS8`) | Default and forced `wl_dmabuf` logs had no late/drop/error lines. | VLC can present HEVC Main 8-bit 1080p60; Picframe should stay guarded until a GStreamer route avoids `cannot have a wl_buffer`. |
| `test_h265.mov` | HEVC DRM video acceleration + `wl_dmabuf` (`DPS3`) | Default and forced `wl_dmabuf` logs had no late/drop/error lines. | VLC can present HEVC Main10 1080p60; current Picframe skip is still correct for GStreamer. |
| `big-buck-bunny_trailer-.webm` | VP8 software `avcodec` + `wl_dmabuf` (`I420`) | No late/drop/error lines in the default log. | Reasonable software candidate if the GStreamer VP8 decoder is installed. |
| `output_pi4_ready.mp4` | No usable video output | VLC process status was not enough; logs show demux/decoder errors and no video output. | Treat as broken media and keep indexing/playback rejection. |

Forced VLC output comparison for representative H.264 and HEVC files:

| VLC output | Result on target Pi |
| --- | --- |
| `wl_dmabuf` | Best result. Representative H.264 1080p60, HEVC Main 1080p60/4K60, and HEVC Main10 1080p60 showed DRM/DMABuf output without late/drop/error lines. |
| `gles2` | Opened with DRM/GL conversion but showed late-frame lines in representative tests. Useful for experiments, not the first path to copy. |
| `wl_shm` | Produced many late-frame lines and aborted in the labwc batch. Not suitable for high-resolution Pi playback. |

## Follow-Up GStreamer Experiments

Do these as separate implementation work before changing Picframe's guards:

- Check whether GStreamer can expose a DRM_PRIME/V4L2-request decode path
  equivalent to VLC's FFmpeg `drm_avcodec` behavior.
- Test HEVC Main 8-bit and Main10 with `v4l2slh265dec` while preserving DMABuf
  caps and DRM modifiers all the way to `waylandsink`.
- Continue validating H.264 1080p60 with `v4l2h264dec` now that
  `GST_V4L2_ENABLE_PROBE=1` exposes the decoder.
- Compare any candidate path against `wl_dmabuf` first; use `gles2` only if it
  proves smoother on target logs and real display.
- Keep `wl_shm` out of high-resolution playback experiments unless the target
  display stack changes substantially.
- Keep the current skip/software guards until each candidate path is validated
  with real files and frame/drop diagnostics.

## Notes

- H.264 on Pi 4 is guarded at 1920x1080 for hardware playback. Larger H.264
  files should not be sent to the Pi 4 hardware decoder.
- HEVC Main 8-bit can be hardware decoded up to 3840x2160 on the tested Pi 4,
  and the working presentation path is `playbin` with `waylandsink`.
- HEVC Main 8-bit 50/60 fps is no longer globally unsupported. MKV 4K60
  playback is validated; MOV/QuickTime 60 fps remains guarded because
  `test_265_8.mov` still fails with `cannot have a wl_buffer`.
- HEVC Main10/HDR MOV files may decode in hardware but still fail practical
  display. Picframe skips these files on the tested Pi 4 path with a clear
  unsupported-media diagnostic instead of showing a frozen or stuttering frame.
- VLC proves that some still-guarded HEVC MOV/Main10 files can play on this Pi
  through FFmpeg DRM/V4L2-request plus `wl_dmabuf`. That remains a future
  GStreamer research target for those guarded paths.
- Ubuntu VM playback remains software-friendly. It is expected to use software
  decoders when hardware acceleration is unavailable.
