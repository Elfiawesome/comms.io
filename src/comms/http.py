from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from comms.config import NetworkConfig
from comms.logging import get_logger
from comms.ratelimit import AdaptiveRateLimiter

log = get_logger("http")


class HttpError(RuntimeError):
    pass


class RateLimitError(HttpError):
    pass


class BudgetExceeded(RuntimeError):
    pass


class RobotsDenied(HttpError):
    pass


class RunBudget:
    def __init__(self, max_requests: int, max_runtime_seconds: float) -> None:
        self.max_requests = max_requests
        self.max_runtime_seconds = max_runtime_seconds
        self.started = time.monotonic()
        self.requests = 0
        self.stop_reason: str | None = None

    def check(self) -> None:
        if self.stop_reason:
            raise BudgetExceeded(self.stop_reason)
        if self.max_requests > 0 and self.requests >= self.max_requests:
            self.stop_reason = "max_requests"
            raise BudgetExceeded(self.stop_reason)
        if self.max_runtime_seconds > 0:
            elapsed = time.monotonic() - self.started
            if elapsed >= self.max_runtime_seconds:
                self.stop_reason = "max_runtime"
                raise BudgetExceeded(self.stop_reason)

    def record_request(self) -> None:
        self.requests += 1

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started


@dataclass
class Response:
    url: str
    status_code: int
    headers: dict[str, str]
    text: str

    def json(self) -> Any:
        import json

        return json.loads(self.text)


class RobotsGuard:
    def __init__(self, client: httpx.AsyncClient, enabled: bool = True) -> None:
        self.client = client
        self.enabled = enabled
        self._cache: dict[str, RobotFileParser | None] = {}

    async def allowed(self, url: str) -> bool:
        if not self.enabled:
            return True
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self._cache:
            self._cache[origin] = await self._load(origin)
        parser = self._cache[origin]
        if parser is None:
            return True
        return parser.can_fetch("*", url)

    async def _load(self, origin: str) -> RobotFileParser | None:
        parser = RobotFileParser()
        parser.set_url(f"{origin}/robots.txt")
        try:
            response = await self.client.get(f"{origin}/robots.txt", timeout=15)
            if response.status_code >= 400:
                log.warning(
                    "robots.txt unavailable for %s (HTTP %s); allowing by default",
                    origin,
                    response.status_code,
                )
                return None
            parser.parse(response.text.splitlines())
            return parser
        except Exception as exc:
            log.warning("Could not read robots.txt for %s: %s; allowing by default", origin, exc)
            return None


class HttpClient:
    def __init__(
        self,
        network: NetworkConfig,
        budget: RunBudget,
        limiter: AdaptiveRateLimiter | None = None,
    ) -> None:
        self.network = network
        self.budget = budget
        self.limiter = limiter or AdaptiveRateLimiter(network.requests_per_second)
        self.client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=network.timeout_seconds,
            headers={"User-Agent": network.user_agent},
        )
        self.robots = RobotsGuard(self.client, enabled=network.respect_robots)

    async def close(self) -> None:
        await self.client.aclose()

    async def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        check_robots: bool = True,
        max_retries: int | None = None,
    ) -> Response:
        if check_robots and not await self.robots.allowed(url):
            raise RobotsDenied(f"robots.txt does not allow {url}")

        retries = self.network.max_retries if max_retries is None else max_retries
        last_error: Exception | None = None
        for attempt in range(1, retries + 1):
            self.budget.check()
            await self.limiter.acquire()
            self.budget.record_request()
            try:
                response = await self.client.get(url, params=params, headers=headers)
            except httpx.RequestError as exc:
                last_error = exc
                log.warning("Request failed %s (attempt %s/%s): %s", url, attempt, retries, exc)
                if attempt < retries:
                    await asyncio.sleep(min(30.0, 2.0**attempt) * random.uniform(0.8, 1.2))
                    continue
                raise HttpError(str(exc)) from exc

            if response.status_code == 429:
                retry_after = _retry_after_seconds(response.headers.get("retry-after"))
                self.limiter.report_429(retry_after)
                log.warning("429 on %s (attempt %s/%s)", url, attempt, retries)
                if attempt < retries:
                    await asyncio.sleep(retry_after or min(60.0, 4.0 * 2 ** (attempt - 1)))
                    continue
                raise RateLimitError(f"429 Too Many Requests: {url}")

            if response.status_code >= 500:
                last_error = HttpError(f"HTTP {response.status_code}")
                log.warning(
                    "HTTP %s on %s (attempt %s/%s)", response.status_code, url, attempt, retries
                )
                if attempt < retries:
                    await asyncio.sleep(min(60.0, 2.0**attempt) * random.uniform(0.8, 1.2))
                    continue
                raise HttpError(f"HTTP {response.status_code}: {url}")

            self.limiter.report_success()
            return Response(
                url=str(response.url),
                status_code=response.status_code,
                headers={key.lower(): value for key, value in response.headers.items()},
                text=response.text,
            )

        raise HttpError(str(last_error or "request failed"))


def _retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None
