from datetime import datetime
from typing import Optional, List

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.database import (
    levels_collection,
    departments_collection,
    courses_collection,
)

from app.features.auth import User, UserRole
from app.shared.auth import get_current_active_user
from app.shared.rbac import require_role

# ============================================================
# SCHEMAS
# ============================================================

class LevelCreate(BaseModel):
    departmentId: str
    courseId: Optional[str] = None
    levelNumber: int = Field(..., ge=1, le=5)
    description: Optional[str] = None

class LevelResponse(BaseModel):
    id: str = Field(alias="_id")
    departmentId: str
    courseId: str
    levelNumber: int
    description: Optional[str] = None
    isDeleted: bool = False
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None
    
    class Config:
        populate_by_name = True

# ============================================================
# ROUTER
# ============================================================

router = APIRouter()

# ============================================================
# HELPERS
# ============================================================

def valid_object_id(value: Optional[str]) -> bool:
    return bool(value and ObjectId.is_valid(value))

def get_user_course_id(current_user: User) -> Optional[str]:
    course_id = getattr(current_user, "courseId", None)
    if not course_id:
        course_id = getattr(current_user, "assigned_course_id", None)
    if course_id:
        return str(course_id)
    return None

def get_user_department_id(current_user: User) -> Optional[str]:
    department_id = getattr(current_user, "departmentId", None)
    if department_id:
        return str(department_id)
    return None

# ============================================================
# CREATE LEVEL
# ============================================================

@router.post("", response_model=LevelResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=LevelResponse, status_code=status.HTTP_201_CREATED)
@require_role([UserRole.DEPARTMENT_HEAD])
async def create_level(
    data: LevelCreate,
    current_user: User = Depends(get_current_active_user),
):
    if not valid_object_id(data.departmentId):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid department ID",
        )

    department_id = ObjectId(data.departmentId)

    department = await departments_collection.find_one(
        {"_id": department_id, "isDeleted": False}
    )

    if not department:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Department not found",
        )

    user_department_id = get_user_department_id(current_user)
    if user_department_id and user_department_id != data.departmentId:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only manage your own department",
        )

    if not data.courseId:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Course ID is required to create a level",
        )

    if not valid_object_id(data.courseId):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid course ID",
        )

    course_id = ObjectId(data.courseId)

    course = await courses_collection.find_one(
        {"_id": course_id, "isDeleted": False}
    )

    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found",
        )

    course_department_id = course.get("departmentId")
    if course_department_id is not None:
        course_department_id = str(course_department_id)

    if course_department_id != data.departmentId:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Course does not belong to this department",
        )

    user_course_id = get_user_course_id(current_user)
    if user_course_id and user_course_id != data.courseId:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only manage levels in your assigned course",
        )

    existing = await levels_collection.find_one(
        {
            "courseId": data.courseId,
            "levelNumber": data.levelNumber,
            "isDeleted": False,
        }
    )

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Level {data.levelNumber} already exists in this course",
        )

    now = datetime.utcnow()
    level = {
        "departmentId": data.departmentId,
        "courseId": data.courseId,
        "levelNumber": data.levelNumber,
        "description": data.description,
        "createdAt": now,
        "updatedAt": now,
        "isDeleted": False,
    }

    result = await levels_collection.insert_one(level)
    level["_id"] = str(result.inserted_id)

    return level

# ============================================================
# LIST LEVELS
# ============================================================

@router.get("", response_model=List[LevelResponse])
@router.get("/", response_model=List[LevelResponse])
async def list_levels(
    deptId: Optional[str] = None,
    departmentId: Optional[str] = None,
    courseId: Optional[str] = None,
    current_user: User = Depends(get_current_active_user),
):
    target_dept = deptId or departmentId
    query = {"isDeleted": False}

    if target_dept:
        if not valid_object_id(target_dept):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid department ID",
            )
        query["departmentId"] = target_dept

    if courseId:
        if not valid_object_id(courseId):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid course ID",
            )
        query["courseId"] = courseId

    cursor = levels_collection.find(query).sort("levelNumber", 1)

    levels = []
    async for level in cursor:
        level["_id"] = str(level["_id"])
        if level.get("departmentId"):
            level["departmentId"] = str(level["departmentId"])
        if level.get("courseId"):
            level["courseId"] = str(level["courseId"])
        levels.append(level)

    return levels

