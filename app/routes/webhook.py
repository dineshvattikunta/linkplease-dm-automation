import json
import logging
from fastapi import APIRouter, Request, Header, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from app.database import get_db
from app.security import verify_webhook_signature
from app.models import WebhookEvent, Rule, DMTask, UserRuleDispatch, StatCounter

logger = logging.getLogger("webhook")
router = APIRouter(tags=["Webhook"])

@router.post("/webhook", status_code=status.HTTP_200_OK)
@router.post("/webhook/", status_code=status.HTTP_200_OK)
async def handle_webhook(
    request: Request,
    x_pseudogram_signature: str = Header(None, alias="X-PseudoGram-Signature"),
    db: AsyncSession = Depends(get_db)
):
    raw_body = await request.body()

    # 1. Signature Verification (Part B requirement)
    if x_pseudogram_signature:
        if not verify_webhook_signature(raw_body, x_pseudogram_signature):
            logger.warning(f"Webhook signature mismatch for header: '{x_pseudogram_signature[:30]}...'")
    else:
        logger.info("Webhook payload received without signature header.")

    # 2. Parse Payload safely (dict, list, or wrapped objects)
    try:
        raw_payload = json.loads(raw_body.decode("utf-8"))
    except Exception as e:
        logger.error(f"Failed to parse JSON body: {e}")
        return {"status": "ignored", "reason": "invalid_json"}

    events_list = []
    if isinstance(raw_payload, list):
        events_list = raw_payload
    elif isinstance(raw_payload, dict):
        if "events" in raw_payload and isinstance(raw_payload["events"], list):
            events_list = raw_payload["events"]
        elif "entry" in raw_payload and isinstance(raw_payload["entry"], list):
            events_list = raw_payload["entry"]
        else:
            events_list = [raw_payload]

    for payload in events_list:
        if not isinstance(payload, dict):
            continue

        event_id = payload.get("event_id") or payload.get("id")
        event_type = payload.get("event_type") or payload.get("type")
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload

        if not event_id or not event_type:
            continue

        # 3. Deduplicate by event_id (~8% duplicate events)
        existing_evt = await db.get(WebhookEvent, event_id)
        if existing_evt:
            logger.info(f"Duplicate event_id received: {event_id}. Ignoring.")
            await db.execute(
                update(StatCounter).where(StatCounter.id == 1).values(
                    duplicates_blocked=StatCounter.duplicates_blocked + 1
                )
            )
            await db.commit()
            continue

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
                continue

            # 5. Handle comment.created
            if event_type == "comment.created":
                comment_id = data.get("comment_id")
                comment_text = data.get("text", "")
                from_dict = data.get("from", {})
                user_id = from_dict.get("user_id") if isinstance(from_dict, dict) else None

                if comment_text and user_id and comment_id:
                    text_lower = comment_text.lower()

                    rules_stmt = select(Rule)
                    rules_result = await db.execute(rules_stmt)
                    all_rules = rules_result.scalars().all()

                    for rule in all_rules:
                        if rule.keyword.lower() in text_lower:
                            # Explicit SELECT-before-INSERT dedup (reliable across all async drivers)
                            existing_dispatch = await db.execute(
                                select(UserRuleDispatch).where(
                                    UserRuleDispatch.user_id == user_id,
                                    UserRuleDispatch.rule_id == rule.rule_id
                                ).limit(1)
                            )
                            if existing_dispatch.scalar_one_or_none() is not None:
                                await db.execute(
                                    update(StatCounter).where(StatCounter.id == 1).values(
                                        duplicates_blocked=StatCounter.duplicates_blocked + 1
                                    )
                                )
                                logger.info(f"User {user_id} already dispatched for rule {rule.rule_id}. Skipping.")
                                continue

                            # Reserve dispatch slot
                            dispatch_entry = UserRuleDispatch(
                                user_id=user_id,
                                rule_id=rule.rule_id,
                                comment_id=comment_id
                            )
                            db.add(dispatch_entry)

                            # Enqueue DM task
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

        except Exception as ie:
            await db.rollback()
            logger.error(f"Unexpected error processing event_id {event_id}: {ie}", exc_info=True)


    return {"status": "ok"}
