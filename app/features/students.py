from fastapi import (
    APIRouter,
    HTTPException,
    status,
    Depends,
    UploadFile,
    File,
    Form,
)
from bson import ObjectId
from datetime import datetime
from typing import List, Optional
import random
import string
from enum import Enum
from pathlib import Path
from pydantic import BaseModel, EmailStr
import shutil

from app.database import (
    db,
    users_collection,
    students_collection,
    departments_collection,
    levels_collection,
    record_office_vaults_collection
)
from app.core.models import User
from app.core.constants import UserRole, UserStatus
from app.shared.auth import get_current_active_user
from app.shared.rbac import require_role
from app.shared.hashing import hash_password
from fastapi import APIRouter, HTTPException
# ============================================================
# FILE UPLOAD HELPER
# ============================================================

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

async def save_upload_file(upload_file: UploadFile) -> str:
    file_path = UPLOAD_DIR / upload_file.filename
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(upload_file.file, buffer)
    return str(file_path)

# ============================================================
# STUDENT STATUS & MODELS
# ============================================================

class StudentStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"

class StudentApproval(BaseModel):
    departmentId: str
    levelId: str
    action: str  # approve / reject

# ============================================================
# ROUTER
# ============================================================

router = APIRouter()

# ============================================================
# GENERATE STUDENT ID
# ============================================================

def generate_student_id() -> str:
    year = datetime.utcnow().year
    random_suffix = "".join(
        random.choices(
            string.digits,
            k=5,
        )
    )
    return f"CAMS-{year}-{random_suffix}"

# ============================================================
# PUBLIC DEPARTMENTS FETCH ENDPOINT (FOR FRONTEND REGISTRATION)
# ============================================================

@router.get("/departments/public")
async def get_public_departments():
    """
    Frontend galmee barataaf deppartimentota/courses DB irraa dynamic-n fida.
    """
    departments = await departments_collection.find(
        {"isDeleted": False},
        {"_id": 1, "name": 1, "code": 1}
    ).to_list(100)

    return [
        {
            "id": str(dept["_id"]),
            "name": dept.get("name", ""),
            "code": dept.get("code", "")
        }
        for dept in departments
    ]

# ============================================================
# GET MODULES BY LEVEL (MAQAA GUUTUUN DHIHAATAA)
# ============================================================

@router.get("/levels/{level_id}/modules")
async def get_modules_by_level(level_id: str):
    """
    Level ID tokkoon moduulota jiran maqaa isaanii, code fi credit hour wajjin fida.
    """
    if not ObjectId.is_valid(level_id):
        raise HTTPException(status_code=400, detail="Level ID sirrii miti.")

    modules = await db["modules"].find(
        {
            "levelId": ObjectId(level_id),
            "isDeleted": False
        },
        {"_id": 1, "moduleName": 1, "name": 1, "moduleCode": 1, "creditHour": 1}
    ).to_list(100)

    return [
        {
            "id": str(mod["_id"]),
            "moduleName": mod.get("moduleName", mod.get("name", "")),
            "moduleCode": mod.get("moduleCode", ""),
            "creditHour": mod.get("creditHour", 0)
        }
        for mod in modules
    ]

# ============================================================
# REGISTER STUDENT
# ============================================================

@router.post("/register")
async def register_student(
    full_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    phone: str = Form(...),
    department_id: str = Form(...),   # MongoDB ObjectId
    requested_level: str = Form(...), # Standard Level String ("Level 1", "Level 2"...)
    passport_photo: UploadFile = File(...),
    id_document: UploadFile = File(...),
    certificate_document: UploadFile = File(...),
    receipt_document: UploadFile = File(...)
):
    existing_user = await students_collection.find_one({"email": email})
    if existing_user:
        raise HTTPException(status_code=400, detail="E-mail kun duraan galmaa'eera.")

    if not ObjectId.is_valid(department_id):
        raise HTTPException(status_code=400, detail="Department ID sirrii miti.")

    hashed_password = hash_password(password)
    passport_path = await save_upload_file(passport_photo)
    id_path = await save_upload_file(id_document)
    cert_path = await save_upload_file(certificate_document)
    receipt_path = await save_upload_file(receipt_document)

    # Extract Level Number (fkn: "Level 2" -> 2)
    level_num = int(''.join(filter(str.isdigit, requested_level))) if any(char.isdigit() for char in requested_level) else 1

    # Check if Department Head already created this level in DB
    existing_level = await levels_collection.find_one({
        "departmentId": ObjectId(department_id),
        "levelNumber": level_num,
        "isDeleted": False
    })

    current_level_id = existing_level["_id"] if existing_level else None

    new_student = {
        "full_name": full_name,
        "email": email,
        "password": hashed_password,
        "phone": phone,
        "departmentId": ObjectId(department_id),
        "requestedLevelNumber": level_num,
        "currentLevelId": current_level_id, # Level ID yoo jiraate achumaan, yoo hin jirre NULL
        "documents": {
            "passport_photo": passport_path,
            "id_document": id_path,
            "certificate_document": cert_path,
            "receipt_document": receipt_path,
        },
        "status": StudentStatus.PENDING,
        "created_at": datetime.utcnow()
    }

    result = await students_collection.insert_one(new_student)
    return {
        "message": "Barataan milkaa'inaan galmaa'eera",
        "student_id": str(result.inserted_id),
        "level_linked_immediately": current_level_id is not None
    }

