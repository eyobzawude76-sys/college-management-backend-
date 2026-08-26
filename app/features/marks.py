from datetime import datetime
from enum import Enum
from typing import List, Optional, Union

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.database import (
    academic_records_collection,
    committee_reviews_collection,
    marks_collection,
    module_assignments_collection,
    modules_collection,
    students_collection,
    teachers_collection,
)

from app.features.auth import User, UserRole
from app.shared.auth import get_current_active_user
from app.shared.rbac import require_role

from app.features.grading_engine import calculate_grade, process_student_result

# ======================================================
# STATUS ENUM
# ======================================================

class MarkStatus(str, Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    PENDING_COMMITTEE_REVIEW = "pending_committee_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    RETURNED = "returned"

# ======================================================
# PYDANTIC SCHEMAS
# ======================================================

class PinVerifyPayload(BaseModel):
    moduleId: str
    pin: str

class MarkEntry(BaseModel):
    studentId: str
    institutional: float = Field(0, ge=0, le=70)
    industrial: float = Field(0, ge=0, le=30)

class BatchMarkPayload(BaseModel):
    pin: str
    marks: List[MarkEntry]

class MarkReviewPayload(BaseModel):
    action: str = Field(..., description="approve, return, or reject")
    comment: Optional[str] = None

# ======================================================
# ROUTER CONFIGURATION
# ======================================================

router = APIRouter()

# ======================================================
# HELPER FUNCTIONS
# ======================================================

def get_id_filters(value: Union[str, ObjectId]) -> List[Union[str, ObjectId]]:
    """
    DB keessatti ID'n string ykn ObjectId ta'uu danda'a.
    Lamaan isaanii ilaalchisee search godha.
    """
    value_str = str(value)

    filters: List[Union[str, ObjectId]] = [value_str]

    if ObjectId.is_valid(value_str):
        filters.append(ObjectId(value_str))

    return filters

def get_user_id(user: User) -> str:
    return str(
        getattr(user, "id", None)
        or getattr(user, "_id", user)
    )

def get_module_name(module: dict) -> str:
    return (
        module.get("moduleName")
        or module.get("name")
        or module.get("title")
        or ""
    )

def get_module_code(module: dict) -> str:
    return (
        module.get("moduleCode")
        or module.get("code")
        or ""
    )

# ======================================================
# FIND TEACHER
# ======================================================

async def find_teacher_by_user(user: User):
    user_id_str = get_user_id(user)

    teacher_filters = [
        {"userId": user_id_str},
        {"user_id": user_id_str},
    ]

    if ObjectId.is_valid(user_id_str):
        teacher_filters.append(
            {"_id": ObjectId(user_id_str)}
        )

    teacher = await teachers_collection.find_one({
        "$or": teacher_filters,
        "isDeleted": {"$ne": True},
    })

    return teacher

# ======================================================
# VERIFY MODULE PIN
# ======================================================

@router.post("/verify-pin")
@require_role([UserRole.TEACHER])
async def verify_module_pin(
    payload: PinVerifyPayload,
    current_user: User = Depends(get_current_active_user),
):
    if not ObjectId.is_valid(payload.moduleId):
        raise HTTPException(
            status_code=400,
            detail="Invalid module ID"
        )

    teacher = await find_teacher_by_user(current_user)

    if not teacher:
        raise HTTPException(
            status_code=404,
            detail="Teacher record not found"
        )

    teacher_id = str(teacher["_id"])

    assignment = await module_assignments_collection.find_one({
        "teacherId": {"$in": get_id_filters(teacher_id)},
        "moduleId": {"$in": get_id_filters(payload.moduleId)},
        "isActive": True,
    })

    if not assignment:
        raise HTTPException(
            status_code=403,
            detail="You are not assigned to this module"
        )

    module = await modules_collection.find_one({
        "_id": ObjectId(payload.moduleId),
        "isDeleted": {"$ne": True},
    })

    if not module:
        raise HTTPException(
            status_code=404,
            detail="Module not found"
        )

    expected_pin = (
        module.get("modulePin")
        or module.get("departmentPin")
    )

    if (
        not expected_pin
        or str(expected_pin).strip() != str(payload.pin).strip()
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid module PIN"
        )

    return {
        "success": True,
        "moduleId": str(module["_id"]),
        "moduleName": get_module_name(module),
        "moduleCode": get_module_code(module),
        "message": "Module unlocked successfully",
        "accessGranted": True,
        "verifiedAt": datetime.utcnow(),
    }

# ======================================================
# GET TEACHER ASSIGNED MODULES
# ======================================================

@router.get("/teacher/modules")
@require_role([UserRole.TEACHER])
async def get_teacher_modules(
    current_user: User = Depends(get_current_active_user),
):
    teacher = await find_teacher_by_user(current_user)

    if not teacher:
        return []

    teacher_id = str(teacher["_id"])

    modules = []

    cursor = module_assignments_collection.find({
        "teacherId": {"$in": get_id_filters(teacher_id)},
        "isActive": True,
    })

    async for assignment in cursor:
        module_id = assignment.get("moduleId")

        if not module_id:
            continue

        module = None

        if ObjectId.is_valid(str(module_id)):
            module = await modules_collection.find_one({
                "_id": ObjectId(str(module_id)),
                "isDeleted": {"$ne": True},
            })
        else:
            module = await modules_collection.find_one({
                "_id": module_id,
                "isDeleted": {"$ne": True},
            })

        if module:
            modules.append({
                "moduleId": str(module["_id"]),
                "moduleName": get_module_name(module),
                "moduleCode": get_module_code(module),
                "creditHour": module.get("creditHour", 3),
                "levelId": str(module.get("levelId", "")),
                "departmentId": str(module.get("departmentId", "")),
                "isPinRequired": True,
            })

    return modules

# ======================================================
# GET STUDENTS BY MODULE
# ======================================================

@router.get("/module/{module_id}/students")
@require_role([UserRole.TEACHER])
async def get_module_students(
    module_id: str,
    current_user: User = Depends(get_current_active_user),
):
    if not ObjectId.is_valid(module_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid module ID"
        )

    teacher = await find_teacher_by_user(current_user)

    if not teacher:
        raise HTTPException(
            status_code=404,
            detail="Teacher not found"
        )

    teacher_id = str(teacher["_id"])

    assignment = await module_assignments_collection.find_one({
        "teacherId": {"$in": get_id_filters(teacher_id)},
        "moduleId": {"$in": get_id_filters(module_id)},
        "isActive": True,
    })

    if not assignment:
        raise HTTPException(
            status_code=403,
            detail="Module not assigned to you"
        )

    module = await modules_collection.find_one({
        "_id": ObjectId(module_id),
        "isDeleted": {"$ne": True},
    })

    if not module:
        raise HTTPException(
            status_code=404,
            detail="Module not found"
        )

    dept_id = str(module.get("departmentId", ""))
    level_id = str(module.get("levelId", ""))

    level_filters = get_id_filters(level_id)
    department_filters = get_id_filters(dept_id)

    student_query = {
        "status": "approved",
        "isDeleted": {"$ne": True},
        "$or": [
            {"currentLevelId": {"$in": level_filters}},
            {"levelId": {"$in": level_filters}},
        ]
    }

    if dept_id:
        student_query["departmentId"] = {
            "$in": department_filters
        }

    students_list = await students_collection.find(
        student_query
    ).to_list(length=100)

    students = []

    for student in students_list:

        student_id = str(student["_id"])

        mark = await marks_collection.find_one({
            "studentId": {"$in": get_id_filters(student_id)},
            "moduleId": {"$in": get_id_filters(module_id)},
        })

        current_status = (
            mark.get("status", MarkStatus.DRAFT.value)
            if mark
            else MarkStatus.DRAFT.value
        )

        is_locked = current_status in [
            MarkStatus.SUBMITTED.value,
            MarkStatus.PENDING_COMMITTEE_REVIEW.value,
            MarkStatus.APPROVED.value,
            MarkStatus.REJECTED.value,
        ]

        student_name = (
            student.get("fullName")
            or student.get("full_name")
            or "Unknown"
        )

        students.append({
            "studentId": student_id,
            "studentName": student_name,
            "studentCode": student.get("studentId", ""),
            "institutional": (
                mark.get("institutionalScore", "")
                if mark else ""
            ),
            "industrial": (
                mark.get("industrialScore", "")
                if mark else ""
            ),
            "totalScore": (
                mark.get("totalScore", 0)
                if mark else 0
            ),
            "grade": (
                mark.get("letterGrade")
                if mark else None
            ),
            "gradePoint": (
                mark.get("gradePoint")
                if mark else None
            ),
            "status": current_status,
            "locked": is_locked,
        })

    return {
        "module": {
            "id": str(module["_id"]),
            "name": get_module_name(module),
            "code": get_module_code(module),
            "creditHour": module.get("creditHour", 3),
        },
        "students": students,
    }

# ======================================================
# SAVE / SUBMIT MARKS
# ======================================================

@router.post("/grading/{module_id}/{action}")
@require_role([UserRole.TEACHER])
async def submit_marks(
    module_id: str,
    action: str,
    payload: BatchMarkPayload,
    current_user: User = Depends(get_current_active_user),
):
    if action not in ["draft", "submit"]:
        raise HTTPException(
            status_code=400,
            detail="Invalid action. Use draft or submit"
        )

    if not ObjectId.is_valid(module_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid module ID"
        )

    teacher = await find_teacher_by_user(current_user)

    if not teacher:
        raise HTTPException(
            status_code=404,
            detail="Teacher not found"
        )

    teacher_id = str(teacher["_id"])

    module = await modules_collection.find_one({
        "_id": ObjectId(module_id),
        "isDeleted": {"$ne": True},
    })

    if not module:
        raise HTTPException(
            status_code=404,
            detail="Module not found"
        )

    # expected_pin = (
    #     module.get("modulePin")
    #     or module.get("departmentPin")
    # )

    # if (
    #     not expected_pin
    #     or str(expected_pin).strip() != str(payload.pin).strip()
    # ):
    #     raise HTTPException(
    #         status_code=403,
    #         detail="Invalid module PIN"
    #     )

    assignment = await module_assignments_collection.find_one({
        "teacherId": {"$in": get_id_filters(teacher_id)},
        "moduleId": {"$in": get_id_filters(module_id)},
        "isActive": True,
    })

    if not assignment:
        raise HTTPException(
            status_code=403,
            detail="Module not assigned"
        )

    valid_student_ids = set()

    dept_id = str(module.get("departmentId", ""))
    level_id = str(module.get("levelId", ""))

    level_filters = get_id_filters(level_id)
    department_filters = get_id_filters(dept_id)

    student_query = {
        "status": "approved",
        "isDeleted": {"$ne": True},
        "$or": [
            {"currentLevelId": {"$in": level_filters}},
            {"levelId": {"$in": level_filters}},
        ]
    }

    if dept_id:
        student_query["departmentId"] = {
            "$in": department_filters
        }

    student_cursor = students_collection.find(
        student_query
    )

    async for student in student_cursor:
        valid_student_ids.add(str(student["_id"]))

    status_value = (
        MarkStatus.SUBMITTED.value
        if action == "submit"
        else MarkStatus.DRAFT.value
    )

    saved = 0

    for item in payload.marks:

        if item.studentId not in valid_student_ids:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Student {item.studentId} "
                    f"does not belong to this module"
                ),
            )

        existing_mark = await marks_collection.find_one({
            "studentId": {"$in": get_id_filters(item.studentId)},
            "moduleId": {"$in": get_id_filters(module_id)},
        })

        if existing_mark:

            existing_status = existing_mark.get(
                "status",
                MarkStatus.DRAFT.value
            )

            if existing_status in [
                MarkStatus.SUBMITTED.value,
                MarkStatus.PENDING_COMMITTEE_REVIEW.value,
                MarkStatus.APPROVED.value,
                MarkStatus.REJECTED.value,
            ]:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Marks for student {item.studentId} "
                        f"are already {existing_status} "
                        f"and cannot be edited"
                    ),
                )

        total_score = (
            item.institutional
            + item.industrial
        )

        letter, point ,_= calculate_grade(total_score)

        mark_data = {
            "studentId": item.studentId,
            "moduleId": module_id,
            "teacherId": teacher_id,
            "departmentId": module.get("departmentId"),
            "levelId": module.get("levelId"),

            "institutionalScore": item.institutional,
            "industrialScore": item.industrial,

            "totalScore": total_score,
            "letterGrade": letter,
            "gradePoint": point,

            "status": status_value,

            "updatedAt": datetime.utcnow(),
        }

        await marks_collection.update_one(
            {
                "studentId": item.studentId,
                "moduleId": module_id,
            },
            {
                "$set": mark_data,
                "$setOnInsert": {
                    "createdAt": datetime.utcnow()
                },
            },
            upsert=True,
        )

        saved += 1

    return {
        "success": True,
        "message": (
            f"{saved} student marks "
            f"saved successfully"
        ),
        "status": status_value,
    }

