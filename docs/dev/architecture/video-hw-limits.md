# Architectural Pattern: Model-Aware Hardware Limitation Detection

Status: implemented guard pattern. The current video stack combines official
Raspberry Pi model decode envelopes, runtime GStreamer V4L2 decoder discovery,
and configurable software fallback limits.

## 1. The Problem: Hardware-Specific Decoding Limits
While GStreamer can dynamically discover *which* codecs are hardware-accelerated, specific hardware decoders have hard limits on the media they can process. For example, a hardware H.264 decoder might be capped at 1080p (1920x1080) at 30fps, while the same SoC might support HEVC (H.265) up to 4K (3840x2160) at 60fps. If we feed a 4K H.264 video into a 1080p-limited hardware decoder, the pipeline will fail, hang, or crash the display server.

## 2. The Hybrid Source Of Truth

GStreamer can discover which decoder elements are installed, but Raspberry Pi
generations differ in codec support even when a codec is common in user media.
Picframe therefore requires two independent confirmations before choosing a
hardware path:

*   **Official model envelope:** `/proc/device-tree/model` is mapped to a small
    Raspberry Pi family table for H.264 and HEVC/H.265.
*   **Runtime decoder availability:** GStreamer must expose the matching V4L2
    decoder element for that codec.

The model table intentionally stays conservative:

| Model family | H.264 | HEVC/H.265 |
| --- | --- | --- |
| Pi 5 / Compute Module 5 | Software only | 3840x2160@60 |
| Pi 4 / Pi 400 / Compute Module 4 | 1920x1080@60 | 3840x2160@60 |
| Pi 3 / Compute Module 3 | 1920x1080@30 | Software only |
| Pi Zero 2 W | 1920x1080@30 | Software only |
| Pi Zero / Zero W / Zero WH | 1920x1080@30 if V4L2 exposes H.264 | Software only |

## 3. Runtime Decoder Discovery
GStreamer remains the final authority on what is usable in the running OS
image. Picframe checks for codec-specific V4L2 hardware decoders:

*   H.264: `v4l2h264dec` or `v4l2slh264dec`
*   HEVC/H.265: `v4l2slh265dec`

On Raspberry Pi, these elements may only appear after
`GST_V4L2_ENABLE_PROBE=1`; the `GstVideoRenderer` sets this for its worker on
Pi hardware unless the user already supplied a value.

### 3.1 Pre-flight Metadata Extraction
Before GStreamer is even invoked, we utilize the `VideoMetadataStrategy` (powered by `ffprobe`) to extract the exact characteristics of the incoming media:
*   `codec` (e.g., `h264`)
*   `width` (e.g., `3840`)
*   `height` (e.g., `2160`)
*   `framerate` (e.g., `60/1`)

### 3.2 The Pre-Playback Decision Matrix
When `play(media_item)` is called, the worker compares the stream facts with
the model table and then checks GStreamer:

*   **Model supports codec, resolution, and fps; decoder exists:** use a
    hardware pipeline.
*   **Model does not support the codec:** force software only if the stream is
    within `viewer.max_software_decode_resolution`; otherwise skip.
*   **Stream exceeds model resolution or fps:** force software only if the
    software ceiling allows it; otherwise skip.
*   **Decoder is missing from GStreamer:** force software only if the software
    ceiling allows it; otherwise skip.

## 4. Handling the Fallback: The "Unplayable" Scenario
When hardware decoding is ruled out due to model support, missing decoder
elements, resolution, or framerate limits, falling back to software decoding
(e.g., `avdec_h264`) for large video on an SBC like a Raspberry Pi is almost
always a fatal UX error. The CPU will peg at 100%, thermal throttling will
occur, and playback will be a slideshow (e.g., 2-3 fps).

### 4.1 Graceful Degradation Strategy
Instead of a blind software fallback, the architecture should implement a **Threshold-Based Rejection**:
1.  **Define a Software Ceiling:** In the application configuration, define the maximum resolution acceptable for software decoding (e.g., `max_software_decode_resolution: 1280x720`).
2.  **Evaluate:** If the media exceeds the hardware limits AND exceeds the `max_software_decode_resolution`:
    *   **DO NOT** attempt playback.
    *   **Emit Event:** Publish a `PlaybackSkippedEvent` (or `SystemErrorEvent` with a specific `UNSUPPORTED_MEDIA` code).
    *   **Log:** *"Media resolution (3840x2160) exceeds hardware decoder limits (1920x1080) and is too large for software fallback. Skipping file."*
    *   **Action:** The `PlaybackEngine` catches this event and immediately transitions to the next media item in the playlist, preserving the appliance's uptime and UX.

## 5. Conclusion
By combining official Raspberry Pi limits with runtime GStreamer discovery,
Picframe avoids feeding unsupported streams to fragile hardware paths while
still adapting to the installed OS image. Known-safe hardware paths are used
when both model and decoder agree; everything else is software-gated or skipped
so playback remains stable across Pi 5, Pi 4, Pi 3, Zero 2 W, and Zero-class
targets.
