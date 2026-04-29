"""
Playback Engine for orchestrating media playback and rendering.
"""
import logging
import time
from typing import Any

from picframe.core.events.dto import (
    Command,
    CommandEvent,
    RenderCommand,
    State,
    StateEvent,
)
from picframe.core.renderers.interfaces import IRenderer
from picframe.core.services.playlist import PlaylistManager


class PlaybackEngine:
    """
    Core state machine for media playback.
    
    Listens to the Event Bus for commands, requests media from the
    PlaylistManager, and sends RenderCommands to the Renderer.
    """

    def __init__(
        self,
        event_bus: Any,  # Should be IEventPublisher & IEventSubscriber
        playlist_manager: PlaylistManager,
        renderer: IRenderer,
        config: dict[str, Any],
    ) -> None:
        """
        Initialize the PlaybackEngine.
        
        Args:
            event_bus: The central event bus for publishing and subscribing.
            playlist_manager: Service for retrieving media items.
            renderer: The presentation layer component for drawing pixels.
            config: Application configuration.
        """
        self._logger = logging.getLogger(__name__)
        self._event_bus = event_bus
        self._playlist_manager = playlist_manager
        self._renderer = renderer
        self._config = config
        
        self._state = State.PAUSED  # IDLE is not in State enum, using PAUSED
        self._is_running = False
        self._time_delay = float(config.get("time_delay", 200.0))
        self._next_transition_time = 0.0
        
        # Subscribe to commands
        self._event_bus.subscribe(CommandEvent, self._handle_command)

    def start(self) -> None:
        """Start the playback engine and render loop."""
        self._logger.info("Starting PlaybackEngine")
        self._is_running = True
        self._renderer.start()
        
        # Initial state transition
        self._change_state(State.PLAYING)
        self._trigger_next_media()
        
        # Main render loop
        self._run_loop()

    def stop(self) -> None:
        """Stop the playback engine and render loop."""
        self._logger.info("Stopping PlaybackEngine")
        self._is_running = False
        # We don't call renderer.stop() here because it might be called
        # from a signal handler which can cause issues with pi3d's
        # display destruction. The renderer will be stopped when the
        # run loop exits.
        self._change_state(State.PAUSED)

    def _run_loop(self) -> None:
        """The main synchronous render loop."""
        while self._is_running:
            # 1. Process any pending events (non-blocking)
            # In a real implementation, we might poll the bus here if it's not
            # automatically dispatching to callbacks in this thread.
            # For now, we assume callbacks are handled.
            
            # 2. Check if it's time for the next slide
            current_time = time.time()
            if (
                self._state == State.PLAYING
                and current_time >= self._next_transition_time
            ):
                self._trigger_next_media()
                
            # 3. Render the frame
            if not self._renderer.render_frame():
                self._logger.info("Renderer requested exit")
                self._is_running = False
                break
                
            # Small sleep to prevent 100% CPU usage if renderer doesn't block
            time.sleep(0.01)
            
        self._logger.info("Exiting render loop, stopping renderer")
        self._renderer.stop()

    def _handle_command(self, event: CommandEvent) -> None:
        """Handle incoming commands from the Event Bus."""
        self._logger.debug(f"Received command: {event.command}")
        
        if event.command == Command.NEXT:
            self._trigger_next_media()
        elif event.command == Command.PREV:
            self._trigger_prev_media()
        elif event.command == Command.PAUSE:
            self._change_state(State.PAUSED)
        elif event.command == Command.PLAY:
            self._change_state(State.PLAYING)
            # Reset timer so it doesn't immediately transition if it was paused
            self._next_transition_time = time.time() + self._time_delay
        elif event.command == Command.STOP:
            self.stop()

    def _trigger_next_media(self) -> None:
        """Fetch the next media item and send a render command."""
        media_item = self._playlist_manager.get_next()
        if media_item:
            self._logger.info(
                f"Transitioning to next media: {media_item.filepath}"
            )
            # TRANSITIONING is not in State enum, skipping state change for now
            
            # Send render command
            render_cmd = RenderCommand(image_path=media_item.filepath)
            self._renderer.execute(render_cmd)
            
            # Update timer
            self._next_transition_time = time.time() + self._time_delay
            
            # We assume transition is fast enough for MVP, go back to playing
            self._change_state(State.PLAYING)
        else:
            self._logger.warning("No media available to play")

    def _trigger_prev_media(self) -> None:
        """Fetch the previous media item and send a render command."""
        media_item = self._playlist_manager.get_previous()
        if media_item:
            self._logger.info(
                f"Transitioning to previous media: {media_item.filepath}"
            )
            # TRANSITIONING is not in State enum, skipping state change for now
            
            # Send render command
            render_cmd = RenderCommand(image_path=media_item.filepath)
            self._renderer.execute(render_cmd)
            
            # Update timer
            self._next_transition_time = time.time() + self._time_delay
            
            # We assume transition is fast enough for MVP, go back to playing
            self._change_state(State.PLAYING)
        else:
            self._logger.warning("No previous media available")

    def _change_state(self, new_state: State) -> None:
        """Update internal state and publish a StateEvent."""
        if self._state != new_state:
            self._logger.debug(f"State changed: {self._state} -> {new_state}")
            self._state = new_state
            self._event_bus.publish(StateEvent(state=new_state))
