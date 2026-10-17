from collections.abc import Hashable
from typing import Any

from cachetools import TTLCache


class ReferenceDataCache:
    """Small process-local TTL cache for low-change reference data only."""

    def __init__(self, ttl_seconds: int, maxsize: int = 128) -> None:
        self._cache: TTLCache[Hashable, Any] | None = (
            TTLCache(maxsize=maxsize, ttl=ttl_seconds) if ttl_seconds > 0 else None
        )

    def get(self, key: Hashable) -> Any | None:
        if self._cache is None:
            return None
        return self._cache.get(key)

    def set(self, key: Hashable, value: Any) -> None:
        if self._cache is not None:
            self._cache[key] = value
