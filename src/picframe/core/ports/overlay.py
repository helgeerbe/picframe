"""Port interface for the overlay controller (WebKitGTK touch overlay, #739).

The overlay controller is the abstraction the core/API layers depend on. Its
production implementation (Phase 1) is the out-of-process ``WebKitOverlayRenderer``
IPC client that mirrors the GStreamer worker pattern. This keeps the main
process GTK/WebKit-free and confines any crash/leak to the overlay surface.
"""

from typing import Protocol

from picframe.core.models.overlay import PluginDescriptor


class IOverlayController(Protocol):
    """Interface for the touch overlay controller.

    The controller is the single source of truth for discovered plugins: it
    scans the configured ``plugin_dir`` (via the plugin loader) and exposes
    the resulting ``PluginDescriptor`` list to the API layer.
    """

    def list_plugins(self) -> list[PluginDescriptor]:
        """Return the discovered plugin descriptors (empty list if none)."""
        ...

    def is_available(self) -> bool:
        """Return ``True`` when the overlay backend (WebKitGTK) is usable."""
        ...

    def start(self) -> None:
        """Start the overlay surface / worker process."""
        ...

    def stop(self) -> None:
        """Stop the overlay surface / worker process."""
        ...

    def set_opacity(self, opacity: float) -> None:
        """Set the overlay surface opacity (0.0 = transparent, 1.0 = opaque)."""
        ...

    def reload(self) -> None:
        """Reload the overlay shell/plugins after a config or plugin change."""
        ...
