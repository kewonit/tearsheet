import stat
import threading

import pytest

from tearsheet.core.cache import Cache


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def cache(tmp_path, clock):
    instance = Cache(tmp_path / "cache.sqlite3", clock=clock)
    yield instance
    instance.close()


def test_returns_what_was_stored(cache):
    cache.put("financials", "EXAMPLE", {"revenue": 1234.5, "name": "₹ test"}, ttl_s=60)
    entry = cache.get("financials", "EXAMPLE")
    assert entry.value == {"revenue": 1234.5, "name": "₹ test"}
    assert entry.fetched_at == 1000.0
    assert entry.stale is False


def test_missing_entry_is_none(cache):
    assert cache.get("financials", "NOPE") is None


def test_same_key_in_another_dataset_is_separate(cache):
    cache.put("financials", "EXAMPLE", 1, ttl_s=60)
    assert cache.get("ownership", "EXAMPLE") is None


def test_entry_is_fresh_until_just_before_expiry(cache, clock):
    cache.put("financials", "EXAMPLE", 1, ttl_s=60)
    clock.now += 59.9
    assert cache.get("financials", "EXAMPLE") is not None


def test_entry_expires_exactly_at_its_ttl(cache, clock):
    cache.put("financials", "EXAMPLE", 1, ttl_s=60)
    clock.now += 60
    assert cache.get("financials", "EXAMPLE") is None


def test_expired_entry_can_be_read_and_is_marked_stale(cache, clock):
    cache.put("financials", "EXAMPLE", 1, ttl_s=60)
    clock.now += 61
    entry = cache.get("financials", "EXAMPLE", allow_stale=True)
    assert entry.value == 1
    assert entry.stale is True


def test_put_replaces_and_resets_the_expiry(cache, clock):
    cache.put("financials", "EXAMPLE", 1, ttl_s=60)
    clock.now += 50
    cache.put("financials", "EXAMPLE", 2, ttl_s=60)
    clock.now += 50
    assert cache.get("financials", "EXAMPLE").value == 2


def test_values_survive_a_restart(tmp_path, clock):
    path = tmp_path / "cache.sqlite3"
    first = Cache(path, clock=clock)
    first.put("financials", "EXAMPLE", 1, ttl_s=60)
    first.close()
    second = Cache(path, clock=clock)
    assert second.get("financials", "EXAMPLE").value == 1
    second.close()


def test_file_is_private_to_the_owner(tmp_path):
    path = tmp_path / "cache.sqlite3"
    Cache(path).close()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_counts_group_by_dataset(cache):
    cache.put("financials", "A", 1, ttl_s=60)
    cache.put("financials", "B", 1, ttl_s=60)
    cache.put("ownership", "A", 1, ttl_s=60)
    assert cache.counts() == {"financials": 2, "ownership": 1}


def test_purge_removes_only_expired_entries(cache, clock):
    cache.put("financials", "OLD", 1, ttl_s=10)
    cache.put("financials", "NEW", 1, ttl_s=100)
    clock.now += 50
    assert cache.purge_expired() == 1
    assert cache.get("financials", "OLD", allow_stale=True) is None
    assert cache.get("financials", "NEW") is not None


@pytest.mark.parametrize("ttl_s", [0, -1])
def test_rejects_a_ttl_that_is_not_positive(cache, ttl_s):
    with pytest.raises(ValueError):
        cache.put("financials", "EXAMPLE", 1, ttl_s=ttl_s)


def test_keys_are_treated_as_data_not_sql(cache):
    key = "x'; DROP TABLE entries; --"
    cache.put("financials", key, 1, ttl_s=60)
    assert cache.get("financials", key).value == 1


def test_safe_to_use_from_several_threads(cache):
    errors = []

    def work(n):
        try:
            for i in range(50):
                cache.put("financials", f"{n}-{i}", i, ttl_s=60)
                cache.get("financials", f"{n}-{i}")
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(n,)) for n in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert cache.counts() == {"financials": 200}
