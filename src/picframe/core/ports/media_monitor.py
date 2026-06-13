"""
Port interface for media filesystem monitoring.
"""

from typing import Protocol


class IMediaMonitor(Protocol):
    """
    Interface for monitoring media directories and reconciling filesystem state.
    """

    def start(self) -> None:
        """Start monitoring configured media directories."""
        ...

    def stop(self) -> None:
        """Stop monitoring configured media directories."""
        ...

    def pause(self) -> None:
        """Pause monitoring without changing configured directories."""
        ...

    def resume(self) -> None:
        """Resume monitoring after reconciling missed changes."""
        ...

    def perform_differential_sync(self) -> None:
        """Publish file-change events for currently available media files."""
        ...

    def set_directories(self, directories: list[str]) -> None:
        """Replace the monitored media directories."""
        ...

    def configure(
        self,
        directories: list[str],
        allowed_extensions: set[str],
        follow_links: bool,
    ) -> None:
        """Replace monitor settings, restarting observers when needed."""
        ...
