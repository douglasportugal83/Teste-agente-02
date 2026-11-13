"""Limitador de tentativas de login em memória (por processo).

Suficiente para um único worker; em produção com vários processos, mover para Redis.
"""

import threading
import time
from collections import defaultdict, deque


class FailureLimiter:
    def __init__(self, max_failures: int, window_seconds: int) -> None:
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        entries = self._failures[key]
        while entries and now - entries[0] > self.window_seconds:
            entries.popleft()
        return entries

    def is_blocked(self, key: str) -> bool:
        with self._lock:
            blocked = len(self._prune(key, time.monotonic())) >= self.max_failures
            if not self._failures[key]:
                del self._failures[key]
            return blocked

    def register_failure(self, key: str) -> None:
        with self._lock:
            now = time.monotonic()
            self._prune(key, now).append(now)

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._failures.clear()
            else:
                self._failures.pop(key, None)
