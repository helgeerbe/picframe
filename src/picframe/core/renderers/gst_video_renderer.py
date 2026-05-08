"""
GStreamer Video Renderer implementation (IPC Client).
"""
from __future__ import annotations
import logging
import os
import subprocess
import sys
import threading
import time
from multiprocessing.connection import Client, Connection
from pathlib import Path
from typing import Optional

from picframe.core.events.dto import PlaybackCompletedEvent, SystemErrorEvent
from picframe.core.events.interfaces import IEventPublisher
from picframe.core.models.media import MediaItem
from picframe.core.renderers.interfaces import IVideoPlayer
from picframe.core.renderers.ipc_protocol import (
    CapsResultEvent,
    CheckCapsCommand,
    EosEvent,
    ErrorEvent,
    IpcMessage,
    PauseCommand,
    PlayCommand,
    SetVolumeCommand,
    StopCommand,
    WarningEvent,
    parse_ipc_message,
)

logger = logging.getLogger(__name__)

class GstVideoRenderer(IVideoPlayer):
    """
    Video player implementation using an out-of-process GStreamer worker via IPC.
    """

    def __init__(self, event_publisher: IEventPublisher, max_software_decode_resolution: str = "1280x720"):
        self._publisher = event_publisher
        self._max_software_decode_resolution = max_software_decode_resolution
        self._current_media: MediaItem | None = None
        self._volume: float = 1.0
        
        self._socket_path = f"/tmp/picframe_gst_{os.getpid()}.sock"
        self._worker_process: Optional[subprocess.Popen[bytes]] = None
        self._conn: Optional[Connection] = None
        self._running = False
        self._listener_thread: Optional[threading.Thread] = None
        
        self._start_worker()

    def _start_worker(self) -> None:
        """Spawn the GStreamer worker subprocess and establish IPC connection."""
        worker_script = Path(__file__).parent / "gst_worker.py"
        
        env = os.environ.copy()
        # Ensure Wayland variables are passed down
        
        try:
            self._worker_process = subprocess.Popen(
                [sys.executable, str(worker_script), "--socket", self._socket_path],
                env=env,
                stdout=sys.stdout,
                stderr=sys.stderr
            )
            
            # Wait for socket to be created
            retries = 50
            while retries > 0 and not os.path.exists(self._socket_path):
                time.sleep(0.1)
                retries -= 1
                
            if not os.path.exists(self._socket_path):
                raise RuntimeError("Worker failed to create IPC socket.")
                
            self._conn = Client(self._socket_path, family='AF_UNIX')
            self._running = True
            
            self._listener_thread = threading.Thread(target=self._listen_for_events, daemon=True)
            self._listener_thread.start()
            
            logger.info("Successfully connected to GStreamer worker subprocess.")
            
        except Exception as e:
            logger.error(f"Failed to start GStreamer worker: {e}")
            self._cleanup()

    def _listen_for_events(self) -> None:
        """Background thread to listen for events from the worker."""
        while self._running and self._conn:
            try:
                if self._conn.poll(1.0):
                    msg_json = self._conn.recv()
                    msg = parse_ipc_message(msg_json)
                    if msg:
                        self._handle_event(msg)
            except EOFError:
                logger.warning("IPC connection closed by worker.")
                self._running = False
                break
            except Exception as e:
                logger.error(f"Error reading IPC event: {e}")

    def _handle_event(self, event: IpcMessage) -> None:
        """Translate IPC events into domain events."""
        from picframe.core.renderers.ipc_protocol import FirstFrameRenderedEvent
        from picframe.core.events.dto import VideoFirstFrameRenderedEvent
        if isinstance(event, EosEvent):
            logger.info("Received EOS from worker.")
            self._publisher.publish(PlaybackCompletedEvent())
        elif isinstance(event, ErrorEvent):
            logger.error(f"Received Error from worker: {event.details}")
            self._publisher.publish(SystemErrorEvent(message=event.details, component="GstVideoRenderer"))
            self._publisher.publish(PlaybackCompletedEvent())
        elif isinstance(event, WarningEvent):
            logger.warning(f"Worker Warning: {event.warning_type} - {event.decoder}")
            # Could publish a PerformanceWarningEvent here
        elif isinstance(event, FirstFrameRenderedEvent):
            logger.info("Received FirstFrameRenderedEvent from worker.")
            self._publisher.publish(VideoFirstFrameRenderedEvent())

    def _send_command(self, cmd: IpcMessage) -> None:
        """Send a command to the worker."""
        if self._conn:
            try:
                self._conn.send(cmd.to_json())
            except Exception as e:
                logger.error(f"Failed to send IPC command: {e}")

    def play(self, media_item: MediaItem, x: int = 0, y: int = 0, w: int = 0, h: int = 0) -> None:
        """Start playing the specified video media item."""
        if not self._running:
            logger.error("Cannot play video: Worker is not running.")
            self._publisher.publish(PlaybackCompletedEvent())
            return

        self.stop()
        self._current_media = media_item

        uri = Path(media_item.filepath).absolute().as_uri()
        
        # Send play command
        self._send_command(PlayCommand(uri=uri, x=x, y=y, w=w, h=h))
        logger.info(f"Sent play command for: {media_item.filepath} at ({x},{y}) {w}x{h}")

    def stop(self) -> None:
        """Stop video playback."""
        self._send_command(StopCommand())
        self._current_media = None
        logger.debug("Sent stop command.")

    def pause(self) -> None:
        """Pause video playback."""
        self._send_command(PauseCommand())
        logger.debug("Sent pause command.")

    def resume(self) -> None:
        """Resume paused video playback."""
        if self._current_media:
            uri = Path(self._current_media.filepath).absolute().as_uri()
            self._send_command(PlayCommand(uri=uri))
            logger.debug("Sent resume (play) command.")

    def set_volume(self, level: float) -> None:
        """Set the audio volume level (0.0 to 1.0)."""
        self._volume = max(0.0, min(1.0, level))
        self._send_command(SetVolumeCommand(level=self._volume))
        logger.debug(f"Sent set_volume command: {self._volume}")

    def _cleanup(self) -> None:
        """Clean up resources."""
        self._running = False
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
        if self._worker_process:
            self._worker_process.terminate()
            try:
                self._worker_process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                self._worker_process.kill()
        if os.path.exists(self._socket_path):
            try:
                os.remove(self._socket_path)
            except Exception:
                pass

    def __del__(self) -> None:
        self._cleanup()
