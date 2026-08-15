import uuid
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models import Rule
from app.schemas import RuleCreate, RuleResponse

router = APIRouter(tags=["Rules"])

@router.post("/rules", response_model=RuleResponse, status_code=status.HTTP_201_CREATED)
async def create_rule(rule_in: RuleCreate, db: AsyncSession = Depends(get_db)):
    rule_id = f"rule_{uuid.uuid4().hex[:12]}"
    
    # Store lowercased keyword for case-insensitive matching
    new_rule = Rule(
        rule_id=rule_id,
        keyword=rule_in.keyword.lower().strip(),
        dm_message=rule_in.dm_message
    )
    db.add(new_rule)
    await db.commit()
    await db.refresh(new_rule)

    return RuleResponse(
        rule_id=new_rule.rule_id,
        keyword=rule_in.keyword,  # Return original keyword string
        dm_message=new_rule.dm_message
    )
