import asyncio
import datetime
import logging
import httpx
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from app.config import settings
from app.database import AsyncSessionLocal
from app.models import DMTask, UserRuleDispatch, StatCounter
from app.services.rate_limiter import rate_limiter

logger = logging.getLogger("dm_worker")
logging.basicConfig(level=logging.INFO)

class DMWorker:
    def __init__(self):
        self.is_running = False
        self.http_client = httpx.AsyncClient(timeout=15.0)

    async def start(self):
        self.is_running = True
        logger.info("DM Worker started.")
        while self.is_running:
            try:
                await self.process_pending_tasks()
            except Exception as e:
                logger.error(f"Error in DM worker loop: {e}", exc_info=True)
            await asyncio.sleep(settings.WORKER_POLL_INTERVAL_SECONDS)

    async def stop(self):
        self.is_running = False
        await self.http_client.aclose()
        logger.info("DM Worker stopped.")

    async def process_pending_tasks(self):
        async with AsyncSessionLocal() as db:
            now = datetime.datetime.utcnow()
            # Fetch tasks ready for processing
            stmt = (
                select(DMTask)
                .where(
                    DMTask.status == "queued",
                    DMTask.dm_id.is_(None),  # Not yet accepted by API
                    DMTask.next_run_at <= now
                )
                .order_by(DMTask.id.asc())
                .limit(5)
            )
            result = await db.execute(stmt)
            tasks = result.scalars().all()

            if not tasks:
                return

            for task in tasks:
                await self.process_single_task(db, task)

    async def process_single_task(self, db, task: DMTask):
        # Note: Deduplication is already enforced at the webhook layer via
        # the UserRuleDispatch UNIQUE(user_id, rule_id) constraint. Only one
        # DM task per (user, rule) pair will ever be created.

        # 1. Acquire Rate Limiter slot
        await rate_limiter.acquire()

        # 3. Call Mock API
        url = f"{settings.PSEUDOGRAM_BASE_URL}/v1/dm/send"
        headers = {
            "X-API-Key": settings.API_KEY,
            "Idempotency-Key": f"dm_req_{task.comment_id}_{task.rule_id}",
            "Content-Type": "application/json"
        }
        payload = {
            "recipient_user_id": task.recipient_user_id,
            "message": task.message,
            "comment_id": task.comment_id
        }

        try:
            response = await self.http_client.post(url, json=payload, headers=headers)
            status_code = response.status_code

            if status_code in (200, 202):
                data = response.json()
                dm_id = data.get("dm_id")
                task.dm_id = dm_id
                task.status = "sent"
                task.updated_at = datetime.datetime.utcnow()
                await self._increment_stat(db, sent=1)
                await db.commit()
                logger.info(f"DM sent for comment {task.comment_id}, dm_id: {dm_id}")


            elif status_code == 429:
                retry_after = 10.0
                try:
                    retry_after = float(response.headers.get("Retry-After", "10"))
                except ValueError:
                    pass
                
                await rate_limiter.update_backoff(retry_after)
                task.next_run_at = datetime.datetime.utcnow() + datetime.timedelta(seconds=retry_after)
                task.last_error = f"429 Rate Limited (Retry-After: {retry_after}s)"
                task.updated_at = datetime.datetime.utcnow()
                await db.commit()
                logger.warning(f"Rate limited on task {task.id}. Pausing for {retry_after}s.")

            elif status_code >= 500:
                task.attempts += 1
                task.last_error = f"HTTP {status_code}: {response.text[:200]}"
                task.updated_at = datetime.datetime.utcnow()

                if task.attempts >= settings.MAX_RETRY_ATTEMPTS:
                    task.status = "failed"
                    await self._increment_stat(db, failed=1)
                    logger.error(f"Task {task.id} failed after {task.attempts} attempts.")
                else:
                    backoff = 2 ** task.attempts
                    task.next_run_at = datetime.datetime.utcnow() + datetime.timedelta(seconds=backoff)
                    logger.warning(f"Task {task.id} got {status_code}. Retrying in {backoff}s.")
                await db.commit()

            else:  # 400 or other non-retryable error
                task.status = "failed"
                task.last_error = f"HTTP {status_code}: {response.text[:200]}"
                task.updated_at = datetime.datetime.utcnow()
                await self._increment_stat(db, failed=1)
                await db.commit()
                logger.error(f"Task {task.id} non-retryable failure {status_code}: {response.text}")

        except Exception as e:
            await db.rollback()
            logger.error(f"Network exception on task {task.id}: {e}")
            try:
                async with AsyncSessionLocal() as fresh_db:
                    t = await fresh_db.get(DMTask, task.id)
                    if t and t.status == "queued":
                        t.attempts += 1
                        t.last_error = str(e)[:250]
                        t.updated_at = datetime.datetime.utcnow()
                        if t.attempts >= settings.MAX_RETRY_ATTEMPTS:
                            t.status = "failed"
                            await self._increment_stat(fresh_db, failed=1)
                        else:
                            backoff = 2 ** t.attempts
                            t.next_run_at = datetime.datetime.utcnow() + datetime.timedelta(seconds=backoff)
                        await fresh_db.commit()
            except Exception as inner_e:
                logger.error(f"Error handling task exception recovery: {inner_e}")


    async def _increment_stat(self, db, sent: int = 0, failed: int = 0, queued: int = 0, duplicates_blocked: int = 0):
        await db.execute(
            update(StatCounter).where(StatCounter.id == 1).values(
                sent=StatCounter.sent + sent,
                failed=StatCounter.failed + failed,
                queued=StatCounter.queued + queued,
                duplicates_blocked=StatCounter.duplicates_blocked + duplicates_blocked
            )
        )

dm_worker = DMWorker()

