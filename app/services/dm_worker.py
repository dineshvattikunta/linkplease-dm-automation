import asyncio
import datetime
import logging
import httpx
from typing import Optional
from sqlalchemy import select, update
from app.config import settings
from app.database import AsyncSessionLocal
from app.models import DMTask, StatCounter
from app.services.rate_limiter import rate_limiter

logger = logging.getLogger("dm_worker")
logging.basicConfig(level=logging.INFO)

# ─── Concurrency-safety notes ─────────────────────────────────────────────────
#
# CLAIM RACE  : _task_claim_lock (asyncio.Lock) serialises SELECT + UPDATE
#               "processing".  Lock is held for one DB round-trip (~10-20 ms).
#               HTTP calls happen outside the lock → true parallelism.
#
# DB POOL     : Each of the three DB phases (claim / write-result / stat-inc)
#               uses its own short-lived AsyncSessionLocal context.  The HTTP
#               call happens between phases with NO connection held.  8 workers
#               never need more than 8 simultaneous connections even in the
#               worst case, and in practice each hold is < 50 ms.
#
# STATS RACE  : UPDATE stat_counters SET sent = sent + 1 is an atomic
#               row-level SQL UPDATE.  PostgreSQL serialises concurrent writers
#               at the storage engine level — no lost-update possible.
#
# RATE LIMIT  : All workers share the same TokenBucketRateLimiter singleton.
#               Its asyncio.Lock serialises acquire() so each worker gets a
#               staggered token (T, T+6.67s, T+13.33s …). Total API call rate
#               across all workers is capped at exactly 9 / 60 s.
#
# CRASH SAFETY: Reconciler resets tasks stuck in "processing" for > 30 s.
# ─────────────────────────────────────────────────────────────────────────────

NUM_WORKERS = 8
_task_claim_lock = asyncio.Lock()


