import asyncio

import pytest

from tearsheet.core.ratelimit import RateLimiter


class FakeTime:
    def __init__(self):
        self.now = 100.0

    def clock(self):
        return self.now

    async def sleep(self, seconds):
        self.now += seconds


def limiter(time_source, **kwargs):
    return RateLimiter(clock=time_source.clock, sleep=time_source.sleep, **kwargs)


def test_first_request_does_not_wait():
    async def run():
        fake = FakeTime()
        async with limiter(fake, min_interval_s=1).slot():
            pass
        assert fake.now == 100.0

    asyncio.run(run())


def test_requests_start_at_least_the_interval_apart():
    async def run():
        fake = FakeTime()
        limit = limiter(fake, min_interval_s=1.5)
        starts = []
        for _ in range(3):
            async with limit.slot():
                starts.append(fake.now)
        assert starts == [100.0, 101.5, 103.0]

    asyncio.run(run())


def test_no_wait_once_the_interval_has_passed():
    async def run():
        fake = FakeTime()
        limit = limiter(fake, min_interval_s=1)
        async with limit.slot():
            pass
        fake.now += 5
        before = fake.now
        async with limit.slot():
            assert fake.now == before

    asyncio.run(run())


def test_concurrent_callers_are_spaced_out_too():
    async def run():
        fake = FakeTime()
        limit = limiter(fake, min_interval_s=1, max_concurrent=5)
        starts = []

        async def call():
            async with limit.slot():
                starts.append(fake.now)

        await asyncio.gather(*(call() for _ in range(4)))
        assert sorted(starts) == [100.0, 101.0, 102.0, 103.0]

    asyncio.run(run())


def test_never_runs_more_than_the_concurrency_cap():
    async def run():
        limit = RateLimiter(min_interval_s=0, max_concurrent=2)
        active = peak = 0

        async def call():
            nonlocal active, peak
            async with limit.slot():
                active += 1
                peak = max(peak, active)
                await asyncio.sleep(0.01)
                active -= 1

        await asyncio.gather(*(call() for _ in range(8)))
        assert peak == 2

    asyncio.run(run())


def test_a_failed_request_frees_its_slot():
    async def run():
        limit = RateLimiter(min_interval_s=0, max_concurrent=1)
        with pytest.raises(RuntimeError):
            async with limit.slot():
                raise RuntimeError("boom")
        async with asyncio.timeout(1):
            async with limit.slot():
                pass

    asyncio.run(run())


@pytest.mark.parametrize("kwargs", [{"min_interval_s": -1}, {"max_concurrent": 0}])
def test_rejects_bad_settings(kwargs):
    with pytest.raises(ValueError):
        RateLimiter(**kwargs)
