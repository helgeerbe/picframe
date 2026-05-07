# Architectural Evaluation: Dynamic Hardware Acceleration Discovery in GStreamer

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