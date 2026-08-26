import pytest
from datetime import datetime

@pytest.mark.asyncio
async def test_complete_marks_workflow(client, admin_token, test_db):
    # 1. Create department
    dept_response = await client.post(
        "/api/departments/",
        json={"name": "Computer Science", "description": "CS Dept"},
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    dept_id = dept_response.json()["_id"]
    
    # 2. Create level
    level_response = await client.post(
        "/api/levels/",
        json={"levelNumber": 1, "departmentId": dept_id},
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    level_id = level_response.json()["_id"]
    
    # 3. Create module
    module_response = await client.post(
        "/api/modules/",
        json={
            "moduleCode": "CS101",
            "moduleName": "Introduction to Programming",
            "creditHour": 3,
            "levelId": level_id,
            "departmentId": dept_id
        },
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert module_response.status_code == 201
    module = module_response.json()
    assert "pin" in module
    assert len(module["pin"]) == 6
    
    # Verify workflow integrity
    assert module_response.json()["levelId"] == level_id