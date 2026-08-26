import pytest
from httpx import AsyncClient
from app.main import app

@pytest.mark.asyncio
async def test_record_office_directory():
    # This assumes some students are already in the database and approved
    async with AsyncClient(app=app, base_url="http://test") as ac:
        # Mocking authentication not easily possible here without setup
        # But this is for testing structure and endpoint availability
        response = await ac.get("/api/v1/record-office/directory")
        # Should be 401/403 without auth
        assert response.status_code in [401, 403]
