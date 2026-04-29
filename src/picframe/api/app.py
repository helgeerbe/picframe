"""
FastAPI Application Setup.

This module initializes the FastAPI application, configures CORS,
and sets up the necessary dependencies for the web control plane.
"""

import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger(__name__)

def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application instance.

    Returns:
        FastAPI: The configured application instance.
    """
    logger.info("Initializing FastAPI application...")
    
    app = FastAPI(
        title="Picframe Web Control Plane",
        description="API for controlling the Picframe digital picture frame.",
        version="2.0.0",
    )

    # Configure CORS
    # In a production environment, these origins should be restricted
    # based on the configuration. For now, we allow all for development.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # TODO: Load from config
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health_check() -> dict[str, str]:
        """Basic health check endpoint."""
        return {"status": "ok"}

    return app
