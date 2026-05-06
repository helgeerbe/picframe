import pytest
from unittest.mock import MagicMock, patch
import time
from picframe.core.services.geocoding_worker import GeocodingWorker

@pytest.fixture
def mock_repo() -> MagicMock:
    repo = MagicMock()
    repo.get_location.return_value = None
    repo.dequeue_location_lookup.return_value = None
    return repo

@pytest.fixture
def mock_geo_reverse() -> MagicMock:
    geo = MagicMock()
    geo.get_address.return_value = "Test Address"
    return geo

@pytest.fixture
def mock_config_repo() -> MagicMock:
    repo = MagicMock()
    repo.get_app_config_bool.return_value = True
    repo.get_app_config.return_value = "test_key"
    return repo

def test_geocoding_worker_initialization(mock_repo: MagicMock, mock_config_repo: MagicMock) -> None:
    worker = GeocodingWorker(mock_repo, mock_config_repo)
    assert not worker._is_running

@patch('picframe.core.services.geocoding_worker.GeoReverse')
def test_geocoding_worker_start_stop(mock_geo_reverse_class: MagicMock, mock_repo: MagicMock, mock_config_repo: MagicMock) -> None:
    worker = GeocodingWorker(mock_repo, mock_config_repo)
    worker.start()
    assert worker._is_running
    assert worker._thread is not None
    assert worker._thread.is_alive()
    
    worker.stop()
    assert not worker._is_running
    if worker._thread is not None:
        worker._thread.join(timeout=1.0)
        assert not worker._thread.is_alive()

@patch('picframe.core.services.geocoding_worker.GeoReverse')
def test_geocoding_worker_queue_coordinates(mock_geo_reverse_class: MagicMock, mock_repo: MagicMock, mock_config_repo: MagicMock) -> None:
    worker = GeocodingWorker(mock_repo, mock_config_repo)
    worker.start()
    worker.queue_lookup(10.1234, 20.5678)
    mock_repo.enqueue_location_lookup.assert_called_once_with(10.1234, 20.5678)
    worker.stop()

@patch('picframe.core.services.geocoding_worker.GeoReverse')
def test_geocoding_worker_process_queue(mock_geo_reverse_class: MagicMock, mock_repo: MagicMock, mock_config_repo: MagicMock) -> None:
    mock_geo_instance = MagicMock()
    mock_geo_instance.get_address.return_value = "Test Address"
    mock_geo_reverse_class.return_value = mock_geo_instance
    
    # Mock the dequeue to return our task once, then None
    mock_repo.dequeue_location_lookup.side_effect = [(10.1234, 20.5678), None, None]
    
    worker = GeocodingWorker(mock_repo, mock_config_repo)
    worker.start()
    
    time.sleep(0.1) # Give it time to process
    worker.stop()
    
    mock_repo.get_location.assert_called_with(10.1234, 20.5678)
    mock_geo_instance.get_address.assert_called_once_with(10.1234, 20.5678)
    mock_repo.save_location.assert_called_once_with(10.1234, 20.5678, "Test Address")

@patch('picframe.core.services.geocoding_worker.GeoReverse')
def test_geocoding_worker_cache_hit(mock_geo_reverse_class: MagicMock, mock_repo: MagicMock, mock_config_repo: MagicMock) -> None:
    mock_geo_instance = MagicMock()
    mock_geo_reverse_class.return_value = mock_geo_instance
    mock_repo.get_location.return_value = "Cached Address"
    
    worker = GeocodingWorker(mock_repo, mock_config_repo)
    worker.start()
    worker.queue_lookup(10.1234, 20.5678)
    
    time.sleep(0.1)
    worker.stop()
    
    mock_repo.get_location.assert_called_once_with(10.1234, 20.5678)
    mock_geo_instance.get_address.assert_not_called()
    mock_repo.save_location.assert_not_called()
