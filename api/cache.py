"""A tiny in-process TTL cache for warehouse results. The marts change at most daily, and BigQuery bills per
query, so each endpoint + arguments is computed once per TTL. Errors are never cached."""

import threading
import time
from collections.abc import Callable, Hashable
from typing import Any

HOUR = 3600


class TTLCache:
    def __init__(self, max_items: int = 512):
        self._data: dict[Hashable, tuple[float, Any]] = {}
        self._lock = threading.Lock()
        self.max_items = max_items

    def get_or_compute(self, key: Hashable, ttl: float, compute: Callable[[], Any]) -> Any:
        now = time.monotonic()
        with self._lock:
            hit = self._data.get(key)
            if hit and hit[0] > now:
                return hit[1]
        value = compute()  # raises → nothing stored
        with self._lock:
            if len(self._data) >= self.max_items:
                self._data = {k: v for k, v in self._data.items() if v[0] > now}
                if len(self._data) >= self.max_items:
                    self._data.clear()
            self._data[key] = (now + ttl, value)
        return value

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


cache = TTLCache()
