import os
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import patch, MagicMock

import pytest

from picframe.core.services.bootstrapper import EnvironmentBootstrapper


@pytest.fixture
def temp_dir(tmp_path: Path) -> Path:
    return tmp_path / ".picframe"


def test_bootstrapper_initialization(temp_dir: Path) -> None:
    bootstrapper = EnvironmentBootstrapper(base_dir=str(temp_dir))
    assert bootstrapper.base_dir == temp_dir
    assert bootstrapper.data_dir == temp_dir / "data"
    assert bootstrapper.config_db_path == temp_dir / "data" / "config.db3"
    assert bootstrapper.media_db_path == temp_dir / "data" / "media_cache.db3"


def test_create_directories(temp_dir: Path) -> None:
    bootstrapper = EnvironmentBootstrapper(base_dir=str(temp_dir))
    bootstrapper._create_directories()
    assert bootstrapper.data_dir.exists()
    assert bootstrapper.data_dir.is_dir()


def test_copy_assets(temp_dir: Path) -> None:
    bootstrapper = EnvironmentBootstrapper(base_dir=str(temp_dir / "user_dir"))
    bootstrapper._create_directories()
    
    # Create fake package directory structure
    fake_pkg_dir = temp_dir / "fake_picframe"
    fake_data_dir = fake_pkg_dir / "data"
    fake_html_dir = fake_pkg_dir / "html"
    
    fake_data_dir.mkdir(parents=True)
    (fake_data_dir / "test.txt").touch()
    (fake_data_dir / "test_dir").mkdir()
    (fake_data_dir / "test_dir" / "inner.txt").touch()
    (fake_data_dir / "no_pictures.jpg").touch()
    
    fake_html_dir.mkdir(parents=True)
    (fake_html_dir / "index.html").touch()
    
    with patch('picframe.__file__', str(fake_pkg_dir / "__init__.py")):
        bootstrapper._copy_assets()
        
    # Assert files were copied
    assert (bootstrapper.data_dir / "test.txt").exists()
    assert (bootstrapper.data_dir / "test_dir").is_dir()
    assert (bootstrapper.data_dir / "test_dir" / "inner.txt").exists()
    assert (bootstrapper.data_dir / "no_pictures.jpg").exists()
    assert (bootstrapper.base_dir / "html" / "index.html").exists()


@patch("picframe.core.services.bootstrapper.input")
def test_prompt_deletion_keep(mock_input: MagicMock, temp_dir: Path) -> None:
    bootstrapper = EnvironmentBootstrapper(base_dir=str(temp_dir))
    test_file = temp_dir / "test.db"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.touch()
    
    mock_input.return_value = "n"
    result = bootstrapper._prompt_deletion(test_file, "Test")
    
    assert result is False
    assert test_file.exists()

@patch("picframe.core.services.bootstrapper.input")
def test_prompt_deletion_delete(mock_input: MagicMock, temp_dir: Path) -> None:
    bootstrapper = EnvironmentBootstrapper(base_dir=str(temp_dir))
    test_file = temp_dir / "test.db"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.touch()
    
    mock_input.return_value = "y"
    result = bootstrapper._prompt_deletion(test_file, "Test")
    
    assert result is True
    assert not test_file.exists()

def test_prompt_deletion_force(temp_dir: Path) -> None:
    bootstrapper = EnvironmentBootstrapper(base_dir=str(temp_dir), force=True)
    test_file = temp_dir / "test.db"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.touch()
    
    result = bootstrapper._prompt_deletion(test_file, "Test")
    
    assert result is True
    assert not test_file.exists()

def test_bootstrap_full(temp_dir: Path) -> None:
    bootstrapper = EnvironmentBootstrapper(base_dir=str(temp_dir))
    
    with patch.object(bootstrapper, '_create_directories') as mock_create_dir, \
         patch.object(bootstrapper, '_copy_assets') as mock_copy_assets, \
         patch.object(bootstrapper, '_prompt_deletion', return_value=True) as mock_prompt, \
         patch('picframe.core.services.bootstrapper.SQLiteConfigRepository') as mock_config_repo, \
         patch('picframe.core.services.bootstrapper.SQLiteMediaRepository') as mock_media_repo, \
         patch.object(bootstrapper, '_seed_default_config') as mock_seed:
        
        # Mock the repo to return empty config so seeding is triggered
        mock_repo_instance = mock_config_repo.return_value
        mock_repo_instance.get_all_app_config.return_value = {}
        
        bootstrapper.bootstrap()
        
        mock_create_dir.assert_called_once()
        mock_copy_assets.assert_called_once()
        assert mock_prompt.call_count == 2
        mock_seed.assert_called_once_with(mock_repo_instance)
