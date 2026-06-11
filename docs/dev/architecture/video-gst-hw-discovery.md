# Architectural Evaluation: Dynamic Hardware Acceleration Discovery in GStreamer

Status: target architecture / design note. The next-gen runtime already uses
GStreamer for video handoff, but this document describes the desired
caps-driven discovery and observability direction for continued hardware
acceleration hardening.

## 1. Executive Summary
This document evaluates the architectural approaches for managing hardware-accelerated video playback on Raspberry Pi (Wayland) using GStreamer. It contrasts static configurations with dynamic discovery mechanisms and proposes an optimal, robust design that leverages GStreamer's native registry and caps negotiation. This design eliminates manual configuration, ensures cross-generation Raspberry Pi compatibility, and provides deterministic observability for software fallbacks.

## 2. Tradeoff Analysis: Hardcoding vs. User Configuration vs. Dynamic Discovery

### 2.1 Hardcoding Supported Combinations
*   **Approach:** Explicitly defining dictionaries mapping codecs (e.g., H.264) and pixel formats (e.g., YUV420P) to specific GStreamer elements (e.g., `v4l2h264dec`).
*   **Pros:** Highly deterministic; easy to implement initially.
*   **Cons:** Extremely brittle. The Raspberry Pi ecosystem is fragmented (Pi 3 uses MMAL/OpenMAX, Pi 4 uses V4L2 for H.264/H.265, Pi 5 drops hardware H.264 decoding entirely). Hardcoding requires constant maintenance and OS-level conditional logic.

### 2.2 User-Configurable Settings
*   **Approach:** Exposing codec-to-element mappings in `config.yaml` for the user to define.
*   **Pros:** Shifts the maintenance burden off the developers; highly flexible.
*   **Cons:** Terrible User Experience (UX). Users rarely understand GStreamer element names or pixel format constraints. It violates the "it just works" principle of an appliance-like digital picture frame.

### 2.3 Dynamic Discovery (Recommended)
*   **Approach:** Querying the GStreamer environment at runtime to discover available hardware decoders and their supported capabilities.
*   **Pros:** Zero configuration required; automatically adapts to Pi 3, 4, 5, or even x86 Linux environments; future-proof.
*   **Cons:** Higher initial architectural complexity; requires deep integration with GStreamer's C-based API bindings (PyGObject).

## 3. Explicit Mapping vs. Dynamic Caps Negotiation

Explicit mapping patterns (e.g., `if codec == 'h264' and format == 'yuv420p': use v4l2h264dec`) are an anti-pattern in GStreamer. GStreamer is fundamentally designed around **Caps (Capabilities) Negotiation**. 

Elements define Pad Templates that describe exactly what formats they can accept (Sink) and produce (Source). Instead of manually mapping formats, the architecture should rely on GStreamer's ability to intersect the Caps of the media file with the Caps of available decoder elements. If the intersection is non-empty, the pipeline can link.

## 4. Proposed Optimal Architecture: The "Discovery-Driven" Approach

To achieve a zero-configuration, highly observable pipeline, we must combine proactive capability discovery with reactive pipeline introspection.

### Current Guardrail: Playable-Stream Validation
Before a video enters the playlist, `VideoMetadataStrategy` treats `ffprobe`
failure, invalid probe JSON, or absence of a video stream as an unplayable
file. The media indexer marks any existing cache row inactive for that path, so
stale placeholder rows do not remain in rotation. Transition-frame extraction is
best-effort only: frame-cache failure reduces handoff smoothness but does not
make an otherwise playable video ineligible.

The GStreamer worker repeats a lightweight `GstPbutils.Discoverer` check before
building a pipeline. This protects against stale cache rows and emits a clear
error such as "No playable video stream found" before any Wayland sink is
created. When Picframe supplies an explicit render rectangle, the worker does
not also request sink fullscreen; the rectangle is the positioning contract.

### Current Handoff Strategy: GTK Wayland Presentation
Raspberry Pi 4 / labwc PoC testing showed that a fully covering plain
`waylandsink` surface can trigger a short pi3d redraw flicker when the video
surface closes at EOS. Production playback therefore prefers a `playbin` +
`gtkwaylandsink` path on Wayland when the worker can create a borderless GTK3
window whose size and position exactly match Picframe's configured pi3d display
rectangle (`viewer.display_x/y/w/h`).