# ======================================================
# GET MARK HISTORY
# ======================================================

@router.get("/history")
@require_role([UserRole.TEACHER])
async def mark_history(
    current_user: User = Depends(get_current_active_user),
):
    teacher = await find_teacher_by_user(current_user)

    if not teacher:
        return []

    teacher_id = str(teacher["_id"])

    records = []

    cursor = marks_collection.find({
        "teacherId": {
            "$in": get_id_filters(teacher_id)
        }
    }).sort("updatedAt", -1)

    async for item in cursor:
        item["_id"] = str(item["_id"])
        records.append(item)

    return records

# ======================================================
# DEPARTMENT HEAD VIEW SUBMITTED MARKS
# ======================================================

@router.get("/department/review")
@require_role([UserRole.DEPARTMENT_HEAD])
async def get_department_mark_reviews(
    current_user: User = Depends(get_current_active_user),
):
    department_id = (
        getattr(current_user, "departmentId", None)
        or getattr(current_user, "department_id", None)
    )

    if not department_id:
        raise HTTPException(
            status_code=403,
            detail=(
                "Department Head is not assigned "
                "to a department"
            ),
        )

    department_filters = get_id_filters(
        str(department_id)
    )

    records = []

    cursor = marks_collection.find({
        "departmentId": {
            "$in": department_filters
        },
        "status": MarkStatus.SUBMITTED.value,
    }).sort("updatedAt", -1)

    async for mark in cursor:

        module = None
        student = None
        teacher = None

        module_id = str(mark.get("moduleId", ""))
        student_id = str(mark.get("studentId", ""))
        teacher_id = str(mark.get("teacherId", ""))

        if module_id:
            module = await modules_collection.find_one({
                "_id": {
                    "$in": get_id_filters(module_id)
                },
                "isDeleted": {
                    "$ne": True
                },
            })

        if student_id:
            student = await students_collection.find_one({
                "_id": {
                    "$in": get_id_filters(student_id)
                },
                "isDeleted": {
                    "$ne": True
                },
            })

        if teacher_id:
            teacher = await teachers_collection.find_one({
                "_id": {
                    "$in": get_id_filters(teacher_id)
                },
                "isDeleted": {
                    "$ne": True
                },
            })

        records.append({
            "_id": str(mark["_id"]),

            "studentId": student_id,

            "studentName": (
                (
                    student.get("fullName")
                    or student.get("full_name")
                )
                if student
                else "Unknown"
            ),

            "studentCode": (
                student.get("studentId", "")
                if student
                else ""
            ),

            "moduleId": module_id,

            "moduleName": (
                get_module_name(module)
                if module
                else ""
            ),

            "moduleCode": (
                get_module_code(module)
                if module
                else ""
            ),

            "teacherId": teacher_id,

            "teacherName": (
                teacher.get("fullName", "")
                if teacher
                else ""
            ),

            "institutionalScore": mark.get(
                "institutionalScore",
                0
            ),

            "industrialScore": mark.get(
                "industrialScore",
                0
            ),

            "totalScore": mark.get(
                "totalScore",
                0
            ),

            "letterGrade": mark.get(
                "letterGrade"
            ),

            "gradePoint": mark.get(
                "gradePoint"
            ),

            "status": mark.get(
                "status"
            ),

            "updatedAt": mark.get(
                "updatedAt"
            ),
        })

    return {
        "success": True,
        "count": len(records),
        "records": records
    }

