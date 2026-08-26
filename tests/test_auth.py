import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_register_student(client):
    response = await client.post("/auth/register", json={
        "fullName": "Test Student",
        "email": "student@test.com",
        "password": "student123",
        "role": "student"
    })
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "student@test.com"
    assert data["role"] == "student"
    assert data["status"] == "pending"

@pytest.mark.asyncio
async def test_login_success(client, admin_user):
    response = await client.post("/auth/login", json={
        "email": "admin@test.com",
        "password": "admin123"
    })
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data

@pytest.mark.asyncio
async def test_login_invalid_credentials(client):
    response = await client.post("/auth/login", json={
        "email": "wrong@test.com",
        "password": "wrong"
    })
    assert response.status_code == 401

@pytest.mark.asyncio
async def test_protected_route_without_token(client):
    response = await client.get("/api/users/")
    assert response.status_code == 403

@pytest.mark.asyncio
async def test_role_based_access(client, admin_token):
    # Admin can access user list
    response = await client.get(
        "/api/users/",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert response.status_code == 200