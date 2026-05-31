import pytest
import threading
import time
from fastapi import FastAPI
from picframe.api.server import WebServer


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()

    @app.get("/test")
    async def test_endpoint() -> dict[str, str]:
        return {"message": "success"}

    return app


class FakeUvicornServer:
    """Minimal stand-in for uvicorn.Server that avoids opening sockets in tests."""

    def __init__(self, config: object) -> None:
        self.config = config
        self.should_exit = False
        self.started = threading.Event()
        self.stopped = threading.Event()

    def run(self) -> None:
        self.started.set()
        while not self.should_exit:
            time.sleep(0.01)
        self.stopped.set()


def test_web_server_start_stop(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("picframe.api.server.uvicorn.Server", FakeUvicornServer)

    port = 9001
    server = WebServer(app, host="127.0.0.1", port=port)
    
    server.start()
    fake_server = server._server
    assert isinstance(fake_server, FakeUvicornServer)
    assert fake_server.started.wait(timeout=1.0)
    assert fake_server.config.host == "127.0.0.1"
    assert fake_server.config.port == port
    
    server.stop()
    assert fake_server.should_exit is True
    assert fake_server.stopped.wait(timeout=1.0)
        
    if server._thread:
        assert not server._thread.is_alive()
