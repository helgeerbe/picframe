import os
import sqlite3
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from picframe.core.services.bootstrapper import EnvironmentBootstrapper


@pytest.fixture
def temp_dir(tmp_path):
    return tmp_path / ".picframe"


def test_bootstrapper_initialization(temp_dir):
    bootstrapper = EnvironmentBootstrapper(base_dir=str(temp_dir))
    assert bootstrapper.base_dir == temp_dir
    assert bootstrapper.data_dir == temp_dir / "data"
    assert bootstrapper.config_db_path == temp_dir / "data" / "config.db3"
    assert bootstrapper.media_db_path == temp_dir / "data" / "media_cache.db3"


def test_create_directories(temp_dir):
    bootstrapper = EnvironmentBootstrapper(base_dir=str(temp_dir))
    bootstrapper._create_directories()
    assert bootstrapper.data_dir.exists()
    assert bootstrapper.data_dir.is_dir()


@patch("picframe.core.services.bootstrapper.shutil")
@patch("picframe.core.services.bootstrapper.Path.exists")
@patch("picframe.core.services.bootstrapper.Path.iterdir")
def test_copy_assets(mock_iterdir, mock_exists, mock_shutil, temp_dir):
    bootstrapper = EnvironmentBootstrapper(base_dir=str(temp_dir))
    
    # Mock the package data directory and its contents
    mock_exists.side_effect = lambda: True # pkg_data_dir exists
    
    mock_file = MagicMock()
    mock_file.name = "test.txt"
    mock_file.is_dir.return_value = False
    
    mock_dir = MagicMock()
    mock_dir.name = "test_dir"
    mock_dir.is_dir.return_value = True
    
    mock_iterdir.return_value = [mock_file, mock_dir]
    
    # Mock destination exists to False so it copies, but pkg_data_dir exists to True
    def mock_exists_side_effect(*args, **kwargs):
        return True
        
    mock_exists.side_effect = mock_exists_side_effect
    
    with patch.object(Path, 'exists', return_value=False):
        # We need to patch the specific Path instance's exists method inside the loop
        # But it's easier to just mock the whole Path.exists and handle the pkg_data_dir check
        pass
        
    # Let's just mock the pkg_data_dir.exists() directly
    # We need enough side_effects for:
    # 1. pkg_data_dir.exists() -> True
    # 2. dest_item.exists() for file -> False
    # 3. dest_item.exists() for dir -> False
    # 4. no_pictures_src.exists() -> True
    # 5. no_pictures_dest.exists() -> False
    with patch('picframe.core.services.bootstrapper.Path.exists', side_effect=[True, False, False, True, False]):
        bootstrapper._copy_assets()
    
    assert mock_shutil.copy2.call_count == 2
    mock_shutil.copytree.assert_called_once()


@patch("picframe.core.services.bootstrapper.input")
def test_prompt_deletion_keep(mock_input, temp_dir):
    bootstrapper = EnvironmentBootstrapper(base_dir=str(temp_dir))
    test_file = temp_dir / "test.db"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.touch()
    
    mock_input.return_value = "n"
    result = bootstrapper._prompt_deletion(test_file, "Test")
    
    assert result is False
    assert test_file.exists()

@patch("picframe.core.services.bootstrapper.input")
def test_prompt_deletion_delete(mock_input, temp_dir):
    bootstrapper = EnvironmentBootstrapper(base_dir=str(temp_dir))
    test_file = temp_dir / "test.db"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.touch()
    
    mock_input.return_value = "y"
    result = bootstrapper._prompt_deletion(test_file, "Test")
    
    assert result is True
    assert not test_file.exists()

def test_prompt_deletion_force(temp_dir):
    bootstrapper = EnvironmentBootstrapper(base_dir=str(temp_dir), force=True)
    test_file = temp_dir / "test.db"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.touch()
    
    result = bootstrapper._prompt_deletion(test_file, "Test")
    
    assert result is True
    assert not test_file.exists()

def test_bootstrap_full(temp_dir):
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
