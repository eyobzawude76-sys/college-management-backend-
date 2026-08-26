from datetime import datetime
from typing import Optional, List
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.database import db, departments_collection, courses_collection
from app.core.models import User
from app.core.constants import UserRole, UserStatus
from app.shared.auth import get_current_active_user, get_password_hash
from app.shared.rbac import require_role

# ============================================================
# SCHEMAS
# ============================================================

class DepartmentCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    description: Optional[str] = None

class DepartmentResponse(BaseModel):
    id: str = Field(alias="_id")
    name: str
    description: Optional[str] = None
    createdAt: datetime
    updatedAt: Optional[datetime] = None
    isDeleted: bool = False

    class Config:
        populate_by_name = True

class CourseCreate(BaseModel):
    departmentId: str
    name: str = Field(..., min_length=2, max_length=150)
    code: str = Field(..., min_length=2, max_length=30)

class CourseResponse(BaseModel):
    id: str = Field(alias="_id")
    departmentId: str
    name: str
    code: str
    createdAt: datetime
    updatedAt: Optional[datetime] = None
    isDeleted: bool = False

    class Config:
        populate_by_name = True

# Schema for Teacher Assignment by Dept Head
class AssignTeacherCreate(BaseModel):
    username: str = Field(..., min_length=3)
    password: str = Field(..., min_length=6)
    full_name: str
    departmentId: str
    levelId: str
    moduleIds: List[str]

# ============================================================
# ROUTER
# ============================================================

router = APIRouter()



# ============================================================
# CREATE DEPARTMENT — ADMIN ONLY
# ============================================================

@router.post("/", response_model=DepartmentResponse, status_code=status.HTTP_201_CREATED)
@require_role([UserRole.ADMIN])
async def create_department(data: DepartmentCreate, current_user: User = Depends(get_current_active_user)):
    existing = await departments_collection.find_one({"name": data.name, "isDeleted": False})
    if existing:
        raise HTTPException(status_code=400, detail="Department already exists")

    department = {
        "name": data.name,
        "description": data.description,
        "createdAt": datetime.utcnow(),
        "updatedAt": None,
        "isDeleted": False
    }
    result = await departments_collection.insert_one(department)
    department["_id"] = str(result.inserted_id)
    return department

# ============================================================
# LIST DEPARTMENTS
# ============================================================

@router.get("/", response_model=List[DepartmentResponse])
async def list_departments(current_user: User = Depends(get_current_active_user)):
    cursor = departments_collection.find({"isDeleted": False}).sort("name", 1)
    departments = []
    async for department in cursor:
        department["_id"] = str(department["_id"])
        departments.append(department)
    return departments

# ============================================================
# MY COURSES (LOGGED-IN DEPARTMENT HEAD / TEACHER)
# ============================================================

@router.get("/my-courses/me")
async def get_my_courses(current_user: User = Depends(get_current_active_user)):
    user_id = str(current_user.id)
    user = await db["users"].find_one({"_id": ObjectId(user_id)})
    if not user:
        return []

    query_conditions = []

    if user.get("courseId"):
        cid = str(user["courseId"])
        if ObjectId.is_valid(cid):
            query_conditions.append({"_id": ObjectId(cid)})
        query_conditions.append({"_id": cid})

    if user.get("departmentId"):
        did = str(user["departmentId"])
        if ObjectId.is_valid(did):
            query_conditions.append({"departmentId": ObjectId(did)})
        query_conditions.append({"departmentId": did})

    if not query_conditions:
        return []

    courses = await db["courses"].find({
        "isDeleted": {"$ne": True},
        "$or": query_conditions
    }).to_list(100)

    for course in courses:
        course["_id"] = str(course["_id"])
        if "departmentId" in course:
            course["departmentId"] = str(course["departmentId"])

    return courses

# ============================================================
# CREATE & ASSIGN TEACHER (DEPARTMENT HEAD ONLY)
# ============================================================

