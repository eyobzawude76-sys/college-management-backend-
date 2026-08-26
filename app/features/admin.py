from datetime import datetime
from typing import Optional, List
import random
import string
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, EmailStr
from passlib.context import CryptContext



from app.database import (
    db,
    departments_collection,
    courses_collection,
    students_collection,
    users_collection,
    audit_logs_collection,
    levels_collection,
    modules_collection,
)
from app.features.auth import User, UserRole, UserStatus
from app.shared.hashing import hash_password
from app.shared.auth import get_current_active_user
from app.shared.rbac import require_role

router = APIRouter(
    tags=["Admin"],
)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ============================================================
# HELPERS
# ============================================================

def valid_object_id(value: str) -> bool:
    return ObjectId.is_valid(value)

def oid(value: str) -> ObjectId:
    if not ObjectId.is_valid(value):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid ID: {value}",
        )
    return ObjectId(value)

async def create_audit_log(
    current_user: User,
    action: str,
    entity_type: str,
    entity_id: Optional[str] = None,
    details: Optional[dict] = None,
):
    """
    Every important Admin action is stored in audit_logs.
    """
    log = {
        "action": action,
        "entityType": entity_type,
        "entityId": entity_id,
        "performedBy": str(current_user.id),
        "performedByRole": str(current_user.role),
        "details": details or {},
        "timestamp": datetime.utcnow(),
    }

    await audit_logs_collection.insert_one(log)

def fix_url(path_str: str) -> str:
    if not path_str:
        return ""
    clean_path = str(path_str).replace("\\", "/").lstrip("/")
    if clean_path.startswith("http"):
        return clean_path
    return f"http://localhost:8000/{clean_path}"

# ============================================================
# SCHEMAS
# ============================================================

class StatusUpdateSchema(BaseModel):
    status: str

class DepartmentCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    description: Optional[str] = None

class DepartmentUpdate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    description: Optional[str] = None

class CourseCreate(BaseModel):
    departmentId: str
    name: str = Field(..., min_length=2, max_length=150)
    code: str = Field(..., min_length=2, max_length=30)

class CourseUpdate(BaseModel):
    name: str = Field(..., min_length=2, max_length=150)
    code: str = Field(..., min_length=2, max_length=30)

class StudentApproval(BaseModel):
    departmentId: str
    levelId: str
    action: str
    rejectionReason: Optional[str] = None

class DeptHeadCreate(BaseModel):
    fullName: str
    email: EmailStr
    username: str
    password: str
    courseId: str

# ============================================================
# ADMIN DASHBOARD
# ============================================================

@router.get("/dashboard")
@require_role([UserRole.ADMIN])
async def admin_dashboard(
    current_user: User = Depends(get_current_active_user),
):
    pending_students = await students_collection.count_documents({"status": "pending"})
    approved_students = await students_collection.count_documents({"status": "approved"})
    rejected_students = await students_collection.count_documents({"status": "rejected"})

    departments = await departments_collection.count_documents({"isDeleted": False})
    courses = await courses_collection.count_documents({"isDeleted": False})
    levels = await levels_collection.count_documents({"isDeleted": False})
    modules = await modules_collection.count_documents({"isDeleted": False})

    return {
        "pendingStudents": pending_students,
        "approvedStudents": approved_students,
        "rejectedStudents": rejected_students,
        "departments": departments,
        "courses": courses,
        "levels": levels,
        "modules": modules,
    }

# ============================================================
# HISTORY / AUDIT LOGS & APPROVED STUDENTS
# ============================================================

@router.get("/history")
@require_role([UserRole.ADMIN])
async def get_admin_history(
    current_user: User = Depends(get_current_active_user),
):
    """
    Fetch all audit logs performed by admins.
    """
    cursor = audit_logs_collection.find().sort("timestamp", -1)
    logs = []
    async for log in cursor:
        log["_id"] = str(log["_id"])
        logs.append(log)
    return logs

