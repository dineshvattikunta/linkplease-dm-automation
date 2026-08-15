import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.mark.asyncio
async def test_create_rule():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post("/rules", json={
            "keyword": "PRICE",
            "dm_message": "Here is the price list: $99"
        })
    assert response.status_code == 201
    data = response.json()
    assert "rule_id" in data
    assert data["keyword"] == "PRICE"
    assert data["dm_message"] == "Here is the price list: $99"