@router.post("/assign-teacher", status_code=status.HTTP_201_CREATED)
@require_role([UserRole.DEPARTMENT_HEAD, UserRole.ADMIN])
async def create_and_assign_teacher(
    data: AssignTeacherCreate, 
    current_user: User = Depends(get_current_active_user)
):
    # Check if username already exists
    existing_user = await db["users"].find_one({"username": data.username})
    if existing_user:
        raise HTTPException(status_code=400, detail="Username eessaniin jira. Kan biraa fayyadamaa.")

    # 1. Create Teacher Account
    teacher_user = {
        "username": data.username,
        "password_hash": get_password_hash(data.password),
        "full_name": data.full_name,
        "role": UserRole.TEACHER,
        "departmentId": data.departmentId,
        "status": UserStatus.ACTIVE,
        "createdAt": datetime.utcnow()
    }
    
    user_result = await db["users"].insert_one(teacher_user)
    teacher_id = str(user_result.inserted_id)

    # 2. Store Teacher Assignment Link
    assignment = {
        "teacherId": teacher_id,
        "departmentId": data.departmentId,
        "levelId": data.levelId,
        "moduleIds": data.moduleIds,
        "assignedBy": str(current_user.id),
        "createdAt": datetime.utcnow()
    }
    
    await db["teacher_assignments"].insert_one(assignment)

    # 3. Also update `teacherId` in modules collection for quick indexing
    for module_id in data.moduleIds:
        if ObjectId.is_valid(module_id):
            await db["modules"].update_one(
                {"_id": ObjectId(module_id)},
                {"$set": {"teacherId": teacher_id}}
            )

    return {
        "message": "Teacher account uumamee Module-wwan itti ramadamaniiru.",
        "teacherId": teacher_id
    }

# ============================================================
# UPDATE DEPARTMENT — ADMIN ONLY
# ============================================================

