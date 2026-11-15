# Adding a source

A source is a Python class registered with `comms.registry.register_source`.
It owns its HTTP client, rate limiting, discovery, parsing, and normalization.
The pipeline only needs `discover()` and `fetch()`.

```python
from comms.registry import register_source
from comms.models import Seed, ArtistBundle, Artist
from comms.sources.base import Source, SourceContext


@register_source("example")
class ExampleSource(Source):
    site = "example"

    async def discover(self, ctx: SourceContext, limit: int):
        for handle in await self._list_public_handles(limit):
            yield Seed(site=self.site, handle=handle, source="example:discover")

    async def fetch(self, ctx: SourceContext, seed: Seed) -> ArtistBundle:
        payload = await self._get_profile(seed.handle)
        return ArtistBundle(artist=..., offerings=..., works=..., price_points=...)
```

Rules:

1. Use `ctx.budget.check()` and `ctx.budget.record_request()` around requests.
2. Use an `AdaptiveRateLimiter`; never use unbounded concurrency.
3. Respect robots.txt. If a page is disallowed, do not fetch it.
4. Normalize handles, IDs, prices, currencies, and timestamps in the source.
5. Use stable IDs from `comms.ids`; never use mutable handles as database keys.
6. Return `ArtistNotFound` for a confirmed missing profile so the frontier marks
   it without deleting the historical record.
7. Raise `SourceError` for transient failures; the pipeline backs off.
8. Keep raw payloads optional. Normalize into models first.

## Config

Add a section to `AppConfig.sources` and `config/comms.example.toml`. A source
should be disabled by default if it is unstable or requires credentials.

## Tests

Save a small HTML/JSON fixture and test the parser without network access.
Do not add tests that hit live sites.
