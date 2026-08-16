import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import delete
from app.main import app
from app.database import AsyncSessionLocal
from app.models import Rule

@pytest.mark.asyncio
async def test_create_rule():
    # Clean any existing rules first so the unique-keyword constraint doesn't conflict
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Rule))
        await db.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post("/rules", json={
            "keyword": "PRICE",
            "dm_message": "Here is the price list: $99"
        })
    assert response.status_code == 201
    data = response.json()
    assert "rule_id" in data
    assert data["keyword"] == "price"
    assert data["dm_message"] == "Here is the price list: $99"
