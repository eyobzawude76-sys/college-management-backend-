import pytest
import pytest_asyncio
from httpx import AsyncClient
from app.main import app
from app.database import db
from app.shared.hashing import hash_password
from bson import ObjectId
from datetime import datetime
@pytest_asyncio.fixture
async def client():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac

@pytest_asyncio.fixture
async def test_db():
    # Use test database
    test_db_name = "cams_test_db"
    db.client.drop_database(test_db_name)
    yield db.client[test_db_name]
    db.client.drop_database(test_db_name)

@pytest_asyncio.fixture
async def admin_user(test_db):
    user = {
        "_id": ObjectId(),
        "fullName": "Test Admin",
        "email": "admin@test.com",
        "passwordHash": hash_password("admin123"),
        "role": "admin",
        "status": "active",
        "createdAt": datetime.utcnow(),
        "isDeleted": False
    }
    await test_db.users.insert_one(user)
    return user

@pytest_asyncio.fixture
async def admin_token(client, admin_user):
    response = await client.post("/auth/login", json={
        "email": "admin@test.com",
        "password": "admin123"
    })
    return response.json()["access_token"]