@router.get("/students/approved")
@require_role([UserRole.ADMIN])
async def get_approved_students_history(
    current_user: User = Depends(get_current_active_user),
):
    """
    Fetch all approved students with details.
    """
    pipeline = [
        {"$match": {"status": "approved"}},
        {
            "$lookup": {
                "from": "users",
                "localField": "userId",
                "foreignField": "_id",
                "as": "user",
            }
        },
        {"$unwind": "$user"},
        {
            "$lookup": {
                "from": "departments",
                "localField": "departmentId",
                "foreignField": "_id",
                "as": "department",
            }
        },
        {
            "$unwind": {
                "path": "$department",
                "preserveNullAndEmptyArrays": True,
            }
        },
        {
            "$lookup": {
                "from": "levels",
                "localField": "currentLevelId",
                "foreignField": "_id",
                "as": "level",
            }
        },
        {
            "$unwind": {
                "path": "$level",
                "preserveNullAndEmptyArrays": True,
            }
        },
        {
            "$project": {
                "_id": 1,
                "studentId": 1,
                "status": 1,
                "approvedAt": 1,
                "approvedBy": 1,
                "fullName": "$user.fullName",
                "email": "$user.email",
                "departmentName": "$department.name",
                "levelNumber": "$level.levelNumber",
            }
        },
        {"$sort": {"approvedAt": -1}},
    ]

    approved_students = []
    async for student in students_collection.aggregate(pipeline):
        student["_id"] = str(student["_id"])
        approved_students.append(student)

    return approved_students

# ============================================================
# STUDENT APPROVAL & PENDING
# ============================================================
@router.patch ("/students/{student_id}")
@require_role([UserRole.ADMIN])
async def approve_or_reject_student(
    student_id: str,
    approval: StudentApproval,
    current_user: User = Depends(get_current_active_user),
):
    if not ObjectId.is_valid(student_id):
        raise HTTPException(status_code=400, detail="Invalid student ID format")

    student_oid = ObjectId(student_id)
    student = await students_collection.find_one({"_id": student_oid})
    if not student:
        raise HTTPException(status_code=404, detail="Student registration not found")

    action = approval.action.lower().strip()
    now = datetime.utcnow()

    # ==========================================================
    # APPROVAL LOGIC (STRICT LEVEL CHECK)
    if action in ["approve", "approved"]:
        dept_id = approval.departmentId or student.get("departmentId")
        req_level_num = student.get("requestedLevelNumber") or 1
        
        dept_id_str = str(dept_id) if dept_id else ""
        dept_id_obj = ObjectId(dept_id_str) if (dept_id_str and ObjectId.is_valid(dept_id_str)) else dept_id
        
        # Level DB keessaa String fi ObjectId lachuu check gochuun barbaadi
        level_doc = await levels_collection.find_one({
            "levelNumber": req_level_num,
            "$or": [
                {"departmentId": dept_id_str},
                {"departmentId": dept_id_obj}
            ]
        })

        # 2. Level-ni yoo dhabame Bad Request deebisa
        if not level_doc:
            raise HTTPException(
                status_code=400,
                detail=f"Barataa approve gochuun hin danda'amu! Level {req_level_num} Department kanaaf DB keessatti hin uumamne."
            )

        target_level = level_doc
        level_id_to_save = target_level["_id"]
        student_id_generated = student.get("studentId")
        if not student_id_generated or student_id_generated.startswith("PENDING"):
            year = now.year
            while True:
                suffix = "".join(random.choices(string.digits, k=5))
                candidate_id = f"CAMS-{year}-{suffix}"
                exists = await students_collection.find_one({"studentId": candidate_id})
                if not exists:
                    student_id_generated = candidate_id
                    break

        if action in ["approve", "approved"]:
         user_id_val = str(current_user.id if hasattr(current_user, "id") else current_user.get("_id", current_user))
        
        # Dept ID fi Level ID qulqulleessanii String-itti jijjiiruu
        dept_id_val = str(dept_id) if dept_id else ""
        level_id_val = str(target_level["_id"]) if target_level else ""

        await students_collection.update_one(
            {"_id": student_oid},
            {
                "$set": {
                    "studentId": student_id_generated,
                    "departmentId": dept_id_val,
                    "currentLevelId": level_id_val,
                    "status": "approved",
                    "approvedBy": user_id_val,
                    "approvedAt": now,
                    "updatedAt": now
                }
            }
        )
        return {
            "message": "Student approved successfully",
            "studentId": student_id_generated,
            "status": "approved"
        }

    # =========================================================
    # REJECT LOGIC
    # =========================================================
    reason = approval.rejectionReason or "Registration rejected by administrator."
    user_id_val = str(current_user.id if hasattr(current_user, "id") else current_user.get("_id", current_user))

    await students_collection.update_one(
        {"_id": student_oid},
        {
            "$set": {
                "status": "rejected",
                "rejectionReason": reason,
                "rejectedBy": user_id_val,
                "updatedAt": now
            }
        }
    )
    return {
        "message": "Student registration rejected successfully",
        "status": "rejected"
    }
