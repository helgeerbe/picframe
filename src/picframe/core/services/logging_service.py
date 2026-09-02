"""Runtime logging configuration and live log streaming support."""

from __future__ import annotations

import logging
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from picframe.core.events.dto import State, StateEvent
from picframe.core.events.interfaces import IEventSubscriber
from picframe.core.repositories.interfaces import IConfigRepository
from picframe.core.services.resource_paths import PICFRAME_DATA_TOKEN, ResourcePaths

LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


@dataclass(frozen=True)
class LogEvent:
    """Serializable log event used by the Logs UI."""

    timestamp: float
    level: str
    logger: str
    message: str
    formatted: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "level": self.level,
            "logger": self.logger,
            "message": self.message,
            "formatted": self.formatted,
        }


class LogEventBuffer:
    """Thread-safe bounded log buffer with live subscribers."""

    def __init__(self, capacity: int = 1000) -> None:
        self._events: deque[LogEvent] = deque(maxlen=max(1, capacity))
        self._subscribers: list[Callable[[LogEvent], None]] = []
        self._lock = threading.RLock()

    def append(self, event: LogEvent) -> None:
        with self._lock:
            self._events.append(event)
            subscribers = list(self._subscribers)
        for callback in subscribers:
            try:
                callback(event)
            except Exception:
                # Avoid recursive logging from log streaming subscribers.
                pass

    def snapshot(self) -> list[LogEvent]:
        with self._lock:
            return list(self._events)

    def subscribe(self, callback: Callable[[LogEvent], None]) -> None:
        with self._lock:
            if callback not in self._subscribers:
                self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[LogEvent], None]) -> None:
        with self._lock:
            if callback in self._subscribers:
                self._subscribers.remove(callback)


class LogEventHandler(logging.Handler):
    """Logging handler that forwards records into a LogEventBuffer."""

    def __init__(self, buffer: LogEventBuffer) -> None:
        super().__init__(level=logging.NOTSET)
        self._buffer = buffer

    def emit(self, record: logging.LogRecord) -> None:
        try:
            event = LogEvent(
                timestamp=record.created,
                level=record.levelname,
                logger=record.name,
                message=record.getMessage(),
                formatted=self.format(record),
            )
            self._buffer.append(event)
        except Exception:
            self.handleError(record)


class PicframeLoggingService:
    """Apply logging config at startup and whenever model logging config changes."""

    def __init__(
        self,
        config_repository: IConfigRepository,
        event_subscriber: IEventSubscriber | None,
        resource_paths: ResourcePaths,
        buffer_capacity: int = 1000,
    ) -> None:
        self._config_repository = config_repository
        self._resource_paths = resource_paths
        self._event_subscriber = event_subscriber
        self.buffer = LogEventBuffer(buffer_capacity)
        self._root_logger = logging.getLogger()
        self._file_handler: RotatingFileHandler | None = None
        self._file_path: Path | None = None
        self._buffer_handler = LogEventHandler(self.buffer)
        self._formatter = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
        self._buffer_handler.setFormatter(self._formatter)

        if self._buffer_handler not in self._root_logger.handlers:
            self._root_logger.addHandler(self._buffer_handler)

        self.apply_from_config()
        if self._event_subscriber is not None:
            self._event_subscriber.subscribe(StateEvent, self._handle_state_event)

    def stop(self) -> None:
        if self._event_subscriber is not None:
            self._event_subscriber.unsubscribe(StateEvent, self._handle_state_event)
        if self._buffer_handler in self._root_logger.handlers:
            self._root_logger.removeHandler(self._buffer_handler)
        self._replace_file_handler(None)

    def apply_from_config(self) -> None:
        raw_level = self._config_repository.get_app_config("model.log_level", "WARNING")
        level_name, level = self._normalize_level(raw_level)
        self._root_logger.setLevel(level)
        for handler in self._root_logger.handlers:
            handler.setLevel(logging.NOTSET)

        raw_file = self._config_repository.get_app_config("model.log_file", "")
        file_path = self._resolve_log_file(raw_file)
        self._replace_file_handler(file_path)
        logging.getLogger(__name__).info(
            "Logging configured: level=%s file=%s",
            level_name,
            str(file_path) if file_path else "disabled",
        )

    def _handle_state_event(self, event: StateEvent) -> None:
        if event.state is not State.CONFIG_CHANGED:
            return
        payload = event.payload if isinstance(event.payload, dict) else {}
        updated_sections = payload.get("updated_sections", [])
        if "model" in updated_sections:
            self.apply_from_config()

    @staticmethod
    def _normalize_level(raw_level: Any) -> tuple[str, int]:
        level_name = str(raw_level or "WARNING").strip().upper()
        if level_name not in LOG_LEVELS:
            logging.getLogger(__name__).warning("Unknown log level %r; using WARNING", raw_level)
            level_name = "WARNING"
        return level_name, LOG_LEVELS[level_name]

    def _resolve_log_file(self, raw_file: Any) -> Path | None:
        text = str(raw_file or "").strip()
        if not text:
            return None
        if text == PICFRAME_DATA_TOKEN or text.startswith(f"{PICFRAME_DATA_TOKEN}/"):
            return Path(self._resource_paths.resolve(text)).expanduser().resolve(strict=False)
        path = Path(text).expanduser()
        if not path.is_absolute():
            path = self._resource_paths.data_dir / "logs" / path
        return path.resolve(strict=False)

    def _replace_file_handler(self, file_path: Path | None) -> None:
        if self._file_path == file_path:
            return
        if self._file_handler is not None:
            self._root_logger.removeHandler(self._file_handler)
            self._file_handler.close()
            self._file_handler = None
            self._file_path = None
        if file_path is None:
            return
        file_path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            file_path,
            maxBytes=2_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(self._formatter)
        handler.setLevel(logging.NOTSET)
        self._root_logger.addHandler(handler)
        self._file_handler = handler
        self._file_path = file_path