# ============================================================
# GET SINGLE LEVEL
# ============================================================

@router.get("/{level_id}", response_model=LevelResponse)
async def get_level(
    level_id: str,
    current_user: User = Depends(get_current_active_user),
):
    if not valid_object_id(level_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid level ID",
        )

    level = await levels_collection.find_one(
        {"_id": ObjectId(level_id), "isDeleted": False}
    )

    if not level:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Level not found",
        )

    level["_id"] = str(level["_id"])
    if level.get("departmentId"):
        level["departmentId"] = str(level["departmentId"])
    if level.get("courseId"):
        level["courseId"] = str(level["courseId"])

    return level

# ============================================================
# UPDATE LEVEL
# ============================================================

@router.put("/{level_id}", response_model=LevelResponse)
@require_role([UserRole.DEPARTMENT_HEAD])
async def update_level(
    level_id: str,
    data: LevelCreate,
    current_user: User = Depends(get_current_active_user),
):
    if not valid_object_id(level_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid level ID",
        )

    existing_level = await levels_collection.find_one(
        {"_id": ObjectId(level_id), "isDeleted": False}
    )

    if not existing_level:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Level not found",
        )

    user_department_id = get_user_department_id(current_user)
    existing_department_id = str(existing_level.get("departmentId"))

    if user_department_id and user_department_id != existing_department_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only manage your own department",
        )

    if not valid_object_id(data.departmentId):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid department ID",
        )

    department = await departments_collection.find_one(
        {"_id": ObjectId(data.departmentId), "isDeleted": False}
    )

    if not department:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Department not found",
        )

    if not data.courseId:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Course ID is required",
        )

    if not valid_object_id(data.courseId):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid course ID",
        )

    course = await courses_collection.find_one(
        {"_id": ObjectId(data.courseId), "isDeleted": False}
    )

    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found",
        )

    course_department_id = course.get("departmentId")
    if course_department_id is not None:
        course_department_id = str(course_department_id)

    if course_department_id != data.departmentId:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Course does not belong to this department",
        )

    user_course_id = get_user_course_id(current_user)
    if user_course_id and user_course_id != data.courseId:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only manage levels in your assigned course",
        )

    duplicate = await levels_collection.find_one(
        {
            "_id": {"$ne": ObjectId(level_id)},
            "courseId": data.courseId,
            "levelNumber": data.levelNumber,
            "isDeleted": False,
        }
    )

    if duplicate:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This level already exists in this course",
        )

    now = datetime.utcnow()
    result = await levels_collection.update_one(
        {"_id": ObjectId(level_id), "isDeleted": False},
        {
            "$set": {
                "departmentId": data.departmentId,
                "courseId": data.courseId,
                "levelNumber": data.levelNumber,
                "description": data.description,
                "updatedAt": now,
            }
        },
    )

    if result.matched_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Level not found",
        )

    level = await levels_collection.find_one({"_id": ObjectId(level_id)})
    level["_id"] = str(level["_id"])
    if level.get("departmentId"):
        level["departmentId"] = str(level["departmentId"])
    if level.get("courseId"):
        level["courseId"] = str(level["courseId"])

    return level

# ============================================================
# DELETE LEVEL
# ============================================================

@router.delete("/{level_id}", status_code=status.HTTP_204_NO_CONTENT)
@require_role([UserRole.DEPARTMENT_HEAD])
async def delete_level(
    level_id: str,
    current_user: User = Depends(get_current_active_user),
):
    if not valid_object_id(level_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid level ID",
        )

    level = await levels_collection.find_one(
        {"_id": ObjectId(level_id), "isDeleted": False}
    )

    if not level:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Level not found",
        )

    user_department_id = get_user_department_id(current_user)
    level_department_id = str(level.get("departmentId"))

    if user_department_id and user_department_id != level_department_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete levels in your department",
        )

    level_course_id = level.get("courseId")
    if level_course_id:
        user_course_id = get_user_course_id(current_user)
        if user_course_id and user_course_id != str(level_course_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only delete levels in your assigned course",
            )

    now = datetime.utcnow()
    await levels_collection.update_one(
        {"_id": ObjectId(level_id), "isDeleted": False},
        {
            "$set": {
                "isDeleted": True,
                "deletedAt": now,
                "updatedAt": now,
            }
        },
    )

    return None