# DEPARTMENT HEAD CREATION (FLEXIBLE FIX)
# ============================================================

@router.post("/department-heads", status_code=status.HTTP_201_CREATED)
@require_role([UserRole.ADMIN])
async def create_department_head(
    data: DeptHeadCreate,
    current_user: User = Depends(get_current_active_user),
):
    # Search course if it's a valid ObjectId, otherwise treat courseId directly as string/name
    department_id = None
    if ObjectId.is_valid(data.courseId):
        course = await courses_collection.find_one({
            "_id": ObjectId(data.courseId),
            "isDeleted": False,
        })
        if course:
            department_id = course.get("departmentId")

    existing_user = await users_collection.find_one({
        "$or": [{"email": data.email}, {"username": data.username}]
    })
    if existing_user:
        raise HTTPException(
            status_code=400,
            detail="User with this email or username already exists",
        )

    hashed_pwd = hash_password(data.password)

    new_user = {
    "fullName": data.fullName,
    "email": data.email,
    "username": data.username,
    "passwordHash": hashed_pwd,      #
    "hashedPassword": hashed_pwd,    #
    "role": getattr(UserRole, "DEPARTMENT_HEAD", "department_head"),
    "courseId": data.courseId,
    "departmentId": str(department_id) if department_id else None,
    "status": UserStatus.ACTIVE,
    "isDeleted": False,              # <-- KANA DABALUURRATTI XIYYEEFFADHU!
    "createdAt": datetime.utcnow(),
}
    result = await users_collection.insert_one(new_user)
    user_id = str(result.inserted_id)

    # History/Audit Log keessatti sirriitti akka galmaa'u
    await create_audit_log(
        current_user,
        "DEPT_HEAD_CREATED",
        "user",
        user_id,
        {
            "username": data.username,
            "fullName": data.fullName,
            "courseId": data.courseId,
            "departmentId": str(department_id) if department_id else None,
        },
    )

    return {
        "message": "Department Head account created successfully",
        "userId": user_id,
        "username": data.username,
    }

# Endpoint dabalataa direct API call support gochuuf
@router.post("/create-dept-head", status_code=status.HTTP_201_CREATED)
async def create_dept_head_direct(payload: DeptHeadCreate):
    existing_user = await users_collection.find_one({"username": payload.username})
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already exists")

    hashed_password = pwd_context.hash(payload.password)

    new_head = {
        "fullName": payload.fullName,
        "email": payload.email,
        "username": payload.username,
        "hashedPassword": hashed_password,
        "role": UserRole.DEPARTMENT_HEAD,
        "assigned_course_id": payload.courseId,
        "status": UserStatus.ACTIVE,
        "createdAt": datetime.utcnow(),
    }

    result = await users_collection.insert_one(new_head)
    return {"message": "Department Head account created", "id": str(result.inserted_id)}

# ============================================================
# DEPARTMENTS
# ============================================================

@router.get("/departments")
@require_role([UserRole.ADMIN])
async def get_departments(
    current_user: User = Depends(get_current_active_user),
):
    departments = []
    cursor = departments_collection.find({"isDeleted": False}).sort("name", 1)
    async for department in cursor:
        department["_id"] = str(department["_id"])
        departments.append(department)
    return departments

