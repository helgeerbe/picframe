"""
Uvicorn Server Management.

This module provides a wrapper around the Uvicorn server to allow
it to be run in a background thread alongside the main pi3d render loop.
"""

import logging
import threading
import uvicorn
from fastapi import FastAPI

logger = logging.getLogger(__name__)

class WebServer:
    """
    Manages the lifecycle of the Uvicorn web server.
    """

    def __init__(self, app: FastAPI, host: str = "0.0.0.0", port: int = 9000) -> None:
        """
        Initialize the WebServer.

        Args:
            app: The FastAPI application instance.
            host: The host interface to bind to.
            port: The port to listen on.
        """
        self._app = app
        self._host = host
        self._port = port
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """
        Start the Uvicorn server in a background thread.
        """
        logger.info(f"Starting web server on {self._host}:{self._port}")
        
        config = uvicorn.Config(
            app=self._app,
            host=self._host,
            port=self._port,
            log_level="info",
            # Disable access log to reduce noise, or configure it properly
            access_log=False,
        )
        self._server = uvicorn.Server(config=config)
        
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """
        Stop the Uvicorn server gracefully.
        """
        if self._server:
            logger.info("Stopping web server...")
            self._server.should_exit = True
            if self._thread:
                self._thread.join(timeout=5.0)
            logger.info("Web server stopped.")