# ======================================================
# DEPARTMENT HEAD REVIEW SINGLE MARK
# ======================================================

@router.patch("/department/review/{mark_id}")
@require_role([UserRole.DEPARTMENT_HEAD])
async def review_mark(
    mark_id: str,
    payload: MarkReviewPayload,
    current_user: User = Depends(get_current_active_user),
):
    if not ObjectId.is_valid(mark_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid mark ID"
        )

    action = payload.action.strip().lower()

    allowed_actions = [
        "approve",
        "return",
        "reject"
    ]

    if action not in allowed_actions:
        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid action. "
                "Use approve, return, or reject"
            ),
        )

    department_id = (
        getattr(current_user, "departmentId", None)
        or getattr(current_user, "department_id", None)
    )

    if not department_id:
        raise HTTPException(
            status_code=403,
            detail=(
                "Department Head is not assigned "
                "to a department"
            ),
        )

    department_filters = get_id_filters(
        str(department_id)
    )

    mark = await marks_collection.find_one({
        "_id": ObjectId(mark_id),
        "departmentId": {
            "$in": department_filters
        },
    })

    if not mark:
        raise HTTPException(
            status_code=404,
            detail="Mark not found"
        )

    if mark.get("status") != MarkStatus.SUBMITTED.value:
        raise HTTPException(
            status_code=409,
            detail=(
                "Only submitted marks "
                "can be reviewed"
            ),
        )

    # --------------------------------------------------
    # DEPARTMENT HEAD DECISION
    # --------------------------------------------------

    if action == "approve":
        new_status = MarkStatus.PENDING_COMMITTEE_REVIEW.value
    elif action == "return":
        new_status = MarkStatus.RETURNED.value
    else:
        new_status = MarkStatus.REJECTED.value

    user_id_str = get_user_id(current_user)
    now = datetime.utcnow()

    update_data = {
        "status": new_status,
        "departmentReviewedBy": user_id_str,
        "departmentReviewedAt": now,
        "departmentReviewComment": payload.comment,
        "updatedAt": now,
    }

    result = await marks_collection.update_one(
        {
            "_id": ObjectId(mark_id),
            "departmentId": {
                "$in": department_filters
            },
            "status": MarkStatus.SUBMITTED.value,
        },
        {
            "$set": update_data
        },
    )

    if result.modified_count == 0:
        raise HTTPException(
            status_code=409,
            detail=(
                "Mark was already reviewed "
                "or could not be updated"
            ),
        )

    # =========================================================
    # TRIGGER GRADE ENGINE ON APPROVAL
    # =========================================================
    if action == "approve":
        try:
            student_id = str(mark.get("studentId"))
            level_id = str(mark.get("levelId"))

            # 1. Fetch all student marks for this level
            all_student_marks = await marks_collection.find({
                "studentId": {"$in": get_id_filters(student_id)},
                "levelId": {"$in": get_id_filters(level_id)},
                "isDeleted": {"$ne": True}
            }).to_list(length=100)

            # 2. Fetch student details
            student_doc = await students_collection.find_one({
                "_id": {"$in": get_id_filters(student_id)}
            })

            student_info = {
                "_id": student_id,
                "studentNumber": student_doc.get("studentId", "N/A") if student_doc else "N/A",
                "fullName": (
                    student_doc.get("fullName") or student_doc.get("full_name") or "Student"
                ) if student_doc else "Student",
                "departmentId": str(department_id),
                "currentLevelId": level_id
            }

            # 3. Calculate GPA & Pass/Fail status
            calculated_result = process_student_result(
                student=student_info, 
                marks=all_student_marks
            )

            # 4. Save to academic_records_collection
            await academic_records_collection.update_one(
                {"studentId": student_id, "levelId": level_id},
                {"$set": {
                    **calculated_result,
                    "departmentApproved": True,
                    "departmentApprovedBy": user_id_str,
                    "departmentApprovedAt": now,
                    "updatedAt": now
                }},
                upsert=True
            )

            # 5. Push to committee_reviews_collection
            await committee_reviews_collection.update_one(
                {"studentId": student_id, "levelId": level_id},
                {"$set": {
                    "studentId": student_id,
                    "levelId": level_id,
                    "departmentId": str(department_id),
                    "gpa": calculated_result.get("gpa", 0.0),
                    "recommendation": calculated_result.get("committeeRecommendation", {}),
                    "status": "READY_FOR_COMMITTEE",
                    "updatedAt": now
                }},
                upsert=True
            )

        except Exception as e:
            print(f"Error triggering Grade Engine: {str(e)}")

    return {
        "success": True,
        "markId": mark_id,
        "action": action,
        "status": new_status,
        "message": "Mark reviewed and Grade Engine executed successfully!",
    }

