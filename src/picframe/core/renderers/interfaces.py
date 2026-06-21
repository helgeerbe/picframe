"""
Interfaces for the Presentation Layer (Renderers).
"""
from typing import Protocol

from picframe.core.events.dto import RenderCommand, RendererConfig
from picframe.core.models.media import MediaItem


class IVideoPlayer(Protocol):
    """
    Protocol defining the contract for a Video Player service.
    """

    def play(
        self,
        media_item: MediaItem,
        x: int = 0,
        y: int = 0,
        w: int = 0,
        h: int = 0,
        fit_display: bool = False,
        host_background: list[float] | tuple[float, ...] | None = None,
        host_backdrop_path: str | None = None,
        host_backdrop_rect: tuple[int, int, int, int] | list[int] | None = None,
        content_fit: str | None = None,
    ) -> None:
        """Start playing the specified video media item within the given screen rectangle."""
        ...

    def stop(self) -> None:
        """Stop video playback."""
        ...

    def pause(self) -> None:
        """Pause video playback."""
        ...

    def resume(self) -> None:
        """Resume paused video playback."""
        ...

    def set_pause_overlay(self, visible: bool, text: str = "") -> None:
        """Show or hide a playback-status overlay above the video window."""
        ...

    def set_volume(self, level: float) -> None:
        """
        Set the audio volume level.
        
        Args:
            level: Volume level between 0.0 and 1.0.
        """
        ...

    def set_max_software_decode_resolution(self, value: str) -> None:
        """Update the software decode ceiling used for future video playback."""
        ...


class IRenderer(Protocol):
    """
    Protocol defining the contract for a Presentation Layer renderer.
    
    The renderer is a "dumb" component responsible only for drawing pixels
    to the screen based on received RenderCommands.
    """

    def start(self) -> None:
        """
        Initialize the display and rendering context.
        Must be called from the main thread.
        """
        ...

    def stop(self) -> None:
        """
        Clean up resources and close the display.
        """
        ...

    def execute(self, command: RenderCommand) -> None:
        """
        Process a new render command (e.g., load a new image texture).
        
        Args:
            command: The RenderCommand with image path and overlay data.
        """
        ...

    def get_display_rect(self) -> tuple[int, int, int, int]:
        """
        Get the actual (x, y, width, height) of the rendering display.
        Returns (0, 0, 0, 0) if the display is not yet initialized.
        """
        ...

    def requires_restart_for_config(
        self,
        old_config: RendererConfig | None,
        new_config: RendererConfig,
    ) -> bool:
        """
        Return True when a config change cannot be applied safely in this process.

        Callers should treat True as requiring an external Picframe restart, not
        as permission to force an in-process display remap.
        """
        ...

    def render_frame(self) -> bool:
        """
        Draw a single frame to the display.
        Must be called continuously in the main thread loop.
        
        Returns:
            bool: True to continue the render loop, False to exit.
        """
        ...
