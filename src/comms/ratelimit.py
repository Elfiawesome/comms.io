from __future__ import annotations

import asyncio
import random
import time


class AdaptiveRateLimiter:
    """Token bucket with conservative adaptive backoff.

    The defaults intentionally favour being slow over being blocked.
    """

    def __init__(
        self,
        rate_per_sec: float = 1.0,
        *,
        min_rate: float = 0.1,
        max_cooldown: float = 120.0,
        jitter_seconds: float = 0.5,
    ) -> None:
        self.base_rate = max(0.01, rate_per_sec)
        self.current_rate = self.base_rate
        self.min_rate = max(0.01, min_rate)
        self.max_cooldown = max_cooldown
        self.jitter_seconds = max(0.0, jitter_seconds)
        self.tokens = 1.0
        self.last_refill = time.monotonic()
        self.consecutive_429 = 0
        self.cooldown_until = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                if now < self.cooldown_until:
                    wait = self.cooldown_until - now
                else:
                    elapsed = now - self.last_refill
                    self.tokens = min(1.0, self.tokens + elapsed * self.current_rate)
                    self.last_refill = now
                    if self.tokens >= 1.0:
                        self.tokens -= 1.0
                        wait = 0.0
                    else:
                        wait = min(5.0, (1.0 - self.tokens) / self.current_rate)
            if wait <= 0:
                break
            await asyncio.sleep(wait)

        if self.jitter_seconds:
            await asyncio.sleep(random.uniform(0.0, self.jitter_seconds))

    def report_429(self, retry_after: float | None = None) -> None:
        self.consecutive_429 += 1
        self.current_rate = max(self.min_rate, self.current_rate * 0.5)
        backoff = (
            retry_after
            if retry_after is not None
            else 8.0 * (2 ** min(self.consecutive_429 - 1, 4))
        )
        self.cooldown_until = time.monotonic() + min(self.max_cooldown, max(1.0, backoff))
        self.tokens = 0.0

    def report_success(self) -> None:
        self.consecutive_429 = 0
        self.cooldown_until = 0.0
        self.current_rate = min(self.base_rate, self.current_rate * 1.1)
