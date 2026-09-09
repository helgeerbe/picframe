"""IPC protocol for the out-of-process WebKitGTK overlay worker (#739).

Mirrors :mod:`picframe.core.renderers.ipc_protocol` (the GStreamer worker
protocol) so the overlay worker follows the same isolation pattern: the main
process contains no GTK/WebKit; :class:`WebKitOverlayRenderer` is a thin IPC
client that talks to ``overlay_worker.py`` over a Unix-domain socket using
newline-delimited JSON messages.

All messages are frozen dataclasses with a ``type`` discriminator field so the
same ``parse_overlay_ipc_message`` factory can rebuild the right subclass.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, TypeVar

T = TypeVar("T", bound="OverlayIpcMessage")

# Input actions emitted by the worker when a pointer/keyboard event is handled
# inside the overlay shell. They are translated by the renderer into
# ``CommandEvent``s on the main event bus.
INPUT_ACTION_PREV = "prev"
INPUT_ACTION_NEXT = "next"
INPUT_ACTION_TOGGLE = "toggle"
# Danger-menu actions (#763): display power, service restart, host
# reboot/shutdown, and exit picframe (#740). These are confirmed in the
# overlay shell before being emitted to the worker. `stop` exits the
# picframe process via ``Command.STOP`` (graceful shutdown of the engine).
INPUT_ACTION_DISPLAY_OFF = "display_off"
INPUT_ACTION_RESTART_SERVICE = "restart_service"
INPUT_ACTION_REBOOT_HOST = "reboot_host"
INPUT_ACTION_SHUTDOWN_HOST = "shutdown_host"
INPUT_ACTION_STOP = "stop"


@dataclass(frozen=True)
class OverlayIpcMessage:
    """Base class for all overlay IPC messages."""

    def to_json(self) -> str:
        """Serialize the message to a JSON string."""
        return json.dumps(asdict(self))

    @classmethod
    def from_dict(cls: type[T], data: dict[str, Any]) -> T:
        """Deserialize a dictionary into an overlay IPC message.

        The ``type`` discriminator is stripped before construction because the
        subclass declares it as a non-init default field.
        """
        filtered_data = {k: v for k, v in data.items() if k != "type"}
        return cls(**filtered_data)


# --- Commands (Main -> Worker) ---


@dataclass(frozen=True)
class SetOpacityCommand(OverlayIpcMessage):
    """Set the overlay surface opacity (0.0 = transparent, 1.0 = opaque)."""

    opacity: float
    type: str = field(default="set_opacity", init=False)


@dataclass(frozen=True)
class SetConfigCommand(OverlayIpcMessage):
    """Apply a merged ``overlay`` config section live (no restart)."""

    config: dict[str, Any]
    type: str = field(default="set_config", init=False)


@dataclass(frozen=True)
class ReloadCommand(OverlayIpcMessage):
    """Reload the overlay shell / re-scan plugins after a change."""

    type: str = field(default="reload", init=False)


@dataclass(frozen=True)
class MediaChangedCommand(OverlayIpcMessage):
    """Push the current media item to the overlay shell.

    The controller (in-process with the event bus) forwards
    ``CurrentMediaChangedEvent`` payloads to the worker via this command so the
    shell's ``media_change`` plugins wake after the image blend — without
    relying on the cross-origin ``/ws/state`` WebSocket from the ``file://``
    overlay surface (#757). The worker injects the ``media`` dict into the
    shell via the same ``evaluate_javascript`` bridge used for config.
    """

    media: dict[str, Any]
    type: str = field(default="media_changed", init=False)


@dataclass(frozen=True)
class ShutdownCommand(OverlayIpcMessage):
    """Ask the worker to shut down cleanly."""

    type: str = field(default="shutdown", init=False)


# --- Events (Worker -> Main) ---


@dataclass(frozen=True)
class ReadyEvent(OverlayIpcMessage):
    """The worker has finished initializing the WebKitGTK surface."""

    type: str = field(default="ready", init=False)


@dataclass(frozen=True)
class InputEvent(OverlayIpcMessage):
    """An input event captured by the overlay shell (pointer or keyboard).

    ``action`` is one of :data:`INPUT_ACTION_PREV`, :data:`INPUT_ACTION_NEXT`,
    :data:`INPUT_ACTION_TOGGLE`, or a danger-menu
    action (:data:`INPUT_ACTION_DISPLAY_OFF`, :data:`INPUT_ACTION_RESTART_SERVICE`,
    :data:`INPUT_ACTION_REBOOT_HOST`, :data:`INPUT_ACTION_SHUTDOWN_HOST`).
    """

    action: str
    type: str = field(default="input", init=False)


@dataclass(frozen=True)
class OverlayErrorEvent(OverlayIpcMessage):
    """An error reported by the worker (e.g. WebKitGTK init failure)."""

    details: str
    code: str | None = None
    type: str = field(default="error", init=False)


@dataclass(frozen=True)
class VisiblePluginsChangedEvent(OverlayIpcMessage):
    """The user changed the expanded plugin set from the overlay dock (#765).

    Carries the next list of visible plugin ids (the dock's
    ``visiblePlugins``) from the worker to the main process. The renderer
    republishes it as a ``CommandEvent(SET_CONFIG, {overlay:
    {visible_plugins}})`` — the exact command the Remote/Appearance REST
    endpoint (``PUT /api/workflow-config``) publishes — so both UIs write the
    same persisted key and refresh through the same
    ``OverlayConfigChangedEvent`` round-trip. A single source of truth
    (``overlay.visible_plugins`` in ``config.db3``) keeps the dock and the
    web UI in sync across ``media_change`` and restarts.
    """

    visible_plugins: tuple[str, ...]
    type: str = field(default="visible_plugins_changed", init=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VisiblePluginsChangedEvent:
        """Coerce the JSON list back into the declared tuple type.

        JSON has no tuple literal, so ``json.loads`` always produces a list;
        without this the round-tripped message would hold a list and fail
        equality against the original (tuple-typed) event.
        """
        filtered = {k: v for k, v in data.items() if k != "type"}
        plugins = filtered.get("visible_plugins")
        if isinstance(plugins, (list, tuple)):
            filtered["visible_plugins"] = tuple(str(p) for p in plugins)
        else:
            filtered["visible_plugins"] = ()
        return cls(**filtered)


@dataclass(frozen=True)
class OnScreenPluginsChangedEvent(OverlayIpcMessage):
    """The on-screen (runtime) visibility of expanded plugins changed (#766).

    Distinct from :class:`VisiblePluginsChangedEvent` (the persisted
    ``visible_plugins`` config set, driven by dock toggles). This carries the
    **transient** set of plugins currently shown on screen — i.e. expanded
    plugins whose panel is *not* auto-hidden (no ``pf-plugin-panel--idle``).
    Auto-hide is purely a client-side fade (CSS opacity) that never writes
    ``config.db3``; without this event the Remote tab only sees the persisted
    ``visible_plugins`` and its tile highlights stay lit while the dock icon
    correctly de-activates. The shell emits it whenever the on-screen set
    actually changes (auto-hide timeout, wake, media_change re-arm, toggle,
    config apply) so the renderer republishes a runtime-visibility domain
    event the browser mirrors.
    """

    on_screen_plugins: tuple[str, ...]
    type: str = field(default="on_screen_plugins_changed", init=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OnScreenPluginsChangedEvent:
        """Coerce the JSON list back into the declared tuple type.

        JSON has no tuple literal, so ``json.loads`` always produces a list;
        without this the round-tripped message would hold a list and fail
        equality against the original (tuple-typed) event.
        """
        filtered = {k: v for k, v in data.items() if k != "type"}
        plugins = filtered.get("on_screen_plugins")
        if isinstance(plugins, (list, tuple)):
            filtered["on_screen_plugins"] = tuple(str(p) for p in plugins)
        else:
            filtered["on_screen_plugins"] = ()
        return cls(**filtered)


_COMMAND_TYPES: dict[str, type[OverlayIpcMessage]] = {
    "set_opacity": SetOpacityCommand,
    "set_config": SetConfigCommand,
    "reload": ReloadCommand,
    "media_changed": MediaChangedCommand,
    "shutdown": ShutdownCommand,
}

_EVENT_TYPES: dict[str, type[OverlayIpcMessage]] = {
    "ready": ReadyEvent,
    "input": InputEvent,
    "error": OverlayErrorEvent,
    "visible_plugins_changed": VisiblePluginsChangedEvent,
    "on_screen_plugins_changed": OnScreenPluginsChangedEvent,
}


def parse_overlay_ipc_message(json_str: str) -> OverlayIpcMessage | None:
    """Parse a JSON string into the appropriate overlay IPC message subclass.

    Returns ``None`` if the string is not valid JSON or the ``type`` is
    unknown, so a malformed line from the worker never crashes the listener.
    """
    try:
        data = json.loads(json_str)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    msg_type = data.get("type")
    cls = _COMMAND_TYPES.get(str(msg_type)) or _EVENT_TYPES.get(str(msg_type))
    if cls is None:
        return None
    try:
        return cls.from_dict(data)
    except (TypeError, ValueError):
        return None