@router.put("/departments/{department_id}")
@require_role([UserRole.ADMIN])
async def update_department(
    department_id: str,
    data: DepartmentUpdate,
    current_user: User = Depends(get_current_active_user),
):
    department = await departments_collection.find_one({
        "_id": oid(department_id),
        "isDeleted": False,
    })
    if not department:
        raise HTTPException(status_code=404, detail="Department not found")

    duplicate = await departments_collection.find_one({
        "_id": {"$ne": oid(department_id)},
        "name": data.name,
        "isDeleted": False,
    })
    if duplicate:
        raise HTTPException(
            status_code=400,
            detail="Another department already has this name",
        )

    await departments_collection.update_one(
        {"_id": oid(department_id)},
        {
            "$set": {
                "name": data.name,
                "description": data.description,
                "updatedAt": datetime.utcnow(),
            }
        },
    )

    await create_audit_log(
        current_user,
        "DEPARTMENT_UPDATED",
        "department",
        department_id,
        {"name": data.name},
    )

    updated = await departments_collection.find_one({"_id": oid(department_id)})
    updated["_id"] = str(updated["_id"])
    return updated

@router.delete("/departments/{department_id}", status_code=status.HTTP_204_NO_CONTENT)
@require_role([UserRole.ADMIN])
async def delete_department(
    department_id: str,
    current_user: User = Depends(get_current_active_user),
):
    department = await departments_collection.find_one({
        "_id": oid(department_id),
        "isDeleted": False,
    })
    if not department:
        raise HTTPException(status_code=404, detail="Department not found")

    await departments_collection.update_one(
        {"_id": oid(department_id)},
        {"$set": {"isDeleted": True, "deletedAt": datetime.utcnow()}},
    )

    await create_audit_log(
        current_user,
        "DEPARTMENT_DELETED",
        "department",
        department_id,
        {"name": department.get("name")},
    )

    return None

# ============================================================
# COURSES
# ============================================================

@router.post("/courses", status_code=status.HTTP_201_CREATED)
@require_role([UserRole.ADMIN])
async def create_course(
    data: CourseCreate,
    current_user: User = Depends(get_current_active_user),
):
    department = await departments_collection.find_one({
        "_id": oid(data.departmentId),
        "isDeleted": False,
    })
    if not department:
        raise HTTPException(status_code=404, detail="Department not found")

    existing = await courses_collection.find_one({
        "departmentId": oid(data.departmentId),
        "code": data.code,
        "isDeleted": False,
    })
    if existing:
        raise HTTPException(
            status_code=400,
            detail="Course code already exists in this department",
        )

    course = {
        "departmentId": oid(data.departmentId),
        "name": data.name,
        "code": data.code,
        "createdAt": datetime.utcnow(),
        "updatedAt": None,
        "isDeleted": False,
        "createdBy": str(current_user.id),
    }

    result = await courses_collection.insert_one(course)
    course["_id"] = str(result.inserted_id)
    course["departmentId"] = str(course["departmentId"])

    await create_audit_log(
        current_user,
        "COURSE_CREATED",
        "course",
        course["_id"],
        {
            "departmentId": data.departmentId,
            "name": data.name,
            "code": data.code,
        },
    )

    return course

@router.get("/courses")
@require_role([UserRole.ADMIN])
async def get_courses(
    departmentId: Optional[str] = None,
    current_user: User = Depends(get_current_active_user),
):
    query = {"isDeleted": False}
    if departmentId:
        query["departmentId"] = oid(departmentId)

    courses = []
    pipeline = [
        {"$match": query},
        {
            "$lookup": {
                "from": "departments",
                "localField": "departmentId",
                "foreignField": "_id",
                "as": "department",
            }
        },
        {
            "$unwind": {
                "path": "$department",
                "preserveNullAndEmptyArrays": True,
            }
        },
        {"$sort": {"name": 1}},
    ]

    async for course in courses_collection.aggregate(pipeline):
        course["_id"] = str(course["_id"])
        if course.get("departmentId"):
            course["departmentId"] = str(course["departmentId"])
        course["departmentName"] = course.get("department", {}).get("name")
        course.pop("department", None)
        courses.append(course)

    return courses

