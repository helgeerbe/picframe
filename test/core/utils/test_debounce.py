from unittest.mock import patch

import pytest

from picframe.core.utils.debounce import Debouncer


def test_debouncer_initialization():
    debouncer = Debouncer(delay_ms=500)
    assert debouncer.delay_seconds == 0.5


def test_debouncer_invalid_initialization():
    with pytest.raises(ValueError):
        Debouncer(delay_ms=-100)


@patch("time.monotonic")
def test_debouncer_should_execute(mock_monotonic):
    debouncer = Debouncer(delay_ms=500)

    # First call should execute
    mock_monotonic.return_value = 100.0
    assert debouncer.should_execute("test_action") is True

    # Call within delay should be debounced
    mock_monotonic.return_value = 100.4
    assert debouncer.should_execute("test_action") is False

    # Call after delay should execute
    mock_monotonic.return_value = 100.6
    assert debouncer.should_execute("test_action") is True

    # Different key should execute independently
    mock_monotonic.return_value = 100.7
    assert debouncer.should_execute("other_action") is True
