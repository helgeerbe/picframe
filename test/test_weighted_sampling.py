import random
import time
from collections import Counter
from unittest.mock import MagicMock

from picframe.model import Model


def _make_model(half_life_days=365, sample_limit=None, portrait_pairs=False, shuffle=True, recent_n=0):
    """Build a Model instance with __init__ bypassed and the bits we need stubbed."""
    m = Model.__new__(Model)
    m._Model__config = {
        "model": {
            "age_weighted_sampling": True,
            "recency_half_life_days": half_life_days,
            "sample_limit": sample_limit,
            "recent_n": recent_n,
        }
    }
    m._Model__logger = MagicMock()
    m._Model__image_cache = MagicMock()
    m._Model__image_cache.portrait_pairs = portrait_pairs
    m.shuffle = shuffle
    return m


def _stub_cache_rows(model, rows):
    model._Model__image_cache.query_file_ids_with_timestamps = MagicMock(return_value=rows)


def test_returns_empty_when_no_rows():
    m = _make_model()
    _stub_cache_rows(m, [])
    assert m._Model__get_weighted_sample("1") == []


def test_returns_one_tuple_per_row():
    m = _make_model()
    now = time.time()
    _stub_cache_rows(m, [(i, now - i * 86400) for i in range(50)])
    result = m._Model__get_weighted_sample("1")
    assert len(result) == 50
    assert all(isinstance(r, tuple) and len(r) == 1 for r in result)
    assert sorted(r[0] for r in result) == list(range(50))


def test_sample_limit_truncates():
    m = _make_model(sample_limit=10)
    now = time.time()
    _stub_cache_rows(m, [(i, now - i * 86400) for i in range(100)])
    result = m._Model__get_weighted_sample("1")
    assert len(result) == 10


def test_sample_limit_larger_than_pool_returns_all():
    m = _make_model(sample_limit=500)
    now = time.time()
    _stub_cache_rows(m, [(i, now - i * 86400) for i in range(20)])
    result = m._Model__get_weighted_sample("1")
    assert len(result) == 20


def test_newer_photos_picked_more_often_with_small_limit():
    # With a tight sample_limit and 1-day half-life over a 100-day spread,
    # the front of the list should be dominated by newer file_ids on average.
    random.seed(42)
    m = _make_model(half_life_days=1, sample_limit=10)
    now = time.time()
    # file_id 0 = newest, file_id 99 = oldest
    rows = [(i, now - i * 86400) for i in range(100)]
    hits = Counter()
    for _ in range(200):
        _stub_cache_rows(m, rows)
        for tup in m._Model__get_weighted_sample("1"):
            hits[tup[0]] += 1
    newest_quarter = sum(hits[i] for i in range(25))
    oldest_quarter = sum(hits[i] for i in range(75, 100))
    assert newest_quarter > 5 * oldest_quarter, (newest_quarter, oldest_quarter)


def test_equal_timestamps_keep_all_photos():
    m = _make_model()
    ts = time.time()
    _stub_cache_rows(m, [(i, ts) for i in range(30)])
    result = m._Model__get_weighted_sample("1")
    assert sorted(r[0] for r in result) == list(range(30))


def test_very_old_photos_do_not_crash():
    # 100-year-old photo with 1-day half-life used to risk overflow.
    m = _make_model(half_life_days=1)
    now = time.time()
    _stub_cache_rows(m, [(1, now), (2, now - 100 * 365 * 86400)])
    result = m._Model__get_weighted_sample("1")
    assert len(result) == 2
    # Newest should almost always win the top slot under huge bias.
    assert result[0][0] == 1


def test_portrait_pairs_disables_weighted_sampling(caplog):
    m = _make_model(portrait_pairs=True)
    # __use_weighted_sampling is what the caller checks before invoking the sampler.
    with caplog.at_level("WARNING"):
        assert m._Model__use_weighted_sampling() is False
    # Subsequent calls cache the decision and do not re-log.
    assert m._Model__use_weighted_sampling() is False


def test_shuffle_false_logs_warning_but_still_runs():
    m = _make_model(shuffle=False)
    assert m._Model__use_weighted_sampling() is True
    m._Model__logger.warning.assert_called()


def test_recent_n_set_logs_warning():
    m = _make_model(recent_n=7)
    assert m._Model__use_weighted_sampling() is True
    m._Model__logger.warning.assert_called()
