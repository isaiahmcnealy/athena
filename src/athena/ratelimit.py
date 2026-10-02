"""A per-client request budget held in one web process; it is not shared across processes."""

import time
from collections import OrderedDict
from collections.abc import Callable


class RateLimiter:
    """Token bucket: a client may burst up to one minute's budget, then is refilled steadily."""

    def __init__(
        self,
        per_minute: int,
        *,
        max_clients: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ):
        if per_minute < 1:
            raise ValueError("per_minute must be at least 1")
        self.capacity = float(per_minute)
        self.refill_per_second = per_minute / 60
        self.max_clients = max_clients
        self.clock = clock
        self.clients: OrderedDict[str, tuple[float, float]] = OrderedDict()

    def retry_after(self, client: str) -> float:
        """Spend one request. Return 0 when allowed, otherwise seconds until one is available."""
        now = self.clock()
        tokens, seen = self.clients.pop(client, (self.capacity, now))
        tokens = min(self.capacity, tokens + (now - seen) * self.refill_per_second)
        allowed = tokens >= 1
        self.clients[client] = (tokens - 1 if allowed else tokens, now)
        if len(self.clients) > self.max_clients:
            # Bound memory. The least recently seen client starts over with a full budget.
            self.clients.popitem(last=False)
        return 0.0 if allowed else (1 - tokens) / self.refill_per_second