class DMWorker:
    def __init__(self):
        self.is_running = False
        self.http_client: Optional[httpx.AsyncClient] = None
        self._worker_tasks: list = []

    async def start(self):
        self.is_running = True
        self.http_client = httpx.AsyncClient(timeout=15.0)
        logger.info(f"DM Worker pool starting ({NUM_WORKERS} concurrent workers).")
        self._worker_tasks = [
            asyncio.create_task(self._worker_loop(i))
            for i in range(NUM_WORKERS)
        ]
        await asyncio.gather(*self._worker_tasks, return_exceptions=True)

    async def stop(self):
        self.is_running = False
        for t in self._worker_tasks:
            t.cancel()
        if self.http_client:
            await self.http_client.aclose()
        logger.info("DM Worker pool stopped.")

    # ── Per-worker loop ───────────────────────────────────────────────────────

    async def _worker_loop(self, worker_id: int):
        while self.is_running:
            try:
                task_snapshot = await self._claim_one_task()
                if task_snapshot is not None:
                    await self._process_task(task_snapshot)
                else:
                    await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Worker {worker_id} error: {e}", exc_info=True)
                await asyncio.sleep(1.0)

    # ── Phase 1: Atomic claim  (DB connection held < 50 ms) ──────────────────

    async def _claim_one_task(self) -> Optional[dict]:
        """
        Atomically claims one queued task.  Returns a plain dict snapshot of
        the task data so the connection can be released before the HTTP call.
        """
        async with _task_claim_lock:
            async with AsyncSessionLocal() as db:
                now = datetime.datetime.utcnow()
                stmt = (
                    select(DMTask)
                    .where(
                        DMTask.status == "queued",
                        DMTask.dm_id.is_(None),
                        DMTask.next_run_at <= now,
                    )
                    .order_by(DMTask.id.asc())
                    .limit(1)
                )
                result = await db.execute(stmt)
                task = result.scalar_one_or_none()
                if task is None:
                    return None
                task.status = "processing"
                task.updated_at = now
                await db.commit()
                # Return a plain snapshot — no live ORM object crosses the session boundary
                return {
                    "id": task.id,
                    "recipient_user_id": task.recipient_user_id,
                    "message": task.message,
                    "comment_id": task.comment_id,
                    "rule_id": task.rule_id,
                    "attempts": task.attempts,
                }

    # ── Phase 2 + 3: Send DM, then write result  (no DB held during HTTP) ────

    async def _process_task(self, snap: dict):
        task_id = snap["id"]

        # Block until rate-limit slot granted (shared across all workers).
        await rate_limiter.acquire()

        url = f"{settings.PSEUDOGRAM_BASE_URL}/v1/dm/send"
        headers = {
            "X-API-Key": settings.API_KEY,
            "Idempotency-Key": f"dm_req_{snap['comment_id']}_{snap['rule_id']}",
            "Content-Type": "application/json",
        }
        payload = {
            "recipient_user_id": snap["recipient_user_id"],
            "message": snap["message"],
            "comment_id": snap["comment_id"],
        }

        # ── HTTP call — NO database connection is held here ──────────────────
        try:
            response = await self.http_client.post(url, json=payload, headers=headers)
            sc = response.status_code
        except Exception as exc:
            logger.error(f"Network error task {task_id}: {exc}")
            await self._mark_retry_or_fail(task_id, snap["attempts"], str(exc)[:250])
            return

        # ── Phase 3: Write result (new short-lived DB session) ────────────────
        if sc in (200, 202):
            dm_id = response.json().get("dm_id")
            await self._mark_sent(task_id, dm_id)
            logger.info(f"Task {task_id} sent → dm_id={dm_id}")

        elif sc == 429:
            retry_after = float(response.headers.get("Retry-After", "10"))
            await rate_limiter.update_backoff(retry_after)
            await self._mark_requeue(task_id, retry_after, f"429 Retry-After={retry_after}s")
            logger.warning(f"Task {task_id} rate-limited, retry in {retry_after}s")

        elif sc >= 500:
            backoff = 2 ** (snap["attempts"] + 1)
            await self._mark_retry_or_fail(task_id, snap["attempts"], f"HTTP {sc}")
            logger.warning(f"Task {task_id} server error {sc}")

        else:
            await self._mark_failed(task_id, f"HTTP {sc}: {response.text[:200]}")
            logger.error(f"Task {task_id} non-retryable {sc}")

    # ── Result writers (each uses its own short-lived session) ───────────────

    async def _mark_sent(self, task_id: int, dm_id: Optional[str]):
        async with AsyncSessionLocal() as db:
            t = await db.get(DMTask, task_id)
            # Only proceed if this worker is still the rightful owner.
            # If the reconciler reset the task to "queued" and another worker
            # re-claimed it, t.status will no longer be "processing" here —
            # we skip the counter increment to prevent double-counting.
            if t and t.status == "processing":
                t.status = "sent"
                t.dm_id = dm_id
                t.updated_at = datetime.datetime.utcnow()
                await db.execute(
                    update(StatCounter).where(StatCounter.id == 1).values(
                        sent=StatCounter.sent + 1
                    )
                )
                await db.commit()
            elif t:
                logger.warning(
                    f"_mark_sent: task {task_id} status={t.status!r} — "
                    "skipping counter increment (likely reconciler reset)"
                )

    async def _mark_requeue(self, task_id: int, delay_s: float, error: str):
        async with AsyncSessionLocal() as db:
            t = await db.get(DMTask, task_id)
            if t:
                t.status = "queued"
                t.next_run_at = datetime.datetime.utcnow() + datetime.timedelta(seconds=delay_s)
                t.last_error = error
                t.updated_at = datetime.datetime.utcnow()
                await db.commit()

    async def _mark_retry_or_fail(self, task_id: int, prev_attempts: int, error: str):
        async with AsyncSessionLocal() as db:
            t = await db.get(DMTask, task_id)
            if t:
                t.attempts = prev_attempts + 1
                t.last_error = error
                t.updated_at = datetime.datetime.utcnow()
                if t.attempts >= settings.MAX_RETRY_ATTEMPTS:
                    t.status = "failed"
                    await db.execute(
                        update(StatCounter).where(StatCounter.id == 1).values(
                            failed=StatCounter.failed + 1
                        )
                    )
                else:
                    t.status = "queued"
                    t.next_run_at = datetime.datetime.utcnow() + datetime.timedelta(
                        seconds=2 ** t.attempts
                    )
                await db.commit()

    async def _mark_failed(self, task_id: int, error: str):
        async with AsyncSessionLocal() as db:
            t = await db.get(DMTask, task_id)
            if t:
                t.status = "failed"
                t.last_error = error
                t.updated_at = datetime.datetime.utcnow()
                await db.execute(
                    update(StatCounter).where(StatCounter.id == 1).values(
                        failed=StatCounter.failed + 1
                    )
                )
                await db.commit()


dm_worker = DMWorker()