@router.put("/{department_id}", response_model=DepartmentResponse)
@require_role([UserRole.ADMIN])
async def update_department(department_id: str, data: DepartmentCreate, current_user: User = Depends(get_current_active_user)):
    if not ObjectId.is_valid(department_id):
        raise HTTPException(status_code=400, detail="Invalid department ID")

    existing = await departments_collection.find_one({
        "name": data.name, "isDeleted": False,
        "_id": {"$ne": ObjectId(department_id)}
    })
    if existing:
        raise HTTPException(status_code=400, detail="Department name already exists")

    result = await departments_collection.update_one(
        {"_id": ObjectId(department_id), "isDeleted": False},
        {"$set": {"name": data.name, "description": data.description, "updatedAt": datetime.utcnow()}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Department not found")

    department = await departments_collection.find_one({"_id": ObjectId(department_id)})
    department["_id"] = str(department["_id"])
    return department

# ============================================================
# DELETE DEPARTMENT — SOFT DELETE — ADMIN ONLY
# ============================================================

@router.delete("/{department_id}", status_code=status.HTTP_204_NO_CONTENT)
@require_role([UserRole.ADMIN])
async def delete_department(department_id: str, current_user: User = Depends(get_current_active_user)):
    if not ObjectId.is_valid(department_id):
        raise HTTPException(status_code=400, detail="Invalid department ID")

    result = await departments_collection.update_one(
        {"_id": ObjectId(department_id), "isDeleted": False},
        {"$set": {"isDeleted": True, "deletedAt": datetime.utcnow()}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Department not found")
    return None

# ============================================================
# CREATE COURSE — ADMIN ONLY (Department -> Course)
# ============================================================

@router.post("/courses", response_model=CourseResponse, status_code=status.HTTP_201_CREATED)
@require_role([UserRole.ADMIN])
async def create_course(data: CourseCreate, current_user: User = Depends(get_current_active_user)):
    if not ObjectId.is_valid(data.departmentId):
        raise HTTPException(status_code=400, detail="Invalid department ID")

    department = await departments_collection.find_one({"_id": ObjectId(data.departmentId), "isDeleted": False})
    if not department:
        raise HTTPException(status_code=404, detail="Department not found")

    existing = await courses_collection.find_one({
        "departmentId": data.departmentId, "code": data.code, "isDeleted": False
    })
    if existing:
        raise HTTPException(status_code=400, detail="Course code already exists in this department")

    course = {
        "departmentId": data.departmentId,
        "name": data.name,
        "code": data.code,
        "createdAt": datetime.utcnow(),
        "updatedAt": None,
        "isDeleted": False
    }
    result = await courses_collection.insert_one(course)
    course["_id"] = str(result.inserted_id)
    return course

# ============================================================
# LIST COURSES BY DEPARTMENT
# GET /departments/{department_id}/courses
# ============================================================

@router.get("/{department_id}/courses", response_model=List[CourseResponse])
async def list_department_courses(department_id: str, current_user: User = Depends(get_current_active_user)):
    user_role = getattr(current_user, "role", "")
    if user_role == UserRole.DEPARTMENT_HEAD:
        user_dept_id = str(getattr(current_user, "departmentId", ""))
        if user_dept_id and user_dept_id != department_id:
            raise HTTPException(status_code=403, detail="Access denied: You can only view your assigned department courses.")

    if not ObjectId.is_valid(department_id):
        raise HTTPException(status_code=400, detail="Invalid department ID")

    dept_obj_id = ObjectId(department_id)
    cursor = courses_collection.find({
        "$or": [{"departmentId": dept_obj_id}, {"departmentId": department_id}],
        "isDeleted": False
    }).sort("name", 1)

    courses = []
    async for course in cursor:
        course["_id"] = str(course["_id"])
        course["departmentId"] = str(course["departmentId"])

        user_course_id = str(getattr(current_user, "courseId", ""))
        if user_role == UserRole.DEPARTMENT_HEAD and user_course_id:
            if course["_id"] == user_course_id:
                courses.append(course)
        else:
            courses.append(course)

    return courses

# ============================================================
# UPDATE COURSE — ADMIN ONLY
# ============================================================

@router.put("/courses/{course_id}", response_model=CourseResponse)
@require_role([UserRole.ADMIN])
async def update_course(course_id: str, data: CourseCreate, current_user: User = Depends(get_current_active_user)):
    if not ObjectId.is_valid(course_id):
        raise HTTPException(status_code=400, detail="Invalid course ID")
    if not ObjectId.is_valid(data.departmentId):
        raise HTTPException(status_code=400, detail="Invalid department ID")

    result = await courses_collection.update_one(
        {"_id": ObjectId(course_id), "isDeleted": False},
        {"$set": {"departmentId": data.departmentId, "name": data.name, "code": data.code, "updatedAt": datetime.utcnow()}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Course not found")

    course = await courses_collection.find_one({"_id": ObjectId(course_id)})
    course["_id"] = str(course["_id"])
    return course

# ============================================================
# DELETE COURSE
# ============================================================

@router.delete("/courses/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
@require_role([UserRole.ADMIN])
async def delete_course(course_id: str, current_user: User = Depends(get_current_active_user)):
    if not ObjectId.is_valid(course_id):
        raise HTTPException(status_code=400, detail="Invalid course ID")

    result = await courses_collection.update_one(
        {"_id": ObjectId(course_id), "isDeleted": False},
        {"$set": {"isDeleted": True, "deletedAt": datetime.utcnow()}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Course not found")
    return None

# ============================================================
# GET DEPARTMENT BY ID
# ============================================================

@router.get("/{department_id}")
async def get_department(department_id: str, current_user: User = Depends(get_current_active_user)):
    if not ObjectId.is_valid(department_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid department ID")

    department = await departments_collection.find_one({"_id": ObjectId(department_id)})
    if not department:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department not found")

    department["_id"] = str(department["_id"])
    return department