# ============================================================
# DEPARTMENT HEAD LEVEL CREATION HOOK (AUTO-LINKING ENGINE)
# ============================================================

@router.post("/department-head/create-level")
@require_role([UserRole.DEPARTMENT_HEAD, UserRole.ADMIN])
async def create_level_and_autolink(
    department_id: str = Form(...),
    level_number: int = Form(...),
    level_name: str = Form(...),
    current_user: User = Depends(get_current_active_user)
):
    """
    Department Head'n level yeroo uumu barattoota Level Number sanatti 
    galmaa'anii NULL irra jiran HUNDA Otomaatikiin AUTO-LINK godha.
    """
    if not ObjectId.is_valid(department_id):
        raise HTTPException(status_code=400, detail="Invalid department ID")

    dept_obj_id = ObjectId(department_id)

    new_level_doc = {
        "departmentId": dept_obj_id,
        "levelNumber": level_number,
        "name": level_name,
        "createdBy": str(current_user.id),
        "isDeleted": False,
        "createdAt": datetime.utcnow()
    }

    level_result = await levels_collection.insert_one(new_level_doc)
    created_level_id = level_result.inserted_id

    # AUTO-LINKING: Barattoota level kana eeggataa jiran hunda UPDATE godhi
    update_result = await students_collection.update_many(
        {
            "departmentId": dept_obj_id,
            "requestedLevelNumber": level_number,
            "currentLevelId": None
        },
        {
            "$set": {
                "currentLevelId": created_level_id,
                "updatedAt": datetime.utcnow()
            }
        }
    )

    return {
        "message": "Level'n uumameera.",
        "level_id": str(created_level_id),
        "auto_linked_students_count": update_result.modified_count
    }

# ============================================================
# ADMIN APPROVE/REJECT STUDENT
# ============================================================

# ============================================================
# GET CURRENT STUDENT PROFILE
# ============================================================

@router.get(
    "/me",
    response_model=dict,
)
async def get_student_profile(
    current_user: User = Depends(get_current_active_user),
):
    # =====================================================
    # 1. ONLY STUDENT
    # =====================================================

    if current_user.role != UserRole.STUDENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a student",
        )

    # =====================================================
    # 2. CURRENT USER ID
    # =====================================================

    current_user_id = str(current_user.id)

    if not ObjectId.is_valid(current_user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user ID",
        )

    student_object_id = ObjectId(current_user_id)

    # =====================================================
    # 3. FIND STUDENT BY _id
    #
    # Student kee users collection keessa hin jiru.
    # students collection keessa qofa jira.
    # =====================================================

    student = await students_collection.find_one({
        "_id": student_object_id,
        "$or": [
            {"isDeleted": False},
            {"isDeleted": {"$exists": False}},
        ],
    })

    # =====================================================
    # 4. FALLBACK BY EMAIL
    #
    # Yoo token ID fi student _id garaagarummaa qabaate,
    # email fayyadamuun student barbaada.
    # =====================================================

    if not student and current_user.email:
        student = await students_collection.find_one({
            "email": current_user.email,
            "$or": [
                {"isDeleted": False},
                {"isDeleted": {"$exists": False}},
            ],
        })

    # =====================================================
    # 5. NOT FOUND
    # =====================================================

    if not student:
        print("\n========== STUDENT PROFILE NOT FOUND ==========")
        print("CURRENT USER ID :", current_user.id)
        print("CURRENT EMAIL   :", current_user.email)
        print("===============================================\n")

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student record not found",
        )

    # =====================================================
    # 6. GET DEPARTMENT
    # =====================================================

    department = None

    raw_department_id = (
        student.get("departmentId")
        or student.get("department_id")
    )

    if raw_department_id:

        department_id = (
            ObjectId(raw_department_id)
            if ObjectId.is_valid(str(raw_department_id))
            else None
        )

        if department_id:
            department = await departments_collection.find_one({
                "_id": department_id
            })

    # =====================================================
    # 7. GET LEVEL
    # =====================================================

    level = None

    raw_level_id = (
        student.get("currentLevelId")
        or student.get("current_level_id")
    )

    if raw_level_id:

        level_id = (
            ObjectId(raw_level_id)
            if ObjectId.is_valid(str(raw_level_id))
            else None
        )

        if level_id:
            level = await levels_collection.find_one({
                "_id": level_id
            })

    # =====================================================
    # 8. CONVERT IDS
    # =====================================================

    student_id = str(student["_id"])

    department_id = (
        str(raw_department_id)
        if raw_department_id
        else None
    )

    level_id = (
        str(raw_level_id)
        if raw_level_id
        else None
    )

    # =====================================================
    # 9. RETURN STUDENT PROFILE
    # =====================================================

    return {
        "id": student_id,

        "studentId": student.get(
            "studentId",
            student.get("student_id", ""),
        ),

        "fullName": student.get(
            "full_name",
            student.get("fullName", ""),
        ),

        "email": student.get(
            "email",
            current_user.email,
        ),

        "phone": student.get(
            "phone",
            "",
        ),

        "status": str(
            student.get("status", "")
        ).lower(),

        "departmentId": department_id,

        "department": (
            department.get("name")
            if department
            else None
        ),

        "levelId": level_id,

        "currentLevel": (
            level.get("levelNumber")
            if level
            else student.get("requestedLevelNumber")
        ),

        "levelName": (
            level.get("name")
            if level
            else None
        ),

        "requestedLevelNumber": student.get(
            "requestedLevelNumber"
        ),

        "createdAt": student.get(
            "created_at"
        ),

        "updatedAt": student.get(
            "updatedAt"
        ),
    }
