from __future__ import annotations

import threading
from dataclasses import dataclass
from time import time


@dataclass
class _Bucket:
    window_start: int
    count: int


class LocalRateLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buckets: dict[str, _Bucket] = {}

    def check(self, key: str, max_attempts: int, window_seconds: int) -> bool:
        now = int(time())
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None or now - bucket.window_start >= window_seconds:
                bucket = _Bucket(window_start=now, count=0)
                self._buckets[key] = bucket
            bucket.count += 1
            return bucket.count <= max_attempts

    def reset(self, key: str) -> None:
        with self._lock:
            self._buckets.pop(key, None)
