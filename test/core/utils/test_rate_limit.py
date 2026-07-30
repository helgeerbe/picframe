from unittest.mock import patch

import pytest

from picframe.core.utils.rate_limit import TokenBucket


def test_token_bucket_initialization():
    bucket = TokenBucket(capacity=10, refill_rate=2.0)
    assert bucket.capacity == 10
    assert bucket.refill_rate == 2.0
    assert bucket.tokens == 10.0


def test_token_bucket_invalid_initialization():
    with pytest.raises(ValueError):
        TokenBucket(capacity=0, refill_rate=1.0)
    with pytest.raises(ValueError):
        TokenBucket(capacity=10, refill_rate=0.0)


def test_token_bucket_consume_success():
    bucket = TokenBucket(capacity=5, refill_rate=1.0)
    assert bucket.consume(1) is True
    assert bucket.tokens == pytest.approx(4.0, abs=1e-2)
    assert bucket.consume(4) is True
    assert bucket.tokens == pytest.approx(0.0, abs=1e-2)


def test_token_bucket_consume_failure():
    bucket = TokenBucket(capacity=5, refill_rate=1.0)
    assert bucket.consume(6) is False
    assert bucket.tokens == pytest.approx(
        5.0, abs=1e-2
    )  # Tokens should not be consumed if request fails


@patch("time.monotonic")
def test_token_bucket_refill(mock_monotonic):
    # Start at time 0
    mock_monotonic.return_value = 0.0
    bucket = TokenBucket(capacity=5, refill_rate=2.0)

    # Consume all tokens
    assert bucket.consume(5) is True
    assert bucket.tokens == 0.0

    # Advance time by 1 second (should add 2 tokens)
    mock_monotonic.return_value = 1.0
    assert bucket.consume(1) is True
    assert bucket.tokens == 1.0  # 0 + 2 - 1 = 1

    # Advance time by 10 seconds (should fill to capacity)
    mock_monotonic.return_value = 11.0
    assert bucket.consume(1) is True
    assert bucket.tokens == 4.0  # Capped at 5, then consumed 1
