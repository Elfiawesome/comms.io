from __future__ import annotations

from collections.abc import Callable
from importlib import metadata
from typing import TypeVar

from comms.config import AppConfig
from comms.sources.base import Source

T = TypeVar("T", bound=type[Source])
_SOURCES: dict[str, type[Source]] = {}
_LOADED = False


def register_source(name: str) -> Callable[[T], T]:
    def decorator(cls: T) -> T:
        _SOURCES[name] = cls
        return cls

    return decorator


def _load_builtins() -> None:
    global _LOADED
    if _LOADED:
        return
    import importlib

    for module_name in ("comms.sources.skeb", "comms.sources.crepe"):
        importlib.import_module(module_name)

    try:
        entry_points = metadata.entry_points(group="comms.sources")
    except TypeError:  # pragma: no cover - Python 3.10 fallback
        entry_points = metadata.entry_points().get("comms.sources", [])  # type: ignore[attr-defined]
    for entry_point in entry_points:
        try:
            entry_point.load()
        except Exception:
            # A broken third-party plugin should not prevent the built-ins from running.
            import logging

            logging.getLogger("comms.registry").exception(
                "Failed to load source plugin %s", entry_point.name
            )
    _LOADED = True


def available_sources() -> list[str]:
    _load_builtins()
    return sorted(_SOURCES)


def create_source(name: str, config: AppConfig) -> Source:
    _load_builtins()
    if name not in _SOURCES:
        raise KeyError(f"Unknown source '{name}'. Available: {', '.join(available_sources())}")
    options = getattr(config.sources, name, None)
    if options is None:
        raise KeyError(f"No config section for source '{name}'")
    return _SOURCES[name](options, config)