This path keeps video playback GPU-friendly: it does not add GStreamer `alpha`,
`videoconvert`, or `videoscale` elements just for handoff. The GTK window is
created and pumped inside the out-of-process GStreamer worker, hides its own
cursor, and EOS still flows back through IPC to the playback engine. If the
rectangle is effectively fullscreen, the worker requests a fullscreen GTK
window. Custom non-fullscreen rectangles are labwc-oriented because Cage is a
fullscreen kiosk compositor; the installer provisions a Picframe-owned labwc
config to disable server decorations for the GTK video window. If GTK3,
`gtkwaylandsink`, or geometry confirmation is unavailable, the worker falls
back to the prior `waylandsink` render-rectangle path.

Transition-frame caching is also aligned with EOS handoff. The first cached
frame is extracted from the first decoded video frame. The final cached frame
is extracted by seeking near the end and decoding a short tail window through
EOS, with larger tail windows and the older fixed duration-offset sampler used
only as fallbacks.

### Phase 1: Startup Capability Discovery (The Registry)
During application initialization, the `GstVideoRenderer` spawns the `gst_worker.py` subprocess. The subprocess queries the `Gst.Registry`.
1.  Iterate through all features in the registry.
2.  Filter for elements where the `klass` metadata contains `Codec/Decoder/Video` AND `Hardware`.
3.  Extract the `Gst.Caps` from the sink pad templates of these hardware elements.
4.  Store this as a "Hardware Capability Matrix" in the subprocess memory.

### Phase 2: Pre-Playback Evaluation (IPC `check_caps`)
When `play(media_item)` is called in the main process:
1.  The main process sends a `check_caps` IPC command to the subprocess with the media URI.
2.  The subprocess retrieves the media's codec and pixel format.
3.  The subprocess converts this metadata into a `Gst.Caps` object and intersects it with the Hardware Capability Matrix.
4.  **Decision:** The subprocess sends a `caps_result` IPC event back to the main process. If unsupported, the main process can immediately log the warning and emit a `SystemErrorEvent` before playback starts.

### Phase 3: Pipeline Introspection and Observability (`autoplug-select`)
The subprocess uses `uridecodebin` (or `playbin3` with deep signal hooks) to dynamically construct the decoding pipeline.

1.  The subprocess connects to the `autoplug-select` signal of `uridecodebin`.
2.  This signal is fired every time the autoplugger considers an element for the pipeline.
3.  **Observability Hook:** Inside the callback, the subprocess inspects the factory's `klass`.
    *   If the autoplugger selects a software decoder (lacking the `Hardware` class) for a heavy codec, it intercepts this decision.
    *   The subprocess sends a `warning` IPC event (type: `software_fallback`) to the main process.
4.  The main process receives this IPC event and translates it into a `PerformanceWarningEvent` on the main Event Bus.

## 5. Ensuring Reliable Software Fallback

By using `uridecodebin` combined with a custom Wayland sink bin (to handle the `pi3d` alpha requirements), we get the best of both worlds:
1.  **Reliability:** `uridecodebin` will exhaust all hardware options. If they fail negotiation, it will automatically fall back to software elements (like `avdec_h264`) without crashing the application.
2.  **Observability:** Because we are hooked into `autoplug-select`, this fallback is no longer silent. We detect the exact moment the software element is chosen.
3.  **Eventing:** Upon detecting a software fallback in the `autoplug-select` callback, the renderer utilizes the injected `IEventPublisher` to broadcast a `SystemErrorEvent` (or a new `PerformanceWarningEvent`), which can be surfaced to the Vue.js frontend or logged for diagnostics.

## 6. Conclusion
Moving away from `playbin` to an introspective `uridecodebin` architecture, combined with `Gst.Registry` querying, completely eliminates the need for hardcoded mappings or user configuration. It leverages GStreamer's native strengths (Caps negotiation) while solving the observability gap (Issue #663) by making software fallbacks explicit, detectable, and reportable system events.
