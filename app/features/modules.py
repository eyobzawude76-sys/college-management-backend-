from random import choices
import string
from datetime import datetime
from typing import Optional, List

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.database import (
    users_collection,
    teachers_collection,
    departments_collection,
    audit_logs_collection,
    module_assignments_collection,
    modules_collection,
    levels_collection,
)
from app.features.auth import User, UserRole
from app.shared.auth import get_current_active_user
from app.shared.rbac import require_role

# ============================================================
# SCHEMAS
# ============================================================

class ModuleCreate(BaseModel):
    departmentId: str
    levelId: str
    name: str = Field(..., min_length=2, max_length=150)
    code: str = Field(..., min_length=2, max_length=30)
    creditHour: int = Field(default=3, ge=1, le=10)

class ModuleUpdate(BaseModel):
    name: str = Field(..., min_length=2, max_length=150)
    code: str = Field(..., min_length=2, max_length=30)
    creditHour: int = Field(default=3, ge=1, le=10)

class PinVerifyRequest(BaseModel):
    pin: str = Field(..., min_length=4, max_length=10)

class ModuleResponse(BaseModel):
    id: str = Field(alias="_id")
    departmentId: str
    levelId: str
    name: str
    code: str
    creditHour: int
    hasPin: bool = False
    modulePin: Optional[str] = None  # Department Head-f PIN deebisuuf
    pinGeneratedAt: Optional[datetime] = None
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None
    isDeleted: bool = False

    class Config:
        populate_by_name = True

# ============================================================
# ROUTER
# ============================================================

router = APIRouter()

# ============================================================
# MODULE PIN GENERATOR
# ============================================================

def generate_pin() -> str:
    return "".join(choices(string.digits, k=6))

async def generate_unique_pin() -> str:
    while True:
        pin = generate_pin()
        exists = await modules_collection.find_one(
            {"modulePin": pin, "isDeleted": False}
        )
        if not exists:
            return pin

# ============================================================
# DEPARTMENT HEAD OWNERSHIP CHECK
# ============================================================

async def check_department_head_owns_department(
    current_user: User,
    department_id: str,
):
    user_department_id = getattr(current_user, "departmentId", None)

    if user_department_id:
        if str(user_department_id) != str(department_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only manage modules in your assigned department",
            )
        return

    if current_user.role not in [UserRole.DEPARTMENT_HEAD, UserRole.ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Department Heads or Admins can manage modules",
        )

# ============================================================
# CREATE MODULE
# ============================================================

@router.post("", response_model=ModuleResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=ModuleResponse, status_code=status.HTTP_201_CREATED)
@require_role([UserRole.DEPARTMENT_HEAD])
async def create_module(
    data: ModuleCreate,
    current_user: User = Depends(get_current_active_user),
):
    if not ObjectId.is_valid(data.departmentId):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid department ID",
        )

    if not ObjectId.is_valid(data.levelId):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid level ID",
        )

    await check_department_head_owns_department(
        current_user=current_user,
        department_id=data.departmentId,
    )

    level_query = {
        "_id": ObjectId(data.levelId),
        "isDeleted": False,
        "$or": [
            {"departmentId": data.departmentId},
            {"departmentId": ObjectId(data.departmentId)}
        ]
    }
    level = await levels_collection.find_one(level_query)

    if not level:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Level not found in this department",
        )

    exists = await modules_collection.find_one(
        {
            "levelId": data.levelId,
            "code": data.code,
            "isDeleted": False,
        }
    )

    if exists:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Module code already exists in this level",
        )

    now = datetime.utcnow()
    module = {
        "departmentId": data.departmentId,
        "levelId": data.levelId,
        "name": data.name,
        "code": data.code,
        "creditHour": data.creditHour,
        "modulePin": None,
        "pinGeneratedAt": None,
        "createdAt": now,
        "updatedAt": now,
        "isDeleted": False,
    }

    result = await modules_collection.insert_one(module)
    module["_id"] = str(result.inserted_id)
    module["hasPin"] = False

    return module

# ============================================================
# LIST MODULES
# ============================================================

