import asyncio
import time
from app.config import settings


class TokenBucketRateLimiter:
    """
    Token bucket rate limiter that enforces a fixed minimum interval between
    requests (= window_seconds / max_requests). Unlike a sliding window, this
    eliminates burst-then-idle behaviour and produces a smooth, steady throughput
    at exactly max_requests per window_seconds — safe under Pseudogram's rolling
    10-req/60s cap.
    """

    def __init__(self, max_requests: int = None, window_seconds: float = None):
        max_requests = max_requests or settings.RATE_LIMIT_MAX_REQUESTS
        window_seconds = window_seconds or float(settings.RATE_LIMIT_WINDOW_SECONDS)
        # Minimum seconds between successive requests
        self.interval = window_seconds / max_requests
        self._next_allowed = 0.0
        self._lock = asyncio.Lock()

        # Forced-backoff support (for 429 Retry-After)
        self._forced_backoff_until = 0.0

    async def acquire(self):
        """Block until the next request slot is available."""
        async with self._lock:
            now = time.monotonic()

            # Respect any forced backoff from a 429 response
            if now < self._forced_backoff_until:
                wait = self._forced_backoff_until - now
                self._next_allowed = self._forced_backoff_until + self.interval
            else:
                if now >= self._next_allowed:
                    wait = 0.0
                    self._next_allowed = now + self.interval
                else:
                    wait = self._next_allowed - now
                    self._next_allowed += self.interval

        if wait > 0:
            await asyncio.sleep(wait)

    async def update_backoff(self, retry_after_seconds: float):
        """Called when the mock API returns 429 with a Retry-After header."""
        async with self._lock:
            deadline = time.monotonic() + retry_after_seconds
            if deadline > self._forced_backoff_until:
                self._forced_backoff_until = deadline


rate_limiter = TokenBucketRateLimiter()
