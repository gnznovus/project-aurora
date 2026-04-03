from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque
from typing import Iterable

from redis import Redis


class QueueAdapter(ABC):
    @abstractmethod
    def enqueue(self, job_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def pop_many(self, limit: int) -> list[str]:
        raise NotImplementedError


class InMemoryQueue(QueueAdapter):
    def __init__(self) -> None:
        self._queue: deque[str] = deque()

    def enqueue(self, job_id: str) -> None:
        self._queue.append(job_id)

    def pop_many(self, limit: int) -> list[str]:
        items: list[str] = []
        while self._queue and len(items) < limit:
            items.append(self._queue.popleft())
        return items


class RedisQueue(QueueAdapter):
    def __init__(self, redis_url: str, queue_name: str) -> None:
        self._redis = Redis.from_url(redis_url, decode_responses=True)
        self._queue_name = queue_name

    def enqueue(self, job_id: str) -> None:
        self._redis.rpush(self._queue_name, job_id)

    def enqueue_many(self, job_ids: Iterable[str]) -> None:
        if not job_ids:
            return
        self._redis.rpush(self._queue_name, *job_ids)

    def pop_many(self, limit: int) -> list[str]:
        items: list[str] = []
        for _ in range(limit):
            value = self._redis.lpop(self._queue_name)
            if value is None:
                break
            items.append(value)
        return items