@router.get("", response_model=List[ModuleResponse])
@router.get("/", response_model=List[ModuleResponse])
async def list_modules(
    levelId: Optional[str] = None,
    deptId: Optional[str] = None,
    current_user: User = Depends(get_current_active_user),
):
    query = {"isDeleted": False}

    if levelId:
        if not ObjectId.is_valid(levelId):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid level ID",
            )
        query["levelId"] = levelId

    # 1. User/Token/Param irraa Department ID fiduu
    user_dict = current_user if isinstance(current_user, dict) else getattr(current_user, "__dict__", {})
    effective_dept = deptId or user_dict.get("departmentId") or user_dict.get("department_id")

    # 2. Yoo hin argamne DB keessatti sakatta'i (Users & Departments Collection)
    if not effective_dept and current_user.role in [UserRole.DEPARTMENT_HEAD, UserRole.ADMIN]:
        user_id_str = str(user_dict.get("_id") or user_dict.get("id") or getattr(current_user, "id", ""))
        
        # Users collection keessa barbaadi
        if user_id_str:
            try:
                db_user = await users_collection.find_one({"_id": ObjectId(user_id_str)})
            except Exception:
                db_user = await users_collection.find_one({"_id": user_id_str})

            if db_user:
                effective_dept = db_user.get("departmentId") or db_user.get("department_id")

        # Departments collection keessatti Head of Department ta'uu check godhi
        if not effective_dept:
            dept_doc = await departments_collection.find_one({"headId": user_id_str}) or await departments_collection.find_one({"head_id": user_id_str})
            if dept_doc:
                effective_dept = str(dept_doc["_id"])

    # Query keessatti filter godhi
    if effective_dept:
        if ObjectId.is_valid(effective_dept):
            query["departmentId"] = str(effective_dept)

    cursor = modules_collection.find(query).sort("name", 1)
    modules = []

    async for module in cursor:
        module["_id"] = str(module["_id"])
        module["hasPin"] = bool(module.get("modulePin"))

        # Department Head ykn Admin qofaaf PIN agarsiisi
        if current_user.role not in [UserRole.DEPARTMENT_HEAD, UserRole.ADMIN]:
            module["modulePin"] = None

        if "createdAt" not in module or not module["createdAt"]:
            module["createdAt"] = datetime.utcnow()

        modules.append(module)

    return modules
# ============================================================
# GET SINGLE MODULE
# ============================================================

@router.get("/{module_id}", response_model=ModuleResponse)
async def get_module(
    module_id: str,
    current_user: User = Depends(get_current_active_user),
):
    if not ObjectId.is_valid(module_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid module ID",
        )

    module = await modules_collection.find_one(
        {"_id": ObjectId(module_id), "isDeleted": False}
    )

    if not module:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Module not found",
        )

    module["_id"] = str(module["_id"])
    module["hasPin"] = bool(module.get("modulePin"))

    if current_user.role not in [UserRole.DEPARTMENT_HEAD, UserRole.ADMIN]:
        module["modulePin"] = None

    if "createdAt" not in module or not module["createdAt"]:
        module["createdAt"] = datetime.utcnow()

    return module

# ============================================================
# GENERATE MODULE PIN
# ============================================================

@router.post("/generate-pin/{module_id}")
@require_role([UserRole.DEPARTMENT_HEAD])
async def generate_module_pin(
    module_id: str,
    current_user: User = Depends(get_current_active_user),
):
    if not ObjectId.is_valid(module_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid module ID",
        )

    module = await modules_collection.find_one(
        {"_id": ObjectId(module_id), "isDeleted": False}
    )

    if not module:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Module not found",
        )

    # RULE: PIN-ni yoo uumamee jiraate, lammata akka hin uumamne dhorgi
    if module.get("modulePin"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Module kanaaf PIN duraan uumameera! Lammata uumuun hin danda'amu.",
        )

    module_department_id = module.get("departmentId")
    if not module_department_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Module has no department assigned",
        )

    await check_department_head_owns_department(
        current_user=current_user,
        department_id=str(module_department_id),
    )

    pin = await generate_unique_pin()
    now = datetime.utcnow()

    # DB keessatti yeruma sana Save/Update godha
    await modules_collection.update_one(
        {"_id": ObjectId(module_id)},
        {
            "$set": {
                "modulePin": pin,
                "pinGeneratedAt": now,
                "updatedAt": now,
            }
        },
    )

    return {
        "moduleId": module_id,
        "moduleName": module["name"],
        "moduleCode": module["code"],
        "pin": pin,
        "pinGeneratedAt": now,
        "message": "Module PIN generated successfully",
    }

# ============================================================
# VERIFY MODULE PIN
# ============================================================

@router.post("/verify-pin/{module_id}")
async def verify_module_pin(
    module_id: str,
    payload: PinVerifyRequest,
    current_user: User = Depends(get_current_active_user),
):
    if not ObjectId.is_valid(module_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid module ID",
        )

    module = await modules_collection.find_one(
        {"_id": ObjectId(module_id), "isDeleted": False}
    )

    if not module:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Module not found",
        )

    stored_pin = module.get("modulePin")

    if not stored_pin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="PIN has not been generated for this module yet.",
        )

    if stored_pin != payload.pin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect PIN for this module",
        )

    return {
        "success": True,
        "unlocked": True,
        "moduleId": module_id,
        "moduleName": module["name"],
        "message": "Module PIN verified successfully. Access granted.",
    }

# ============================================================
# GET MODULE PIN
# ============================================================

@router.get("/get-pin/{module_id}")
@require_role([UserRole.DEPARTMENT_HEAD])
async def get_module_pin_for_head(
    module_id: str,
    current_user: User = Depends(get_current_active_user),
):
    if not ObjectId.is_valid(module_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid module ID",
        )

    module = await modules_collection.find_one(
        {"_id": ObjectId(module_id), "isDeleted": False}
    )

    if not module:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Module not found",
        )

    return {
        "moduleId": module_id,
        "moduleName": module["name"],
        "pin": module.get("modulePin"),
    }