# ============================================================
# STUDENT PENDING FETCH WITH DYNAMIC LOOKUP
# ============================================================
@router.get("/students/pending")
async def get_pending_students():
    print(" X1X2X3 THIS IS THE ACTIVE ENDPOINT")
    raw_students = await db.students.find({"status": "pending"}).to_list(100)
    
    # 1. Fetch departments & map BOTH string ID and ObjectId
    dept_docs = await db.departments.find({}).to_list(100)
    departments = {}
    for d in dept_docs:
        dept_name = d.get("name", "Unknown Dept")
        departments[str(d["_id"])] = dept_name
        departments[d["_id"]] = dept_name  # Direct ObjectId Key

    # 2. Fetch levels & map BOTH string ID and ObjectId
    level_docs = await db.levels.find({}).to_list(100)
    levels = {}
    for l in level_docs:
        lvl_name = l.get("name") or f"Level {l.get('levelNumber', l.get('level_number', ''))}"
        levels[str(l["_id"])] = lvl_name
        levels[l["_id"]] = lvl_name  # Direct ObjectId Key

    students = []
    for s in raw_students:
        student_id_str = str(s["_id"])
        
        # --- DEPARTMENT MATCHING ---
        dept_raw = s.get("departmentId") or s.get("dept_id")
        dept_name = None
        
        if dept_raw:
            # Check string and ObjectId formats
            dept_name = departments.get(dept_raw) or departments.get(str(dept_raw))
            
        if not dept_name or dept_name == "N/A":
            dept_name = s.get("department") if (s.get("department") and s.get("department") != "N/A") else "Not Assigned"

        # --- LEVEL MATCHING ---
        level_raw = s.get("currentLevelId") or s.get("levelId")
        req_lvl = s.get("requestedLevelNumber") or s.get("requested_level_number")
        level_name = None

        if level_raw:
            level_name = levels.get(level_raw) or levels.get(str(level_raw))

        if not level_name and req_lvl is not None and str(req_lvl).strip() != "":
            level_name = f"Level {req_lvl}"

        if not level_name or level_name == "N/A":
            level_name = s.get("level") if (s.get("level") and s.get("level") != "N/A") else "Not Assigned"

        # Documents
        docs = s.get("documents", {}) if isinstance(s.get("documents"), dict) else {}
        photo_raw = docs.get("passport_photo") or s.get("photo") or s.get("photo_url") or ""

        students.append({
            "_id": student_id_str,
            "id": student_id_str,
            "fullName": s.get("full_name") or s.get("fullName") or s.get("name") or "N/A",
            "email": s.get("email", "N/A"),
            "phone": s.get("phone", ""),
            "department": dept_name,
            "departmentId": str(dept_raw) if dept_raw else "",
            "level": level_name,
            "levelId": str(level_raw) if level_raw else "",
            "photo_url": fix_url(photo_raw),
            "documents": {
                "passport_photo": fix_url(docs.get("passport_photo", "")),
                "id_document": fix_url(docs.get("id_document", "")),
                "grade12_result": fix_url(docs.get("grade12_result") or docs.get("certificate_document", "")),
                "bank_receipt": fix_url(docs.get("bank_receipt") or docs.get("receipt_document", "")),
            }
        })

    return students
      
      

@router.post("/fix-null-departments", status_code=status.HTTP_200_OK)
async def fix_null_departments_route():
    users = await users_collection.find({"role": "department_head", "departmentId": None}).to_list(100)
    updated_count = 0

    for u in users:
        course_id = u.get("courseId")
        if course_id:
            c_id = ObjectId(course_id) if isinstance(course_id, str) else course_id
            course = await courses_collection.find_one({"_id": c_id})
            
            if course and course.get("departmentId"):
                dept_id = course["departmentId"]
                dept_obj_id = ObjectId(dept_id) if isinstance(dept_id, str) else dept_id
                
                await users_collection.update_one(
                    {"_id": u["_id"]},
                    {"$set": {"departmentId": dept_obj_id}}
                )
                updated_count += 1

    return {"message": f"Successfully fixed {updated_count} department heads!"}

# ============================================================
# 2. GET ALL APPROVED STUDENTS
# ============================================================
