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
INPUT_ACTION_HIDE = "hide"


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
    :data:`INPUT_ACTION_TOGGLE`, :data:`INPUT_ACTION_HIDE`.
    """

    action: str
    type: str = field(default="input", init=False)


@dataclass(frozen=True)
class OverlayErrorEvent(OverlayIpcMessage):
    """An error reported by the worker (e.g. WebKitGTK init failure)."""

    details: str
    code: str | None = None
    type: str = field(default="error", init=False)


_COMMAND_TYPES: dict[str, type[OverlayIpcMessage]] = {
    "set_opacity": SetOpacityCommand,
    "set_config": SetConfigCommand,
    "reload": ReloadCommand,
    "shutdown": ShutdownCommand,
}

_EVENT_TYPES: dict[str, type[OverlayIpcMessage]] = {
    "ready": ReadyEvent,
    "input": InputEvent,
    "error": OverlayErrorEvent,
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
