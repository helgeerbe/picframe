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


def _rows(specs, now=None):
    """Build cache rows from (file_id, age_days, is_portrait) tuples."""
    if now is None:
        now = time.time()
    return [(fid, now - age_days * 86400, int(is_portrait)) for fid, age_days, is_portrait in specs]


def test_returns_empty_when_no_rows():
    m = _make_model()
    _stub_cache_rows(m, [])
    assert m._Model__get_weighted_sample("1") == []


def test_returns_one_tuple_per_row():
    m = _make_model()
    _stub_cache_rows(m, _rows([(i, i, False) for i in range(50)]))
    result = m._Model__get_weighted_sample("1")
    assert len(result) == 50
    assert all(isinstance(r, tuple) and len(r) == 1 for r in result)
    assert sorted(r[0] for r in result) == list(range(50))


def test_sample_limit_truncates():
    m = _make_model(sample_limit=10)
    _stub_cache_rows(m, _rows([(i, i, False) for i in range(100)]))
    result = m._Model__get_weighted_sample("1")
    assert len(result) == 10


def test_sample_limit_larger_than_pool_returns_all():
    m = _make_model(sample_limit=500)
    _stub_cache_rows(m, _rows([(i, i, False) for i in range(20)]))
    result = m._Model__get_weighted_sample("1")
    assert len(result) == 20


def test_newer_photos_picked_more_often_with_small_limit():
    random.seed(42)
    m = _make_model(half_life_days=1, sample_limit=10)
    rows = _rows([(i, i, False) for i in range(100)])  # fid 0 newest, fid 99 oldest
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
    _stub_cache_rows(m, _rows([(i, 0, False) for i in range(30)]))
    result = m._Model__get_weighted_sample("1")
    assert sorted(r[0] for r in result) == list(range(30))


def test_very_old_photos_do_not_crash():
    m = _make_model(half_life_days=1)
    _stub_cache_rows(m, _rows([(1, 0, False), (2, 100 * 365, False)]))
    result = m._Model__get_weighted_sample("1")
    assert len(result) == 2
    assert result[0][0] == 1


def test_portrait_pairs_joins_consecutive_portraits():
    random.seed(0)
    m = _make_model(portrait_pairs=True)
    # All portraits, all same age — pair-joining alone should produce 2-tuples.
    _stub_cache_rows(m, _rows([(i, 0, True) for i in range(6)]))
    result = m._Model__get_weighted_sample("1")
    assert len(result) == 3
    assert all(len(t) == 2 for t in result)
    assert sorted(fid for t in result for fid in t) == list(range(6))


def test_portrait_pairs_handles_odd_count():
    random.seed(0)
    m = _make_model(portrait_pairs=True)
    _stub_cache_rows(m, _rows([(i, 0, True) for i in range(5)]))
    result = m._Model__get_weighted_sample("1")
    pair_count = sum(1 for t in result if len(t) == 2)
    solo_count = sum(1 for t in result if len(t) == 1)
    assert pair_count == 2 and solo_count == 1


def test_portrait_pairs_keeps_landscapes_solo():
    random.seed(0)
    m = _make_model(portrait_pairs=True)
    _stub_cache_rows(m, _rows([
        (0, 0, False), (1, 0, True), (2, 0, True),
        (3, 0, False), (4, 0, True),
    ]))
    result = m._Model__get_weighted_sample("1")
    landscape_ids = {fid for t in result if len(t) == 1 for fid in t}
    portrait_ids = {fid for t in result if len(t) == 2 for fid in t}
    assert 0 in landscape_ids and 3 in landscape_ids
    assert portrait_ids == {1, 2} or {1, 4} in [portrait_ids] or {2, 4} in [portrait_ids]
    # Total file_ids should be preserved (the lone portrait that didn't pair shows up solo).
    all_ids = {fid for t in result for fid in t}
    assert all_ids == {0, 1, 2, 3, 4}


def test_portrait_pairs_off_returns_only_singletons():
    m = _make_model(portrait_pairs=False)
    _stub_cache_rows(m, _rows([(i, 0, True) for i in range(4)]))
    result = m._Model__get_weighted_sample("1")
    assert all(len(t) == 1 for t in result)


def test_shuffle_false_logs_warning_but_still_runs():
    m = _make_model(shuffle=False)
    assert m._Model__use_weighted_sampling() is True
    m._Model__logger.warning.assert_called()


def test_recent_n_set_logs_warning():
    m = _make_model(recent_n=7)
    assert m._Model__use_weighted_sampling() is True
    m._Model__logger.warning.assert_called()


def test_portrait_pairs_no_longer_disables_weighted_sampling():
    m = _make_model(portrait_pairs=True)
    assert m._Model__use_weighted_sampling() is True
