import json
import logging
from fastapi import APIRouter, Request, Header, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from app.database import get_db
from app.security import verify_webhook_signature
from app.models import WebhookEvent, Rule, DMTask, UserRuleDispatch, StatCounter

logger = logging.getLogger("webhook")
router = APIRouter(tags=["Webhook"])

@router.post("/webhook", status_code=status.HTTP_200_OK)
async def handle_webhook(
    request: Request,
    x_pseudogram_signature: str = Header(None, alias="X-PseudoGram-Signature"),
    db: AsyncSession = Depends(get_db)
):
    raw_body = await request.body()

    # 1. Signature Verification (Part B requirement)
    if x_pseudogram_signature:
        if not verify_webhook_signature(raw_body, x_pseudogram_signature):
            logger.warning("Rejected webhook due to invalid signature.")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid HMAC SHA-256 signature"
            )
    else:
        logger.info("Webhook payload received without signature header.")





    # 2. Parse Payload
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception as e:
        logger.error(f"Failed to parse JSON body: {e}")
        return {"status": "ignored", "reason": "invalid_json"}

    event_id = payload.get("event_id")
    event_type = payload.get("event_type")
    data = payload.get("data", {})

    if not event_id or not event_type:
        return {"status": "ignored", "reason": "missing_event_id_or_type"}

    # 3. Deduplicate by event_id (~8% duplicate events)
    existing_evt = await db.get(WebhookEvent, event_id)
    if existing_evt:
        logger.info(f"Duplicate event_id received: {event_id}. Ignoring.")
        # Atomic SQL update for stat counter
        await db.execute(
            update(StatCounter).where(StatCounter.id == 1).values(
                duplicates_blocked=StatCounter.duplicates_blocked + 1
            )
        )
        await db.commit()
        return {"status": "ok", "message": "duplicate_event_ignored"}

    # Store Event in DB
    evt_record = WebhookEvent(
        event_id=event_id,
        event_type=event_type,
        comment_id=data.get("comment_id"),
        post_id=data.get("post_id"),
        user_id=data.get("from", {}).get("user_id") if isinstance(data.get("from"), dict) else None,
        payload=json.dumps(payload)
    )
    db.add(evt_record)

    try:
        # 4. Handle comment.deleted (Part C requirement)
        if event_type == "comment.deleted":
            comment_id = data.get("comment_id")
            if comment_id:
                # Cancel any pending un-sent DM task for this comment
                stmt = (
                    update(DMTask)
                    .where(DMTask.comment_id == comment_id, DMTask.status == "queued", DMTask.dm_id.is_(None))
                    .values(status="cancelled")
                )
                result = await db.execute(stmt)
                if result.rowcount > 0:
                    logger.info(f"Cancelled DM for deleted comment {comment_id}")
                    await db.execute(
                        update(StatCounter).where(StatCounter.id == 1).values(
                            duplicates_blocked=StatCounter.duplicates_blocked + result.rowcount
                        )
                    )

            await db.commit()
            return {"status": "ok", "message": "comment_deleted_processed"}

        # 5. Handle comment.created
        if event_type == "comment.created":
            comment_id = data.get("comment_id")
            comment_text = data.get("text", "")
            from_dict = data.get("from", {})
            user_id = from_dict.get("user_id") if isinstance(from_dict, dict) else None

            if comment_text and user_id and comment_id:
                text_lower = comment_text.lower()

                # Find all matching rules
                rules_stmt = select(Rule)
                rules_result = await db.execute(rules_stmt)
                all_rules = rules_result.scalars().all()

                for rule in all_rules:
                    if rule.keyword in text_lower:
                        # Atomic check-and-set reservation for (user_id, rule_id)
                        try:
                            async with db.begin_nested():
                                dispatch_entry = UserRuleDispatch(
                                    user_id=user_id,
                                    rule_id=rule.rule_id,
                                    comment_id=comment_id
                                )
                                db.add(dispatch_entry)
                        except IntegrityError:
                            await db.execute(
                                update(StatCounter).where(StatCounter.id == 1).values(
                                    duplicates_blocked=StatCounter.duplicates_blocked + 1
                                )
                            )
                            logger.info(f"User {user_id} already DMed for rule {rule.rule_id}. Skipping.")
                            continue

                        # Create pending DM task for genuine first-time user dispatches
                        task = DMTask(
                            comment_id=comment_id,
                            recipient_user_id=user_id,
                            rule_id=rule.rule_id,
                            message=rule.dm_message,
                            status="queued"
                        )
                        db.add(task)
                        logger.info(f"Enqueued DM task for user {user_id}, comment {comment_id}, rule {rule.rule_id}")

            await db.commit()
            return {"status": "ok"}

        await db.commit()
        return {"status": "ok"}

    except IntegrityError:
        # Microsecond race condition on duplicate event_id or DB constraint
        await db.rollback()
        logger.info(f"Concurrent duplicate event_id {event_id} caught by IntegrityError.")
        async with db.begin():
            await db.execute(
                update(StatCounter).where(StatCounter.id == 1).values(
                    duplicates_blocked=StatCounter.duplicates_blocked + 1
                )
            )
        return {"status": "ok", "message": "duplicate_event_ignored"}

