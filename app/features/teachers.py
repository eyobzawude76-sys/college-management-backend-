from datetime import datetime
from typing import List, Optional
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, EmailStr
import uuid

from app.database import (
    users_collection,
    teachers_collection,
    departments_collection,
    module_assignments_collection,
    modules_collection,
)
from app.core.models import User
from app.core.constants import UserRole
from app.shared.auth import get_current_active_user
from app.shared.rbac import require_role
from app.shared.hashing import hash_password

# ==========================================================
# ROUTER CONFIGURATION
# ==========================================================

router = APIRouter()
 


# ==========================================================
# PYDANTIC SCHEMAS
# ==========================================================

class TeacherCreate(BaseModel):
    fullName: str
    username: str
    password: str
    level: str
    departmentId: Optional[str] = None
    email: Optional[EmailStr] = None
    status :Optional[str]="approved"
class TeacherResponse(BaseModel):
    id: str = Field(alias="_id")
    fullName: str
    username: str
    level: str
    departmentId: Optional[str] = None
    email: Optional[EmailStr] = None
    userId: Optional[str] = None

    class Config:
        populate_by_name = True

# Helper function to extract departmentId safely
async def resolve_department_id(user: any, custom_dept_id: Optional[str] = None) -> Optional[str]:
    if custom_dept_id:
        return custom_dept_id

    # Dict vs Model handling
    if isinstance(user, dict):
        user_dict = user
    elif hasattr(user, "model_dump"):
        user_dict = user.model_dump()
    else:
        user_dict = getattr(user, "__dict__", dict(user))

    dept_id = user_dict.get("departmentId") or user_dict.get("department_id")
    if dept_id:
        return str(dept_id)

    # Search in Users Collection
    user_id = user_dict.get("_id") or user_dict.get("id")
    if user_id:
        try:
            db_user = await users_collection.find_one({"_id": ObjectId(str(user_id))})
        except Exception:
            db_user = await users_collection.find_one({"_id": str(user_id)})

        if db_user:
            dept_id = db_user.get("departmentId") or db_user.get("department_id")
            if dept_id:
                return str(dept_id)

    # Search in Departments Head Ownership
    user_id_str = str(user_id) if user_id else ""
    dept = await departments_collection.find_one(
        {"$or": [{"headId": user_id_str}, {"head_id": user_id_str}]}
    )
    return str(dept["_id"]) if dept else None

# ==========================================================
# GET ALL TEACHERS (BY DEPARTMENT)
# ==========================================================

@router.get("/", status_code=status.HTTP_200_OK)
@require_role([UserRole.DEPARTMENT_HEAD, UserRole.ADMIN])
async def get_teachers(
    departmentId: Optional[str] = None,
    current_user=Depends(get_current_active_user),
):
    dept_id = await resolve_department_id(current_user, departmentId)

    query = {"isDeleted": {"$ne": True}}
    if dept_id:
        query["departmentId"] = str(dept_id)

    cursor = teachers_collection.find(query)
    teachers = []

    async for doc in cursor:
        doc["_id"] = str(doc["_id"])
        doc.pop("password", None)
        teachers.append(doc)

    return teachers

# ==========================================================
# CREATE TEACHER
# ==========================================================

@router.post("/", status_code=status.HTTP_201_CREATED)
@require_role([UserRole.DEPARTMENT_HEAD, UserRole.ADMIN])
async def create_teacher(
    data: TeacherCreate,
    current_user=Depends(get_current_active_user),
):
    dept_id = await resolve_department_id(current_user, data.departmentId)

    if not dept_id:
        raise HTTPException(
            status_code=400,
            detail="Department ID DB keessatti hin argamne. Mee user kanaaf department assign godhaa.",
        )

    # Prevent duplicate username
    existing_user = await teachers_collection.find_one(
        {"username": data.username, "isDeleted": {"$ne": True}}
    )
    if existing_user:
        raise HTTPException(
            status_code=400,
            detail="Username kun duraan akka teacher-tti fayyadama irra jira.",
        )

    # Generate unique ID for teacher mapping
    generated_user_id = f"USR-{uuid.uuid4().hex[:6].upper()}"

    new_teacher = {
        "fullName": data.fullName,
        "username": data.username,
        "password": hash_password(data.password),
        "level": data.level,
        "departmentId": str(dept_id),
        "role": "teacher",
        "isDeleted": False,
        "createdAt": datetime.utcnow(),
        # Both field names saved to fix lookup mismatch bugs
        "userId": generated_user_id,
        "user_id": generated_user_id,
        "status":"approved",
        "is_active": True,
        "employee_id": f"EMP-{uuid.uuid4().hex[:6].upper()}"
    }

    result = await teachers_collection.insert_one(new_teacher)

    return {
        "message": "Teacher successfully created",
        "teacherId": str(result.inserted_id),
        "departmentId": str(dept_id),
    }

# ==========================================================
# GET ASSIGNED MODULES FOR SPECIFIC TEACHER
# ==========================================================

@router.get("/{teacher_id}/modules", status_code=status.HTTP_200_OK)
@require_role([UserRole.ADMIN, UserRole.DEPARTMENT_HEAD])
async def get_teacher_assigned_modules(
    teacher_id: str,
    current_user=Depends(get_current_active_user),
):
    if not ObjectId.is_valid(teacher_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid teacher ID format",
        )

    cursor = module_assignments_collection.find(
        {
            "teacherId": teacher_id,
            "isActive": True,
        }
    )

    assigned_modules = []

    async for assignment in cursor:
        m_id = assignment.get("moduleId")
        if m_id and ObjectId.is_valid(m_id):
            module = await modules_collection.find_one(
                {"_id": ObjectId(m_id), "isDeleted": {"$ne": True}}
            )
            if module:
                assigned_modules.append(
                    {
                        "_id": str(assignment["_id"]),
                        "moduleId": str(module["_id"]),
                        "moduleName": module.get("name", ""),
                        "moduleCode": module.get("code", ""),
                        "departmentPin": module.get("departmentPin")
                        or module.get("modulePin"),
                        "assignedAt": assignment.get("assignedAt"),
                    }
                )

    return assigned_modules