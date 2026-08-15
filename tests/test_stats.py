import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.mark.asyncio
async def test_get_stats():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/stats")
    assert response.status_code == 200
    data = response.json()
    assert "sent" in data
    assert "failed" in data
    assert "queued" in data
    assert "duplicates_blocked" in data
    assert isinstance(data["sent"], int)
    assert isinstance(data["failed"], int)
    assert isinstance(data["queued"], int)
    assert isinstance(data["duplicates_blocked"], int)
