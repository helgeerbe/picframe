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
import yaml
from pathlib import Path
from typing import Any

from picframe.api.models import AppConfig
from picframe.core.repositories.sqlite_config import SQLiteConfigRepository
from picframe.core.repositories.sqlite_media import SQLiteMediaRepository
from picframe.core.services.resource_paths import repair_legacy_resource_defaults

logger = logging.getLogger(__name__)

class EnvironmentBootstrapper:
    """
    Bootstraps the picframe environment.

    Handles the creation of the base directory structure, copying of default
    assets required for rendering, and the initialization of the SQLite databases.
    """

    def __init__(self, base_dir: str = "~/.picframe", config_db_path: str | None = None, media_db_path: str | None = None, force: bool = False) -> None:
        """
        Initialize the EnvironmentBootstrapper.

        Args:
            base_dir: The base directory for the picframe environment. Defaults to "~/.picframe".
            config_db_path: Optional override for the config database path.
            media_db_path: Optional override for the media database path.
            force: If True, bypass interactive prompts and overwrite existing databases.
        """
        self.base_dir = Path(os.path.expanduser(base_dir))
        self.data_dir = self.base_dir / "data"
        self.config_db_path = Path(config_db_path) if config_db_path else self.data_dir / "config.db3"
        self.media_db_path = Path(media_db_path) if media_db_path else self.data_dir / "media_cache.db3"
        self.force = force

    def _prompt_deletion(self, filepath: Path, db_name: str) -> bool:
        if not filepath.exists():
            return True # Safe to proceed
            
        if self.force:
            logger.info(f"--force flag provided. Deleting existing {db_name} database.")
            filepath.unlink()
            return True

        response = input(f"\n[?] The {db_name} database already exists at {filepath}.\nDo you want to delete it and start fresh? [y/N]: ").strip().lower()
        if response in ['y', 'yes']:
            filepath.unlink()
            logger.info(f"Deleted existing {db_name} database.")
            return True
        else:
            logger.info(f"Keeping existing {db_name} database. Migrations will be applied if necessary.")
            return False

    def bootstrap(self) -> None:
        """
        Execute the full bootstrap process.

        This method sequentially creates directories, copies assets, and initializes databases.
        """
        logger.info(f"Bootstrapping environment at {self.base_dir}")
        self._create_directories()
        self._copy_assets()
        
        # 1. Handle existing databases
        config_cleared = self._prompt_deletion(self.config_db_path, "Configuration")
        media_cleared = self._prompt_deletion(self.media_db_path, "Media Cache")

        # 2. Initialize Repositories (This triggers migrations automatically)
        config_repo = SQLiteConfigRepository(str(self.config_db_path))
        media_repo = SQLiteMediaRepository(str(self.media_db_path))

        # 3. Seed Configuration (Only if config was cleared or is empty)
        if config_cleared or not config_repo.get_all_app_config():
            self._seed_default_config(config_repo)
        repair_legacy_resource_defaults(config_repo)
            
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
        
        # Ensure no_pictures.jpg is copied to the root of the data directory
        no_pictures_src = pkg_data_dir / "no_pictures.jpg"
        no_pictures_dest = self.data_dir / "no_pictures.jpg"
        if no_pictures_src.exists() and not no_pictures_dest.exists():
            shutil.copy2(no_pictures_src, no_pictures_dest)
            logger.debug(f"Copied fallback image to {no_pictures_dest}")
        
        # Copy HTML assets (force overwrite if exists to ensure updates)
        pkg_html_dir = pkg_dir / "html"
        dest_html_dir = self.base_dir / "html"
        if pkg_html_dir.exists():
            if dest_html_dir.exists():
                shutil.rmtree(dest_html_dir)
            shutil.copytree(pkg_html_dir, dest_html_dir)
            logger.debug(f"Copied HTML directory to {dest_html_dir}")

    def _flatten_dict(self, d: dict[str, Any], parent_key: str = '') -> dict[str, Any]:
        items: list[tuple[str, Any]] = []
        for k, v in d.items():
            new_key = f"{parent_key}.{k}" if parent_key else k
            if isinstance(v, dict):
                items.extend(self._flatten_dict(v, new_key).items())
            else:
                items.append((new_key, v))
        return dict(items)

    def _seed_default_config(self, config_repo: SQLiteConfigRepository) -> None:
        """
        Seed the configuration database with default values from default_config.yaml.
        """
        logger.info("Seeding database with default configuration...")
        
        import picframe
        pkg_dir = Path(picframe.__file__).parent
        default_yaml_path = pkg_dir / "config" / "default_config.yaml"
        
        if not default_yaml_path.exists():
            logger.error(f"Default configuration file not found at {default_yaml_path}")
            return
            
        try:
            with open(default_yaml_path, 'r') as f:
                raw_defaults = yaml.safe_load(f)
                
            # Validate against Pydantic model
            validated_config = AppConfig(**raw_defaults)
            
            # Flatten and Seed
            flat_config = self._flatten_dict(validated_config.model_dump())
            for key, value in flat_config.items():
                config_repo.set_app_config(key, value)
                
            logger.info("Database seeded successfully.")
        except Exception as e:
            logger.error(f"Failed to seed default configuration: {e}")
