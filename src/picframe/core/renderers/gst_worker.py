"""
GStreamer Subprocess Worker.

This script runs in an isolated subprocess to handle GStreamer video playback.
It communicates with the main application process via an IPC socket using JSON messages.
"""

import argparse
import logging
import os
import sys
from multiprocessing.connection import Connection, Listener
from typing import Any

from picframe.core.renderers.ipc_protocol import (
    CapsResultEvent,
    CheckCapsCommand,
    EosEvent,
    ErrorEvent,
    FirstFrameRenderedEvent,
    IpcMessage,
    PauseCommand,
    PlayCommand,
    SetVolumeCommand,
    StopCommand,
    WarningEvent,
    parse_ipc_message,
)

# Configure logging for the worker
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("gst_worker")

try:
    import gi
    gi.require_version('Gst', '1.0')
    gi.require_version('GstPbutils', '1.0')
    from gi.repository import GLib, Gst, GstPbutils
    Gst.init(None)
    GST_AVAILABLE = True
except ImportError:
    Gst = Any
    GLib = Any
    GstPbutils = Any
    logger.error("GStreamer not available. Worker cannot start.")
    GST_AVAILABLE = False

from picframe.core.renderers.gst_utils import find_best_element  # noqa: E402


class GstWorker:
    def __init__(self, socket_path: str):
        self.socket_path = socket_path
        self.conn: Connection | None = None
        self.listener: Listener | None = None
        self.pipeline: Any = None
        self.bus: Any = None
        self.volume: float = 1.0
        self.running = True
        self.loop: Any = GLib.MainLoop() if GST_AVAILABLE else None
        self._current_play_request: tuple[str, int, int, int, int] | None = None
        self._software_decode_retry_attempted = False

    def start(self) -> None:
        """Start the worker and listen for IPC connections."""
        if not GST_AVAILABLE:
            sys.exit(1)

        # Ensure socket path directory exists
        os.makedirs(os.path.dirname(self.socket_path), exist_ok=True)
        
        # Remove existing socket if it exists
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)

        logger.info(f"Starting IPC listener on {self.socket_path}")
        self.listener = Listener(self.socket_path, family='AF_UNIX')
        
        # Accept the initial connection
        self._accept_connection()

        # Run the GLib main loop (required for GStreamer bus signals)
        try:
            if self.loop:
                self.loop.run()
        except KeyboardInterrupt:
            pass
        finally:
            self.cleanup()

    def _accept_connection(self) -> None:
        """Accept a connection and set up the IO watch."""
        if self.listener:
            try:
                self.conn = self.listener.accept()
                logger.info("Main process connected.")
                # Add the connection's file descriptor to the GLib main loop
                if self.conn and hasattr(self.conn, 'fileno'):
                    GLib.io_add_watch(
                        self.conn.fileno(),
                        GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR,
                        self._on_ipc_data,
                    )
            except Exception as e:
                logger.error(f"Failed to accept connection: {e}")

    def _on_ipc_data(self, fd: int, condition: Any) -> bool:
        """Callback for GLib IO watch when data is available on the IPC socket."""
        if condition & (GLib.IO_HUP | GLib.IO_ERR):
            logger.info("IPC connection closed or errored.")
            self._handle_disconnect()
            return False # Remove the watch

        if condition & GLib.IO_IN:
            try:
                if self.conn:
                    msg_json = self.conn.recv()
                    msg = parse_ipc_message(msg_json)
                    if msg:
                        self._dispatch_command(msg)
                    else:
                        logger.warning(f"Failed to parse IPC message: {msg_json}")
            except EOFError:
                logger.info("IPC connection closed by main process (EOF).")
                self._handle_disconnect()
                return False # Remove the watch
            except Exception as e:
                logger.error(f"Error reading IPC message: {e}")
                self._handle_disconnect()
                return False # Remove the watch

        return True # Keep the watch active

    def _handle_disconnect(self) -> None:
        """Handle disconnection from the main process."""
        self._handle_stop()
        if self.conn:
            self.conn.close()
            self.conn = None
        
        # In a robust system, we might want to wait for a new connection here.
        # For now, we exit the worker so the main process can respawn it cleanly.
        logger.info("Exiting worker due to disconnect.")
        self.running = False
        if self.loop:
            self.loop.quit()

    def _send_event(self, event: IpcMessage) -> None:
        """Send an event back to the main process."""
        if self.conn and not self.conn.closed:
            try:
                self.conn.send(event.to_json())
            except Exception as e:
                logger.error(f"Failed to send IPC event: {e}")

    def _dispatch_command(self, cmd: IpcMessage) -> None:
        """Dispatch an incoming command to the appropriate handler."""
        if isinstance(cmd, PlayCommand):
            self._handle_play(cmd.uri, cmd.x, cmd.y, cmd.w, cmd.h)
        elif isinstance(cmd, PauseCommand):
            self._handle_pause()
        elif isinstance(cmd, StopCommand):
            self._handle_stop()
        elif isinstance(cmd, SetVolumeCommand):
            self._handle_set_volume(cmd.level)
        elif isinstance(cmd, CheckCapsCommand):
            self._handle_check_caps(cmd.uri)

    def _handle_play(self, uri: str, x: int, y: int, w: int, h: int) -> None:
        try:
            playable, reason = self._discover_playable_video(uri)
            if not playable:
                details = reason or "No playable video stream found."
                logger.error(f"Skipping {uri}: {details}")
                self._send_event(ErrorEvent(details=details))
                return

            self._current_play_request = (uri, x, y, w, h)
            self._software_decode_retry_attempted = False
            self._start_pipeline(uri, x, y, w, h, force_software_decoders=False)
        except Exception as e:
            logger.error(f"Exception during playback setup: {e}")
            self._send_event(ErrorEvent(details=str(e)))
            self._handle_stop()

    def _start_pipeline(
        self,
        uri: str,
        x: int,
        y: int,
        w: int,
        h: int,
        *,
        force_software_decoders: bool,
    ) -> None:
        self._handle_stop()

        try:
            pipeline_description = self._build_pipeline_description(
                uri,
                x,
                y,
                w,
                h,
                force_software_decoders=force_software_decoders,
            )
            self.pipeline = Gst.parse_launch(pipeline_description)
            uridecodebin = self.pipeline.get_by_name("decoder")
            if force_software_decoders:
                logger.info("Retrying %s with software decoders forced.", uri)
            uridecodebin.connect("autoplug-select", self._on_autoplug_select)
            
            try:
                self.pipeline.set_property("volume", self.volume)
            except TypeError:
                pass
                
            self.bus = self.pipeline.get_bus()
            self.bus.add_signal_watch()
            self.bus.connect("message::eos", self._on_eos)
            self.bus.connect("message::error", self._on_error)
            self.bus.connect("message::async-done", self._on_async_done)
            
            ret = self.pipeline.set_state(Gst.State.PLAYING)
            if ret == Gst.StateChangeReturn.FAILURE:
                logger.error(f"Failed to set pipeline state to PLAYING for {uri}")
                self._send_event(ErrorEvent(details="Pipeline failed to start playing."))
                self._handle_stop()
            else:
                logger.info(f"Playing {uri}")
        except Exception as e:
            logger.error(f"Exception during playback setup: {e}")
            self._send_event(ErrorEvent(details=str(e)))
            self._handle_stop()

    def _build_pipeline_description(
        self,
        uri: str,
        x: int,
        y: int,
        w: int,
        h: int,
        *,
        force_software_decoders: bool,
    ) -> str:
        force_sw = " force-sw-decoders=true" if force_software_decoders else ""
        sink_name = find_best_element(["waylandsink", "glimagesink", "ximagesink", "autovideosink"])
        if not sink_name:
            sink_name = "autovideosink"

        has_render_rectangle = w > 0 and h > 0
        sink_props = []
        if has_render_rectangle:
            sink_props.append(f'render-rectangle="<{x}, {y}, {w}, {h}>"')
        else:
            sink_props.append("fullscreen=true")
        if sink_name == "waylandsink":
            sink_props.append("rotate-method=8")
        sink_props_str = " ".join(sink_props)

        return (
            f'uridecodebin name=decoder uri="{uri}"{force_sw} '
            "decoder. ! "
            "videoconvert ! "
            "videoscale add-borders=false ! "
            "videoconvert ! "
            "video/x-raw,format=RGBA ! "
            "alpha alpha=0.99 ! "
            f"{sink_name} name=sink {sink_props_str}"
        )

    def _discover_playable_video(self, uri: str) -> tuple[bool, str | None]:
        """Return whether GStreamer can discover at least one playable video stream."""
        try:
            discoverer = GstPbutils.Discoverer.new(5 * Gst.SECOND)
            info = discoverer.discover_uri(uri)
            if not info.get_video_streams():
                return False, "No playable video stream found."
            return True, None
        except Exception as e:
            return False, f"Could not discover playable video stream: {e}"

    def _create_sink_bin(self, x: int, y: int, w: int, h: int) -> Any:
        bin = Gst.Bin.new("sink_bin")
        elements, sink_pad_element = self._build_sink_elements(x, y, w, h)

        for elem in elements:
            bin.add(elem)

        self._link_elements(elements)

        pad = sink_pad_element.get_static_pad("sink")
        ghost_pad = Gst.GhostPad.new("sink", pad)
        bin.add_pad(ghost_pad)

        return bin

    def _build_sink_elements(self, x: int, y: int, w: int, h: int) -> tuple[list[Any], Any]:
        hw_converter = find_best_element(["v4l2convert"])
        
        elements = []
        queue = Gst.ElementFactory.make("queue", "video_queue")
        elements.append(queue)
        if hw_converter:
            conv = Gst.ElementFactory.make(hw_converter, "conv")
            elements.append(conv)
        else:
            conv1 = Gst.ElementFactory.make("videoconvert", "conv1")
            scale = Gst.ElementFactory.make("videoscale", "scale")
            scale.set_property("add-borders", False)
            conv2 = Gst.ElementFactory.make("videoconvert", "conv2")
            elements.extend([conv1, scale, conv2])
        sink_pad_element = queue
            
        capsfilter = Gst.ElementFactory.make("capsfilter", "capsfilter")
        caps = Gst.Caps.from_string("video/x-raw,format=RGBA")
        capsfilter.set_property("caps", caps)
        elements.append(capsfilter)
        
        alpha = Gst.ElementFactory.make("alpha", "alpha")
        alpha.set_property("alpha", 0.99)
        elements.append(alpha)
            
        sink_name = find_best_element(["waylandsink", "glimagesink", "ximagesink", "autovideosink"])
        if not sink_name:
            sink_name = "autovideosink"
            
        sink = Gst.ElementFactory.make(sink_name, "sink")
        has_render_rectangle = w > 0 and h > 0

        if not has_render_rectangle:
            try:
                if hasattr(sink.props, 'fullscreen'):
                    sink.set_property("fullscreen", True)
            except Exception:
                pass

        if has_render_rectangle:
            try:
                Gst.util_set_object_arg(sink, "render-rectangle", f"<{x}, {y}, {w}, {h}>")
            except Exception as e:
                logger.warning(f"Sink {sink_name} does not support render-rectangle property: {e}")

        if sink_name == "waylandsink":
            sink.set_property("rotate-method", 8)
            
        elements.append(sink)
        return elements, sink_pad_element

    def _link_elements(self, elements: list[Any]) -> None:
        for i in range(len(elements) - 1):
            elements[i].link(elements[i + 1])

    def _on_pad_added(self, element: Any, pad: Any, sink_pad_element: Any) -> None:
        caps = pad.get_current_caps()
        if not caps:
            caps = pad.query_caps()
            
        if caps:
            struct = caps.get_structure(0)
            name = struct.get_name()
            logger.debug("Decoded pad added with caps: %s", caps.to_string())
            if name.startswith("video/"):
                sink_pad = sink_pad_element.get_static_pad("sink")
                if not sink_pad.is_linked():
                    result = pad.link(sink_pad)
                    if result != Gst.PadLinkReturn.OK:
                        logger.error(
                            "Failed to link decoded video pad to sink bin: %s",
                            result.value_nick if hasattr(result, "value_nick") else result,
                        )
                    else:
                        logger.debug("Linked decoded video pad to sink chain.")

    def _on_autoplug_select(self, bin: Any, pad: Any, caps: Any, factory: Any) -> int:
        klass = factory.get_metadata(Gst.ELEMENT_METADATA_KLASS)
        if klass and "Decoder" in klass and "Video" in klass and "Hardware" not in klass:
            self._send_event(
                WarningEvent(warning_type="software_fallback", decoder=factory.get_name())
            )
        return 0

    def _handle_pause(self) -> None:
        if self.pipeline:
            self.pipeline.set_state(Gst.State.PAUSED)

    def _handle_stop(self) -> None:
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
            if self.bus:
                self.bus.remove_signal_watch()
            self.pipeline = None
            self.bus = None

    def _handle_set_volume(self, level: float) -> None:
        self.volume = max(0.0, min(1.0, level))
        if self.pipeline:
            try:
                self.pipeline.set_property("volume", self.volume)
            except TypeError:
                pass

    def _handle_check_caps(self, uri: str) -> None:
        if not GST_AVAILABLE:
            self._send_event(CapsResultEvent(supported=False))
            return

        try:
            # Initialize Discoverer with a 5-second timeout
            discoverer = GstPbutils.Discoverer.new(5 * Gst.SECOND)
            info = discoverer.discover_uri(uri)
            
            # Get video streams
            video_streams = info.get_video_streams()
            if not video_streams:
                # No video stream found, might be audio only or unsupported
                self._send_event(CapsResultEvent(supported=False))
                return
                
            # Check if we have a valid video stream with caps
            for stream in video_streams:
                caps = stream.get_caps()
                if caps:
                    # Intersect caps with registry's available decoders
                    registry = Gst.Registry.get()
                    factories = registry.get_feature_list(Gst.ElementFactory)
                    stream_supported = False
                    
                    for factory in factories:
                        klass = factory.get_metadata(Gst.ELEMENT_METADATA_KLASS)
                        if klass and "Decoder" in klass and "Video" in klass:
                            for template in factory.get_static_pad_templates():
                                if template.direction == Gst.PadDirection.SINK:
                                    template_caps = template.get_caps()
                                    if template_caps and template_caps.can_intersect(caps):
                                        intersected = template_caps.intersect(caps)
                                        if not intersected.is_empty():
                                            stream_supported = True
                                            break
                        if stream_supported:
                            break
                            
                    if stream_supported:
                        self._send_event(CapsResultEvent(supported=True))
                        return
                        
            self._send_event(CapsResultEvent(supported=False))
            
        except Exception as e:
            logger.error(f"Caps discovery failed for {uri}: {e}")
            self._send_event(CapsResultEvent(supported=False))

    def _on_eos(self, bus: Any, msg: Any) -> None:
        self._send_event(EosEvent())
        # Do NOT call _handle_stop() here. We want the last frame to remain visible
        # until the main process explicitly sends a StopCommand after the pi3d transition.

    def _on_error(self, bus: Any, msg: Any) -> None:
        err, debug = msg.parse_error()
        debug_text = str(debug or "")
        logger.error("GStreamer error: %s", err.message)
        if debug_text:
            logger.error("GStreamer debug info: %s", debug_text)
        if self._should_retry_with_software_decode(err.message, debug_text):
            self._retry_with_software_decode(err.message, debug_text)
            return
        self._send_event(ErrorEvent(details=err.message))
        self._handle_stop()

    def _should_retry_with_software_decode(self, message: str, debug: str) -> bool:
        if self._software_decode_retry_attempted or self._current_play_request is None:
            return False
        combined = f"{message}\n{debug}".lower()
        return (
            "not-negotiated" in combined
            or "reason not-negotiated" in combined
            or "internal data stream error" in combined
        )

    def _retry_with_software_decode(self, message: str, debug: str) -> None:
        request = self._current_play_request
        if request is None:
            self._send_event(ErrorEvent(details=message))
            self._handle_stop()
            return

        self._software_decode_retry_attempted = True
        logger.warning(
            "Hardware/autoplug video path failed; retrying with software decoders. "
            "Message=%s Debug=%s",
            message,
            debug,
        )
        self._send_event(
            WarningEvent(
                warning_type="software_fallback",
                decoder="force-sw-decoders",
            )
        )
        uri, x, y, w, h = request
        self._start_pipeline(uri, x, y, w, h, force_software_decoders=True)

    def _on_async_done(self, bus: Any, msg: Any) -> None:
        self._send_event(FirstFrameRenderedEvent())
        # Ensure pipeline is playing after async-done
        if self.pipeline:
            self.pipeline.set_state(Gst.State.PLAYING)

    def cleanup(self) -> None:
        self._handle_stop()
        if self.conn:
            self.conn.close()
        if self.listener:
            self.listener.close()
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GStreamer IPC Worker")
    parser.add_argument(
        "--socket",
        required=False,
        default="/tmp/picframe_gst_worker.sock",
        help="Path to the Unix domain socket",
    )
    args = parser.parse_args()
    
    worker = GstWorker(args.socket)
    worker.start()
