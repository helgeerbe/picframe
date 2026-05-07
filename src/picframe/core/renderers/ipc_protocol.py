"""
IPC Protocol definitions for communication between the main process and the GStreamer subprocess.

This module defines the Data Transfer Objects (DTOs) used for sending commands
to the GStreamer worker and receiving events back from it.
"""

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional, Type, TypeVar

T = TypeVar("T", bound="IpcMessage")

@dataclass(frozen=True)
class IpcMessage:
    """Base class for all IPC messages."""

    def to_json(self) -> str:
        """Serialize the message to a JSON string."""
        return json.dumps(asdict(self))

    @classmethod
    def from_dict(cls: Type[T], data: Dict[str, Any]) -> T:
        """Deserialize a dictionary into an IPC message."""
        # Remove 'type' from data as it's handled by the subclass constructor or implicitly
        filtered_data = {k: v for k, v in data.items() if k != "type"}
        return cls(**filtered_data)

# --- Commands (Main -> Subprocess) ---

@dataclass(frozen=True)
class PlayCommand(IpcMessage):
    """Command to start playing a media URI."""
    uri: str
    type: str = field(default="play", init=False)

@dataclass(frozen=True)
class PauseCommand(IpcMessage):
    """Command to pause playback."""
    type: str = field(default="pause", init=False)

@dataclass(frozen=True)
class StopCommand(IpcMessage):
    """Command to stop playback and reset the pipeline."""
    type: str = field(default="stop", init=False)

@dataclass(frozen=True)
class SetVolumeCommand(IpcMessage):
    """Command to set the audio volume."""
    level: float
    type: str = field(default="set_volume", init=False)

@dataclass(frozen=True)
class CheckCapsCommand(IpcMessage):
    """Command to check if the hardware supports the media URI."""
    uri: str
    type: str = field(default="check_caps", init=False)

# --- Events (Subprocess -> Main) ---

@dataclass(frozen=True)
class EosEvent(IpcMessage):
    """Event indicating the End of Stream has been reached."""
    type: str = field(default="eos", init=False)

@dataclass(frozen=True)
class ErrorEvent(IpcMessage):
    """Event indicating a GStreamer error occurred."""
    details: str
    type: str = field(default="error", init=False)

@dataclass(frozen=True)
class WarningEvent(IpcMessage):
    """Event indicating a performance warning (e.g., software fallback)."""
    warning_type: str
    decoder: str
    type: str = field(default="warning", init=False)

@dataclass(frozen=True)
class CapsResultEvent(IpcMessage):
    """Event returning the result of a CheckCapsCommand."""
    supported: bool
    type: str = field(default="caps_result", init=False)

def parse_ipc_message(json_str: str) -> Optional[IpcMessage]:
    """
    Parse a JSON string into the appropriate IpcMessage subclass.
    
    Args:
        json_str: The JSON string to parse.
        
    Returns:
        The parsed IpcMessage object, or None if parsing fails.
    """
    try:
        data = json.loads(json_str)
        msg_type = data.get("type")
        
        if msg_type == "play":
            return PlayCommand.from_dict(data)
        elif msg_type == "pause":
            return PauseCommand.from_dict(data)
        elif msg_type == "stop":
            return StopCommand.from_dict(data)
        elif msg_type == "set_volume":
            return SetVolumeCommand.from_dict(data)
        elif msg_type == "check_caps":
            return CheckCapsCommand.from_dict(data)
        elif msg_type == "eos":
            return EosEvent.from_dict(data)
        elif msg_type == "error":
            return ErrorEvent.from_dict(data)
        elif msg_type == "warning":
            return WarningEvent.from_dict(data)
        elif msg_type == "caps_result":
            return CapsResultEvent.from_dict(data)
        else:
            return None
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
