import uuid
from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models import Rule
from app.schemas import RuleCreate, RuleResponse
from typing import List

router = APIRouter(tags=["Rules"])

@router.get("/rules", response_model=List[RuleResponse], status_code=status.HTTP_200_OK)
async def list_rules(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Rule))
    rules = result.scalars().all()
    return [RuleResponse(rule_id=r.rule_id, keyword=r.keyword, dm_message=r.dm_message) for r in rules]

@router.post("/rules", response_model=RuleResponse, status_code=status.HTTP_201_CREATED)
async def create_rule(rule_in: RuleCreate, db: AsyncSession = Depends(get_db)):
    keyword = rule_in.keyword.lower().strip()

    # Prevent duplicate-keyword rules accumulating across test runs
    existing = await db.execute(select(Rule).where(Rule.keyword == keyword).limit(1))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Rule with keyword '{keyword}' already exists."
        )

    rule_id = f"rule_{uuid.uuid4().hex[:12]}"
    new_rule = Rule(
        rule_id=rule_id,
        keyword=keyword,
        dm_message=rule_in.dm_message
    )
    db.add(new_rule)
    await db.commit()
    await db.refresh(new_rule)

    return RuleResponse(
        rule_id=new_rule.rule_id,
        keyword=new_rule.keyword,
        dm_message=new_rule.dm_message
    )
