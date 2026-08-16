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

# ─── Concurrency-safety proof ─────────────────────────────────────────────────
#
# CLAIM RACE: Multiple workers could SELECT the same "queued" task simultaneously.
# Fix: _task_claim_lock (asyncio.Lock) serialises the SELECT + UPDATE "processing"
# pair. Lock is released *before* the HTTP call, so workers run API calls in
# parallel while claiming stays serial. Lock hold time: ~5–20 ms (one DB round
# trip). Zero risk of deadlock because the lock is never held across an await
# that could itself block on the lock.
#
# STATS RACE: Multiple workers complete near-simultaneously and call
# UPDATE stat_counters SET sent = sent + 1. This is a PostgreSQL atomic
# row-level UPDATE — the DB engine serialises concurrent writers on the row;
# no lost-update is possible.
#
# RATE LIMIT RACE: Token bucket uses its own asyncio.Lock (_lock). Each
# acquire() atomically reads + advances _next_allowed before releasing. Workers
# that call acquire() concurrently get staggered tokens (T=0, T+6.67s, T+13.33s
# …), guaranteeing exactly 9 API calls per 60 s across all workers combined —
# the hard Pseudogram ceiling is never breached regardless of worker count.
#
# STUCK-PROCESSING RECOVERY: If a worker crashes between "processing" and "sent",
# the reconciler resets tasks stuck in "processing" for > 30 s back to "queued".
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
        # Block until all workers exit (or are cancelled at shutdown)
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
                task_id = await self._claim_one_task()
                if task_id is not None:
                    await self._process_task(task_id)
                else:
                    # No tasks ready — back off briefly before polling again
                    await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Worker {worker_id} unhandled error: {e}", exc_info=True)
                await asyncio.sleep(1.0)

    # ── Atomic task claim ─────────────────────────────────────────────────────

    async def _claim_one_task(self) -> Optional[int]:
        """
        Atomically select the oldest queued task and mark it 'processing'.
        _task_claim_lock ensures only one coroutine executes the
        SELECT + UPDATE pair at a time, preventing duplicate claims.
        Lock is released before the HTTP call so workers remain concurrent.
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
                return task.id

    # ── Task processing (runs concurrently across workers) ────────────────────

    async def _process_task(self, task_id: int):
        # Block here until the shared token bucket grants a slot.
        # All 8 workers share the same rate_limiter instance, so the total
        # API call rate across all workers is capped at 9 / 60 s.
        await rate_limiter.acquire()

        async with AsyncSessionLocal() as db:
            task = await db.get(DMTask, task_id)
            if task is None or task.status != "processing":
                # Already handled (e.g. by reconciler reset) — skip silently
                return

            url = f"{settings.PSEUDOGRAM_BASE_URL}/v1/dm/send"
            headers = {
                "X-API-Key": settings.API_KEY,
                "Idempotency-Key": f"dm_req_{task.comment_id}_{task.rule_id}",
                "Content-Type": "application/json",
            }
            payload = {
                "recipient_user_id": task.recipient_user_id,
                "message": task.message,
                "comment_id": task.comment_id,
            }

            try:
                response = await self.http_client.post(url, json=payload, headers=headers)
                sc = response.status_code

                if sc in (200, 202):
                    dm_id = response.json().get("dm_id")
                    task.dm_id = dm_id
                    task.status = "sent"
                    task.updated_at = datetime.datetime.utcnow()
                    await self._inc(db, sent=1)
                    await db.commit()
                    logger.info(f"Task {task.id} sent → dm_id={dm_id}")

                elif sc == 429:
                    retry_after = float(response.headers.get("Retry-After", "10"))
                    await rate_limiter.update_backoff(retry_after)
                    task.status = "queued"
                    task.next_run_at = datetime.datetime.utcnow() + datetime.timedelta(seconds=retry_after)
                    task.last_error = f"429 Retry-After={retry_after}s"
                    task.updated_at = datetime.datetime.utcnow()
                    await db.commit()
                    logger.warning(f"Task {task.id} rate-limited, retry in {retry_after}s")

                elif sc >= 500:
                    task.attempts += 1
                    task.last_error = f"HTTP {sc}: {response.text[:200]}"
                    task.updated_at = datetime.datetime.utcnow()
                    if task.attempts >= settings.MAX_RETRY_ATTEMPTS:
                        task.status = "failed"
                        await self._inc(db, failed=1)
                        logger.error(f"Task {task.id} permanently failed after {task.attempts} attempts")
                    else:
                        task.status = "queued"
                        task.next_run_at = datetime.datetime.utcnow() + datetime.timedelta(seconds=2 ** task.attempts)
                        logger.warning(f"Task {task.id} server error {sc}, retrying")
                    await db.commit()

                else:
                    task.status = "failed"
                    task.last_error = f"HTTP {sc}: {response.text[:200]}"
                    task.updated_at = datetime.datetime.utcnow()
                    await self._inc(db, failed=1)
                    await db.commit()
                    logger.error(f"Task {task.id} non-retryable {sc}")

            except Exception as exc:
                await db.rollback()
                logger.error(f"Network error task {task_id}: {exc}")
                try:
                    async with AsyncSessionLocal() as rdb:
                        t = await rdb.get(DMTask, task_id)
                        if t and t.status == "processing":
                            t.attempts += 1
                            t.last_error = str(exc)[:250]
                            t.updated_at = datetime.datetime.utcnow()
                            if t.attempts >= settings.MAX_RETRY_ATTEMPTS:
                                t.status = "failed"
                                await self._inc(rdb, failed=1)
                            else:
                                t.status = "queued"
                                t.next_run_at = datetime.datetime.utcnow() + datetime.timedelta(seconds=2 ** t.attempts)
                            await rdb.commit()
                except Exception as inner:
                    logger.error(f"Recovery failed for task {task_id}: {inner}")

    # ── Atomic stat increment (safe under concurrent writers) ─────────────────

    async def _inc(self, db, sent: int = 0, failed: int = 0):
        """
        PostgreSQL atomic UPDATE: concurrent writers on the same row are
        serialised by the DB engine at the row level — no lost-update possible.
        """
        await db.execute(
            update(StatCounter).where(StatCounter.id == 1).values(
                sent=StatCounter.sent + sent,
                failed=StatCounter.failed + failed,
            )
        )


dm_worker = DMWorker()