# ======================================================
# DEPARTMENT HEAD REVIEW HISTORY
# ======================================================

@router.get("/department/review-history")
@require_role([UserRole.DEPARTMENT_HEAD])
async def department_review_history(
    current_user: User = Depends(get_current_active_user),
):
    department_id = (
        getattr(current_user, "departmentId", None)
        or getattr(current_user, "department_id", None)
    )

    if not department_id:
        raise HTTPException(
            status_code=403,
            detail=(
                "Department Head is not assigned "
                "to a department"
            ),
        )

    department_filters = get_id_filters(
        str(department_id)
    )

    records = []

    cursor = marks_collection.find({
        "departmentId": {
            "$in": department_filters
        },

        "status": {
            "$in": [
                MarkStatus.PENDING_COMMITTEE_REVIEW.value,
                MarkStatus.RETURNED.value,
                MarkStatus.REJECTED.value,
                MarkStatus.APPROVED.value,
            ]
        },
    }).sort("departmentReviewedAt", -1)

    async for mark in cursor:

        module = None
        student = None
        teacher = None

        module_id = str(mark.get("moduleId", ""))
        student_id = str(mark.get("studentId", ""))
        teacher_id = str(mark.get("teacherId", ""))

        if module_id:
            module = await modules_collection.find_one({
                "_id": {
                    "$in": get_id_filters(module_id)
                },
                "isDeleted": {
                    "$ne": True
                },
            })

        if student_id:
            student = await students_collection.find_one({
                "_id": {
                    "$in": get_id_filters(student_id)
                },
                "isDeleted": {
                    "$ne": True
                },
            })

        if teacher_id:
            teacher = await teachers_collection.find_one({
                "_id": {
                    "$in": get_id_filters(teacher_id)
                },
                "isDeleted": {
                    "$ne": True
                },
            })

        records.append({
            "_id": str(mark["_id"]),

            "studentId": student_id,

            "studentName": (
                (
                    student.get("fullName")
                    or student.get("full_name")
                )
                if student
                else "Unknown"
            ),

            "moduleId": module_id,

            "moduleName": (
                get_module_name(module)
                if module
                else ""
            ),

            "moduleCode": (
                get_module_code(module)
                if module
                else ""
            ),

            "teacherId": teacher_id,

            "teacherName": (
                teacher.get("fullName", "")
                if teacher
                else ""
            ),

            "institutionalScore": mark.get(
                "institutionalScore",
                0
            ),

            "industrialScore": mark.get(
                "industrialScore",
                0
            ),

            "totalScore": mark.get(
                "totalScore",
                0
            ),

            "letterGrade": mark.get(
                "letterGrade"
            ),

            "gradePoint": mark.get(
                "gradePoint"
            ),

            "status": mark.get(
                "status"
            ),

            "departmentReviewComment": mark.get(
                "departmentReviewComment"
            ),

            "departmentReviewedBy": mark.get(
                "departmentReviewedBy"
            ),

            "departmentReviewedAt": mark.get(
                "departmentReviewedAt"
            ),
        })

    return {
        "success": True,
        "count": len(records),
        "records": records
    }