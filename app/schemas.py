from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict

# Rule Schemas
class RuleCreate(BaseModel):
    keyword: str
    dm_message: str

class RuleResponse(BaseModel):
    rule_id: str
    keyword: str
    dm_message: str

# Stats Schema
class StatsResponse(BaseModel):
    sent: int
    failed: int
    queued: int
    duplicates_blocked: int

# Webhook Payload Schemas
class UserFrom(BaseModel):
    user_id: str
    username: Optional[str] = None

class CommentData(BaseModel):
    comment_id: str
    post_id: Optional[str] = None
    text: Optional[str] = ""
    created_at: Optional[str] = None
    from_user: Optional[UserFrom] = Field(default=None, alias="from")

    model_config = ConfigDict(populate_by_name=True)

class WebhookPayload(BaseModel):
    event_id: str
    event_type: str
    sent_at: Optional[str] = None
    data: Dict[str, Any]
