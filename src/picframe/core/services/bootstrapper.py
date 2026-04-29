"""
Environment Bootstrapper Service.

This module provides the EnvironmentBootstrapper class, which is responsible for
initializing the application's runtime environment. This includes creating the
necessary directory structure (e.g., ~/.picframe), copying default assets (fonts,
shaders, etc.) from the package to the user's data directory, and initializing
empty SQLite databases for configuration and media caching.
"""

import os
import shutil
import sqlite3
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class EnvironmentBootstrapper:
    """
    Bootstraps the picframe environment.

    Handles the creation of the base directory structure, copying of default
    assets required for rendering, and the initialization of the SQLite databases.
    """

    def __init__(self, base_dir: str = "~/.picframe", config_db_path: str | None = None, media_db_path: str | None = None) -> None:
        """
        Initialize the EnvironmentBootstrapper.

        Args:
            base_dir: The base directory for the picframe environment. Defaults to "~/.picframe".
            config_db_path: Optional override for the config database path.
            media_db_path: Optional override for the media database path.
        """
        self.base_dir = Path(os.path.expanduser(base_dir))
        self.data_dir = self.base_dir / "data"
        self.config_db_path = Path(config_db_path) if config_db_path else self.data_dir / "config.db3"
        self.media_db_path = Path(media_db_path) if media_db_path else self.data_dir / "media_cache.db3"

    def bootstrap(self) -> None:
        """
        Execute the full bootstrap process.

        This method sequentially creates directories, copies assets, and initializes databases.
        """
        logger.info(f"Bootstrapping environment at {self.base_dir}")
        self._create_directories()
        self._copy_assets()
        self._initialize_databases()
        logger.info("Bootstrap complete.")

    def _create_directories(self) -> None:
        """
        Create the necessary directory structure.

        Creates the base directory and the data subdirectory if they do not exist.
        """
        self.data_dir.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Created directory: {self.data_dir}")

    def _copy_assets(self) -> None:
        """
        Copy default assets from the package to the user's data directory.

        Copies fonts, mat textures, shaders, and the default 'no_pictures.jpg' image.
        """
        import picframe
        pkg_dir = Path(picframe.__file__).parent
        pkg_data_dir = pkg_dir / "data"

        if not pkg_data_dir.exists():
            logger.warning(f"Package data directory not found at {pkg_data_dir}. Skipping asset copy.")
            return

        for item in pkg_data_dir.iterdir():
            dest_item = self.data_dir / item.name
            if item.is_dir():
                if not dest_item.exists():
                    shutil.copytree(item, dest_item)
                    logger.debug(f"Copied directory {item.name} to {dest_item}")
            else:
                if not dest_item.exists():
                    shutil.copy2(item, dest_item)
                    logger.debug(f"Copied file {item.name} to {dest_item}")

    def _initialize_databases(self) -> None:
        """
        Initialize empty SQLite databases.

        Creates empty 'config.db3' and 'media_cache.db3' files if they do not exist.
        """
        if not self.config_db_path.exists():
            self._create_empty_db(self.config_db_path)
            logger.debug(f"Initialized config database at {self.config_db_path}")
        
        if not self.media_db_path.exists():
            self._create_empty_db(self.media_db_path)
            logger.debug(f"Initialized media database at {self.media_db_path}")

    def _create_empty_db(self, path: Path) -> None:
        """
        Create an empty SQLite database file.

        Args:
            path: The path where the database file should be created.
        """
        conn = sqlite3.connect(path)
        conn.close()