# ============================================================
# STUDENT FINALIZED RESULTS
# IMPORTANT:
# - Only logged-in student
# - Only this student's result
# - Only FINALIZED committee result
# - Record Office result only
# ============================================================
# ============================================================
# STUDENT FINALIZED RESULTS
# ============================================================

@router.get(
    "/my-finalized-results",
    response_model=dict,
)
async def get_my_finalized_results(
    current_user: User = Depends(get_current_active_user),
):
    # =====================================================
    # 1. STUDENT ONLY
    # =====================================================

    if current_user.role != UserRole.STUDENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only students can view their results",
        )

    # =====================================================
    # 2. FIND LOGGED-IN STUDENT
    # =====================================================

    student = None

    # First: MongoDB _id
    if ObjectId.is_valid(str(current_user.id)):
        student = await students_collection.find_one({
            "_id": ObjectId(str(current_user.id)),
            "$or": [
                {"isDeleted": False},
                {"isDeleted": {"$exists": False}},
            ],
        })

    # Fallback: email
    if not student and current_user.email:
        student = await students_collection.find_one({
            "email": current_user.email,
            "$or": [
                {"isDeleted": False},
                {"isDeleted": {"$exists": False}},
            ],
        })

    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student profile not found",
        )

    # =====================================================
    # 3. GET THIS STUDENT'S REAL IDENTIFIERS
    # =====================================================

    student_object_id = str(student["_id"])

    student_number = student.get(
        "studentId"
    )

    student_email = student.get(
        "email"
    )

    # =====================================================
    # 4. FIND ONLY THIS STUDENT'S FINALIZED RESULT
    # =====================================================

    result_query = {
        "$and": [

            # ---------------------------------------------
            # Student identity
            # ---------------------------------------------

            {
                "$or": [
                    {
                        "studentId": student_object_id
                    },
                    {
                        "studentId": student_number
                    },
                    {
                        "studentNumber": student_number
                    },
                ]
            },

            # ---------------------------------------------
            # Committee finalized only
            # ---------------------------------------------

            {
                "status": "FINALIZED"
            },

            {
                "committeeFinalized": True
            },
        ]
    }

    records = await (
        record_office_vaults_collection
        .find(result_query)
        .sort("updatedAt", -1)
        .to_list(length=None)
    )

    # =====================================================
    # 5. DEBUG
    # =====================================================

    print("\n========== STUDENT RESULT DEBUG ==========")
    print("Logged user ID :", current_user.id)
    print("Student _id    :", student_object_id)
    print("Student number :", student_number)
    print("Student email  :", student_email)
    print("Student name   :", student.get("full_name"))
    print("Results found  :", len(records))
    print("===========================================\n")

    # =====================================================
    # 6. FORMAT RESULT
    # =====================================================

    results = []

    for record in records:

        results.append({
            "id": str(record["_id"]),

            "studentId": record.get(
                "studentId",
                student_object_id,
            ),

            "studentNumber": record.get(
                "studentNumber",
                student_number,
            ),

            "fullName": record.get(
                "fullName",
                student.get("full_name", ""),
            ),

            "departmentId": record.get(
                "departmentId"
            ),

            "levelId": record.get(
                "levelId"
            ),

            "gpa": record.get(
                "gpa",
                0,
            ),

            "status": record.get(
                "status"
            ),

            "committeeFinalized": record.get(
                "committeeFinalized",
                False,
            ),

            "committeeFinalizedAt": record.get(
                "committeeFinalizedAt"
            ),

            "modules": record.get(
                "modules",
                [],
            ),

            "totalModules": record.get(
                "totalModules",
                0,
            ),

            "passedModules": record.get(
                "passedModules",
                0,
            ),

            "totalCredits": record.get(
                "totalCredits",
                0,
            ),

            "totalQualityPoints": record.get(
                "totalQualityPoints",
                0,
            ),

            "overallStatus": record.get(
                "overallStatus"
            ),
        })

    # =====================================================
    # 7. RETURN
    # =====================================================

    return {
        "student": {
            "studentId": student_number,
            "fullName": student.get(
                "full_name",
                "",
            ),
            "email": student.get(
                "email",
                current_user.email,
            ),
        },

        "results": results,

        "count": len(results),
    }