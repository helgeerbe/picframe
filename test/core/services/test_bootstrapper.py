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
    with patch('picframe.core.services.bootstrapper.Path.exists', side_effect=[True, False, False]):
        bootstrapper._copy_assets()
    
    mock_shutil.copy2.assert_called_once()
    mock_shutil.copytree.assert_called_once()


def test_initialize_databases(temp_dir):
    bootstrapper = EnvironmentBootstrapper(base_dir=str(temp_dir))
    bootstrapper._create_directories() # Need dir first
    bootstrapper._initialize_databases()
    
    assert bootstrapper.config_db_path.exists()
    assert bootstrapper.media_db_path.exists()
    
    # Verify they are valid sqlite databases
    conn = sqlite3.connect(bootstrapper.config_db_path)
    conn.close()
    
    conn = sqlite3.connect(bootstrapper.media_db_path)
    conn.close()


def test_bootstrap_full(temp_dir):
    bootstrapper = EnvironmentBootstrapper(base_dir=str(temp_dir))
    
    with patch.object(bootstrapper, '_create_directories') as mock_create_dir, \
         patch.object(bootstrapper, '_copy_assets') as mock_copy_assets, \
         patch.object(bootstrapper, '_initialize_databases') as mock_init_db:
        
        bootstrapper.bootstrap()
        
        mock_create_dir.assert_called_once()
        mock_copy_assets.assert_called_once()
        mock_init_db.assert_called_once()
