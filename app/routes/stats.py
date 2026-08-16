from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update, delete
from app.database import get_db
from app.models import StatCounter, DMTask, WebhookEvent, UserRuleDispatch
from app.schemas import StatsResponse

router = APIRouter(tags=["Stats"])

@router.get("/stats", response_model=StatsResponse, status_code=status.HTTP_200_OK)
async def get_stats(db: AsyncSession = Depends(get_db)):
    # Fetch global stat counters
    stat = await db.get(StatCounter, 1)
    
    sent = stat.sent if stat else 0
    failed = stat.failed if stat else 0
    duplicates_blocked = stat.duplicates_blocked if stat else 0

    # Calculate live queued count directly from DMTask table
    queued_stmt = select(func.count(DMTask.id)).where(DMTask.status == "queued")
    queued_result = await db.execute(queued_stmt)
    queued = queued_result.scalar() or 0

    return StatsResponse(
        sent=sent,
        failed=failed,
        queued=queued,
        duplicates_blocked=duplicates_blocked
    )

@router.post("/reset", status_code=status.HTTP_200_OK)
async def reset_database(db: AsyncSession = Depends(get_db)):
    """
    Clears ALL records (rules, DM tasks, webhook events, dispatches)
    and resets stat counters to 0. Use before each test run.
    """
    from app.models import Rule
    await db.execute(delete(DMTask))
    await db.execute(delete(UserRuleDispatch))
    await db.execute(delete(WebhookEvent))
    await db.execute(delete(Rule))
    await db.execute(
        update(StatCounter).where(StatCounter.id == 1).values(
            sent=0, failed=0, queued=0, duplicates_blocked=0
        )
    )
    await db.commit()
    return {"status": "ok", "message": "Database and stats reset clean"}

