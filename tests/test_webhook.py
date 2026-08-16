import json
import hmac
import hashlib
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.config import settings

def generate_signature(body: bytes, secret: str) -> str:
    sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={sig}"

@pytest.mark.asyncio
async def test_webhook_invalid_signature():
    payload = {"event_id": "evt_test1", "event_type": "comment.created", "data": {}}
    body = json.dumps(payload).encode("utf-8")
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post(
            "/webhook",
            content=body,
            headers={"X-PseudoGram-Signature": "sha256=invalidhexsignature"}
        )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_webhook_missing_signature_header():
    payload = {"event_id": "evt_test2", "event_type": "comment.created", "data": {}}
    body = json.dumps(payload).encode("utf-8")
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post("/webhook", content=body)
    assert response.status_code == 200



@pytest.mark.asyncio
async def test_webhook_valid_signature_and_matching():
    # 1. Create a rule first
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        await ac.post("/rules", json={"keyword": "INFO", "dm_message": "Here is details"})

        # 2. Send webhook matching rule
        payload = {
            "event_id": "evt_001",
            "event_type": "comment.created",
            "sent_at": "2026-08-10T09:14:22.481Z",
            "data": {
                "comment_id": "cmt_001",
                "post_id": "post_001",
                "text": "Need INFO please!",
                "created_at": "2026-08-10T09:14:21.900Z",
                "from": {
                    "user_id": "usr_test123",
                    "username": "dinesh_test"
                }
            }
        }
        body = json.dumps(payload).encode("utf-8")
        sig = generate_signature(body, settings.API_KEY)

        response = await ac.post(
            "/webhook",
            content=body,
            headers={"X-PseudoGram-Signature": sig}
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
