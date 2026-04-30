"""
FastAPI Application Setup.

This module initializes the FastAPI application, configures CORS,
and sets up the necessary dependencies for the web control plane.
"""

import logging
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

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

    # Serve SPA static files
    html_dir = Path(__file__).parent.parent / "html"
    if html_dir.exists():
        # Mount the assets directory
        assets_dir = html_dir / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        # Catch-all route for SPA
        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str) -> FileResponse:
            requested_file = html_dir / full_path
            if full_path and requested_file.is_file():
                return FileResponse(requested_file)
            return FileResponse(html_dir / "index.html")
    else:
        logger.warning(f"Frontend build directory not found at {html_dir}. Web UI will not be available.")

    return app
