# Architectural Pattern: Dynamic Hardware Limitation Detection

## 1. The Problem: Hardware-Specific Decoding Limits
While GStreamer can dynamically discover *which* codecs are hardware-accelerated, specific hardware decoders have hard limits on the media they can process. For example, a hardware H.264 decoder might be capped at 1080p (1920x1080) at 30fps, while the same SoC might support HEVC (H.265) up to 4K (3840x2160) at 60fps. If we feed a 4K H.264 video into a 1080p-limited hardware decoder, the pipeline will fail, hang, or crash the display server.

## 2. The Anti-Pattern: OS/Hardware Sniffing
The naive approach is to read `/proc/cpuinfo` or `/proc/device-tree/model` to determine the board (e.g., "Raspberry Pi 4 Model B") and hardcode a lookup table of its limits. 
**Why this fails:**
*   **Brittle:** It requires constant updates for new hardware revisions (Pi 5, Compute Modules, alternative SBCs like Orange Pi).
*   **Inaccurate:** Firmware updates or kernel changes (e.g., switching from legacy MMAL to V4L2) can change capabilities without changing the hardware model.

## 3. The Recommended Pattern: Caps-Driven Limit Detection
GStreamer's architecture already solves this problem. Hardware decoder elements (like `v4l2h264dec`) explicitly declare their maximum supported resolutions and framerates within their **Pad Templates** in the GStreamer Registry. We must leverage this as the single source of truth.

### 3.1 Pre-flight Metadata Extraction
Before GStreamer is even invoked, we utilize the `VideoMetadataStrategy` (powered by `ffprobe`) to extract the exact characteristics of the incoming media:
*   `codec` (e.g., `h264`)
*   `width` (e.g., `3840`)
*   `height` (e.g., `2160`)
*   `framerate` (e.g., `60/1`)

### 3.2 GStreamer Registry Introspection
During application startup (or cached on first use), we query the `Gst.Registry` for hardware decoders. Instead of just checking if the decoder *exists*, we inspect its `Sink Pad Template`:
1.  Find the hardware decoder for the target codec (e.g., `v4l2h264dec`).
2.  Extract its `Gst.Caps`.
3.  Read the `width` and `height` ranges defined in the caps. For a 1080p-limited decoder, the caps will explicitly state `width=(int)[ 1, 1920 ], height=(int)[ 1, 1080 ]`.

### 3.3 The Pre-Playback Decision Matrix
When `play(media_item)` is called, we perform a **Pre-flight Caps Intersection**:
We construct a temporary `Gst.Caps` object representing the media file (e.g., `video/x-h264, width=3840, height=2160`) and attempt to intersect it with the hardware decoder's template caps.

*   **Scenario A: Intersection Succeeds (Media <= HW Limits)**
    *   *Action:* Proceed with the hardware-accelerated pipeline.
*   **Scenario B: Intersection Fails (Media > HW Limits)**
    *   *Action:* We now know hardware decoding is impossible. We must evaluate the fallback strategy.

## 4. Handling the Fallback: The "Unplayable" Scenario
When hardware decoding is ruled out due to resolution limits, falling back to software decoding (e.g., `avdec_h264`) for 4K video on an SBC like a Raspberry Pi is almost always a fatal UX error. The CPU will peg at 100%, thermal throttling will occur, and playback will be a slideshow (e.g., 2-3 fps).

### 4.1 Graceful Degradation Strategy
Instead of a blind software fallback, the architecture should implement a **Threshold-Based Rejection**:
1.  **Define a Software Ceiling:** In the application configuration, define the maximum resolution acceptable for software decoding (e.g., `max_software_decode_resolution: 1280x720`).
2.  **Evaluate:** If the media exceeds the hardware limits AND exceeds the `max_software_decode_resolution`:
    *   **DO NOT** attempt playback.
    *   **Emit Event:** Publish a `PlaybackSkippedEvent` (or `SystemErrorEvent` with a specific `UNSUPPORTED_MEDIA` code).
    *   **Log:** *"Media resolution (3840x2160) exceeds hardware decoder limits (1920x1080) and is too large for software fallback. Skipping file."*
    *   **Action:** The `PlaybackEngine` catches this event and immediately transitions to the next media item in the playlist, preserving the appliance's uptime and UX.

## 5. Conclusion
By relying on GStreamer's Pad Templates rather than hardware sniffing, the application becomes completely hardware-agnostic. It will automatically support 4K on devices with 4K hardware decoders, and gracefully skip 4K files on devices limited to 1080p, ensuring a stable, crash-free experience across all generations of hardware.