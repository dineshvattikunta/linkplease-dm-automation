import asyncio
import datetime
import logging
import httpx
from sqlalchemy import select, update
from app.config import settings
from app.database import AsyncSessionLocal
from app.models import DMTask, StatCounter

logger = logging.getLogger("reconciler")

class ReconcilerService:
    def __init__(self):
        self.is_running = False
        self.http_client = httpx.AsyncClient(timeout=10.0)

    async def start(self):
        self.is_running = True
        logger.info("Reconciler service started.")
        while self.is_running:
            try:
                await self.reconcile_pending_dms()
            except Exception as e:
                logger.error(f"Error in reconciler loop: {e}", exc_info=True)
            await asyncio.sleep(settings.RECONCILER_INTERVAL_SECONDS)

    async def stop(self):
        self.is_running = False
        await self.http_client.aclose()
        logger.info("Reconciler service stopped.")

    async def reconcile_pending_dms(self):
        async with AsyncSessionLocal() as db:
            stmt = (
                select(DMTask)
                .where(
                    DMTask.status == "queued",
                    DMTask.dm_id.isnot(None)
                )
                .limit(10)
            )
            result = await db.execute(stmt)
            tasks = result.scalars().all()

            if not tasks:
                return

            for task in tasks:
                await self.check_dm_status(db, task)

    async def check_dm_status(self, db, task: DMTask):
        url = f"{settings.PSEUDOGRAM_BASE_URL}/v1/dm/{task.dm_id}"
        headers = {"X-API-Key": settings.API_KEY}

        try:
            response = await self.http_client.get(url, headers=headers)
            if response.status_code == 200:
                data = response.json()
                mock_status = data.get("status")

                if mock_status == "delivered":
                    task.status = "sent"
                    task.updated_at = datetime.datetime.utcnow()
                    await self._increment_stat(db, sent=1)
                    await db.commit()
                    logger.info(f"DM {task.dm_id} (Task {task.id}) confirmed DELIVERED.")

                elif mock_status == "failed":
                    task.attempts += 1
                    task.updated_at = datetime.datetime.utcnow()

                    if task.attempts >= settings.MAX_RETRY_ATTEMPTS:
                        task.status = "failed"
                        await self._increment_stat(db, failed=1)
                        logger.error(f"DM {task.dm_id} (Task {task.id}) failed permanently after {task.attempts} attempts.")
                    else:
                        # Reset dm_id to trigger retry send in worker
                        task.dm_id = None
                        task.status = "queued"
                        backoff = 2 ** task.attempts
                        task.next_run_at = datetime.datetime.utcnow() + datetime.timedelta(seconds=backoff)
                        logger.warning(f"DM {task.dm_id} failed on remote API. Resetting for retry attempt {task.attempts}.")

                    await db.commit()

                # If status is still "queued", do nothing and check next cycle

        except Exception as e:
            logger.error(f"Exception checking DM status for {task.dm_id}: {e}")

    async def _increment_stat(self, db, sent: int = 0, failed: int = 0, queued: int = 0, duplicates_blocked: int = 0):
        await db.execute(
            update(StatCounter).where(StatCounter.id == 1).values(
                sent=StatCounter.sent + sent,
                failed=StatCounter.failed + failed,
                queued=StatCounter.queued + queued,
                duplicates_blocked=StatCounter.duplicates_blocked + duplicates_blocked
            )
        )

reconciler = ReconcilerService()

