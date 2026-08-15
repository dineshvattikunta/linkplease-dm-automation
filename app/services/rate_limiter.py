import asyncio
import time
from collections import deque
from app.config import settings

class SlidingWindowRateLimiter:
    """
    Sliding window rate limiter that strictly guarantees max_requests 
    per window_seconds across all async tasks.
    """
    def __init__(self, max_requests: int = None, window_seconds: float = None):
        self.max_requests = max_requests or settings.RATE_LIMIT_MAX_REQUESTS
        self.window_seconds = window_seconds or float(settings.RATE_LIMIT_WINDOW_SECONDS)
        self.timestamps = deque()
        self.lock = asyncio.Lock()
        self.forced_backoff_until = 0.0

    async def acquire(self):
        """
        Blocks asynchronously until a request slot is available in the rolling window.
        """
        while True:
            async with self.lock:
                now = time.time()

                # If server returned 429 with Retry-After, respect forced backoff
                if now < self.forced_backoff_until:
                    wait_time = self.forced_backoff_until - now + 0.1
                else:
                    # Remove timestamps outside rolling window
                    while self.timestamps and self.timestamps[0] <= now - self.window_seconds:
                        self.timestamps.popleft()

                    if len(self.timestamps) < self.max_requests:
                        self.timestamps.append(now)
                        return
                    else:
                        # Time until the oldest timestamp falls outside the rolling window
                        oldest = self.timestamps[0]
                        wait_time = (oldest + self.window_seconds) - now + 0.05

            await asyncio.sleep(max(wait_time, 0.05))

    async def update_backoff(self, retry_after_seconds: float):
        """
        Called when mock API returns 429 Rate Limited with a Retry-After header.
        """
        async with self.lock:
            self.forced_backoff_until = max(self.forced_backoff_until, time.time() + retry_after_seconds)

rate_limiter = SlidingWindowRateLimiter()
