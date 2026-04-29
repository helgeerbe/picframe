import pytest
import threading
import time
import requests
from fastapi import FastAPI
from picframe.api.server import WebServer

@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()
    @app.get("/test")
    def test_endpoint() -> dict[str, str]:
        return {"message": "success"}
    return app

def test_web_server_start_stop(app: FastAPI) -> None:
    # Use a non-standard port to avoid conflicts
    port = 9001
    server = WebServer(app, host="127.0.0.1", port=port)
    
    # Start the server
    server.start()
    
    # Give it a moment to start up
    time.sleep(1.0)
    
    try:
        # Test that it's running and responding
        response = requests.get(f"http://127.0.0.1:{port}/test")
        assert response.status_code == 200
        assert response.json() == {"message": "success"}
    finally:
        # Ensure it gets stopped even if the test fails
        server.stop()
        
    # Verify the thread has stopped
    if server._thread:
        assert not server._thread.is_alive()
