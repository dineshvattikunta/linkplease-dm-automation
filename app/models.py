import datetime
from sqlalchemy import Column, String, Text, DateTime, Integer, UniqueConstraint, Index
from app.database import Base

class Rule(Base):
    __tablename__ = "rules"

    rule_id = Column(String(64), primary_key=True, index=True)
    keyword = Column(String(255), nullable=False, index=True)
    dm_message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    event_id = Column(String(64), primary_key=True, index=True)
    event_type = Column(String(64), nullable=False)
    comment_id = Column(String(64), nullable=True, index=True)
    post_id = Column(String(64), nullable=True)
    user_id = Column(String(64), nullable=True, index=True)
    payload = Column(Text, nullable=False)
    received_at = Column(DateTime, default=datetime.datetime.utcnow)

class UserRuleDispatch(Base):
    __tablename__ = "user_rule_dispatches"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), nullable=False, index=True)
    rule_id = Column(String(64), nullable=False, index=True)
    comment_id = Column(String(64), nullable=False)
    dispatched_at = Column(DateTime, default=datetime.datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "rule_id", name="uq_user_rule"),
    )

class DMTask(Base):
    __tablename__ = "dm_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dm_id = Column(String(64), nullable=True, index=True)
    comment_id = Column(String(64), nullable=False, index=True)
    recipient_user_id = Column(String(64), nullable=False, index=True)
    rule_id = Column(String(64), nullable=False, index=True)
    message = Column(Text, nullable=False)
    
    # Statuses: 'queued', 'sending', 'sent', 'failed', 'cancelled', 'blocked_duplicate'
    status = Column(String(32), nullable=False, default="queued", index=True)
    attempts = Column(Integer, default=0)
    last_error = Column(Text, nullable=True)
    next_run_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

class StatCounter(Base):
    __tablename__ = "stat_counters"

    id = Column(Integer, primary_key=True, default=1)
    sent = Column(Integer, default=0)
    failed = Column(Integer, default=0)
    queued = Column(Integer, default=0)
    duplicates_blocked = Column(Integer, default=0)
