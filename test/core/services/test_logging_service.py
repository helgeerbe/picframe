import logging
from pathlib import Path
from typing import Any

from picframe.core.events.dto import State, StateEvent
from picframe.core.services.logging_service import PicframeLoggingService
from picframe.core.services.resource_paths import ResourcePaths


class FakeConfigRepository:
    def __init__(self, values: dict[str, Any]) -> None:
        self.values = values

    def get_app_config(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)


class FakeSubscriber:
    def __init__(self) -> None:
        self.callbacks: list[Any] = []

    def subscribe(self, _event_type: type, callback: Any) -> None:
        self.callbacks.append(callback)

    def unsubscribe(self, _event_type: type, callback: Any) -> None:
        self.callbacks.remove(callback)


def test_logging_service_applies_level_file_and_live_updates(tmp_path: Path) -> None:
    root_logger = logging.getLogger()
    previous_level = root_logger.level
    resource_paths = ResourcePaths.from_base_dir(tmp_path / "picframe")
    repo = FakeConfigRepository(
        {
            "model.log_level": "DEBUG",
            "model.log_file": "picframe.log",
        }
    )
    subscriber = FakeSubscriber()
    service = PicframeLoggingService(repo, subscriber, resource_paths)

    try:
        assert root_logger.level == logging.DEBUG
        logging.getLogger("picframe.test").debug("buffered debug message")
        snapshot = service.buffer.snapshot()
        assert any(event.message == "buffered debug message" for event in snapshot)

        log_path = resource_paths.data_dir / "logs" / "picframe.log"
        assert log_path.exists()

        repo.values["model.log_level"] = "ERROR"
        repo.values["model.log_file"] = ""
        subscriber.callbacks[0](
            StateEvent(
                state=State.CONFIG_CHANGED,
                payload={"updated_sections": ["model"]},
            )
        )

        assert root_logger.level == logging.ERROR
        assert not any(
            getattr(handler, "baseFilename", None) == str(log_path)
            for handler in root_logger.handlers
        )
    finally:
        service.stop()
        root_logger.setLevel(previous_level)


def test_logging_service_normalizes_unknown_level(tmp_path: Path) -> None:
    root_logger = logging.getLogger()
    previous_level = root_logger.level
    resource_paths = ResourcePaths.from_base_dir(tmp_path / "picframe")
    repo = FakeConfigRepository({"model.log_level": "NOPE", "model.log_file": ""})
    service = PicframeLoggingService(repo, None, resource_paths)

    try:
        assert root_logger.level == logging.WARNING
    finally:
        service.stop()
        root_logger.setLevel(previous_level)
