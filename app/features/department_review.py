import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.database import (
    marks_collection,
    levels_collection,
    modules_collection,
    students_collection,
    teachers_collection,
)

from app.features.auth import User, UserRole
from app.features.marks import MarkStatus
from app.features.grading_engine import process_all_students_in_level
from app.shared.auth import get_current_active_user
from app.shared.rbac import require_role

logger = logging.getLogger(__name__)

router = APIRouter()

# ============================================================
# HELPERS
# ============================================================

def get_id_filters(
    value: Union[str, ObjectId, None]
) -> List[Union[str, ObjectId]]:
    """
    MongoDB ID String ykn ObjectId ta'uu danda'a.
    Kanaaf lamaan isaanii search godha.
    """
    if value is None:
        return []

    value_str = str(value).strip()

    if not value_str:
        return []

    filters: List[Union[str, ObjectId]] = [value_str]

    if ObjectId.is_valid(value_str):
        filters.append(ObjectId(value_str))

    return filters

def get_user_id(current_user: User) -> str:
    """
    Current user's ID gara stringtti jijjiira.
    """
    return str(
        getattr(current_user, "id", None)
        or getattr(current_user, "_id", None)
        or getattr(current_user, "userId", None)
        or ""
    )

def get_department_id(current_user: User) -> str:
    """
    Department Head irraa department ID sirriitti baasa.
    """
    department_id = (
        getattr(current_user, "departmentId", None)
        or getattr(current_user, "department_id", None)
    )

    return str(department_id) if department_id else ""

async def find_student_by_id(student_id: Any):
    """
    marks.studentId String/ObjectId lamaan deeggarama.
    """
    filters = get_id_filters(student_id)

    if not filters:
        return None

    # Yoo _id irratti argame
    student = await students_collection.find_one(
        {
            "_id": {
                "$in": [
                    value
                    for value in filters
                    if isinstance(value, ObjectId)
                ]
            }
        }
    )

    if student:
        return student

    # Yoo studentId field keessatti string/objectid ta'e
    student = await students_collection.find_one(
        {
            "studentId": {
                "$in": filters
            }
        }
    )

    return student

async def find_module_by_id(module_id: Any):
    """
    modules collection keessatti module ID String/ObjectId lamaan ilaala.
    """
    filters = get_id_filters(module_id)

    if not filters:
        return None

    object_ids = [
        value
        for value in filters
        if isinstance(value, ObjectId)
    ]

    if object_ids:
        module = await modules_collection.find_one(
            {
                "_id": {
                    "$in": object_ids
                }
            }
        )

        if module:
            return module

    module = await modules_collection.find_one(
        {
            "_id": str(module_id)
        }
    )

    return module

async def find_teacher_by_id(teacher_id: Any):
    """
    Teacher ID String/ObjectId lamaan ilaala.
    """
    filters = get_id_filters(teacher_id)

    if not filters:
        return None

    object_ids = [
        value
        for value in filters
        if isinstance(value, ObjectId)
    ]

    if object_ids:
        teacher = await teachers_collection.find_one(
            {
                "_id": {
                    "$in": object_ids
                }
            }
        )

        if teacher:
            return teacher

    teacher = await teachers_collection.find_one(
        {
            "_id": str(teacher_id)
        }
    )

    return teacher

# ============================================================
# SCHEMAS
# ============================================================

class ReviewPayload(BaseModel):
    comment: str = ""

class LevelApprovePayload(BaseModel):
    levelId: str
    comment: str = (
        "All department level marks approved by Department Head"
    )

# ============================================================
# DEPARTMENT REVIEW - PENDING
# ============================================================
#
# WORKFLOW:
#
# Department Head login
#        ↓
# Department ID from current user
#        ↓
# Only levels belonging to that department
#        ↓
# Department Head selects level
#        ↓
# Only marks belonging to:
#   department + selected level + submitted
#        ↓
# studentId → students collection
#        ↓
# moduleId → modules collection
#
# ============================================================

@router.get("/pending")
@require_role([UserRole.DEPARTMENT_HEAD])
async def get_pending_reviews(
    level_id: Optional[str] = None,
    current_user: User = Depends(get_current_active_user),
):
    department_id = get_department_id(current_user)

    if not department_id:
        raise HTTPException(
            status_code=403,
            detail="Department Head is not assigned to a department",
        )

    # ========================================================
    # STEP 1
    # Department Head's department qofa
    # ========================================================

    department_filters = get_id_filters(department_id)

    # ========================================================
    # STEP 2
    # Level filter
    #
    # Yoo level_id hin jirre:
    #   Department Head's department keessatti levelwwan qofa
    #
    # Yoo level_id jiraate:
    #   level sana department kana keessa jiraachuu qaba
    # ========================================================

    if level_id:

        level_filters = get_id_filters(level_id)

        level_query = {
            "_id": {
                "$in": [
                    value
                    for value in level_filters
                    if isinstance(value, ObjectId)
                ]
            },
            "departmentId": {
                "$in": department_filters
            },
        }

        selected_level = None

        if level_query["_id"]["$in"]:
            selected_level = await levels_collection.find_one(
                level_query
            )

        # Some DBs may store _id as string
        if not selected_level:
            selected_level = await levels_collection.find_one(
                {
                    "_id": str(level_id),
                    "departmentId": {
                        "$in": department_filters
                    },
                }
            )

        if not selected_level:
            raise HTTPException(
                status_code=403,
                detail=(
                    "This level does not belong to your department."
                ),
            )

        allowed_level_ids = [
            str(selected_level["_id"])
        ]

        if isinstance(
            selected_level.get("_id"),
            ObjectId
        ):
            allowed_level_ids.append(
                str(selected_level["_id"])
            )

    else:

        # ====================================================
        # Department Head levelwwan department isaa qofa
        # ====================================================

        allowed_level_ids = []

        level_cursor = levels_collection.find(
            {
                "departmentId": {
                    "$in": department_filters
                }
            }
        )

        async for level in level_cursor:
            if level.get("_id") is not None:
                allowed_level_ids.append(
                    str(level["_id"])
                )

        if not allowed_level_ids:
            return {
                "success": True,
                "count": 0,
                "records": [],
            }

    # ========================================================
    # STEP 3
    # Marks:
    #
    # departmentId
    # +
    # levelId
    # +
    # submitted
    #
    # qofa
    # ========================================================

    mark_query: Dict[str, Any] = {
        "departmentId": {
            "$in": department_filters
        },
        "levelId": {
            "$in": allowed_level_ids
        },
        "status": {
            "$in": [
                "submitted",
                "SUBMITTED",
            ]
        },
    }

    cursor = marks_collection.find(mark_query)

    records: List[Dict[str, Any]] = []

    # ========================================================
    # STEP 4
    # Mark tokko tokko irratti student/module/teacher
    # barbaadi
    # ========================================================

    async for mark in cursor:

        mark_id = mark.get("_id")
        student_id = mark.get("studentId")
        module_id = mark.get("moduleId")
        teacher_id = mark.get("teacherId")

        # ----------------------------------------------------
        # STUDENT
        # ----------------------------------------------------

        student = await find_student_by_id(student_id)

        if student:

            student_name = (
                student.get("fullName")
                or student.get("full_name")
                or (
                    f"{student.get('firstName', '')} "
                    f"{student.get('lastName', '')}"
                ).strip()
                or "Unknown Student"
            )

            student_code = (
                student.get("studentId")
                or student.get("studentNumber")
                or student.get("studentCode")
                or str(student_id)
            )

        else:

            student_name = "Unknown Student"

            student_code = (
                str(student_id)
                if student_id
                else ""
            )

        # ----------------------------------------------------
        # MODULE
        # ----------------------------------------------------

        module = await find_module_by_id(module_id)

        module_name = ""

        module_code = ""

        if module:

            module_name = (
                module.get("name")
                or module.get("moduleName")
                or ""
            )

            module_code = (
                module.get("code")
                or module.get("moduleCode")
                or ""
            )

        # ----------------------------------------------------
        # TEACHER
        # ----------------------------------------------------

        teacher = await find_teacher_by_id(
            teacher_id
        )

        teacher_name = ""

        if teacher:

            teacher_name = (
                teacher.get("fullName")
                or teacher.get("full_name")
                or (
                    f"{teacher.get('firstName', '')} "
                    f"{teacher.get('lastName', '')}"
                ).strip()
                or ""
            )

        # ----------------------------------------------------
        # RESPONSE
        # ----------------------------------------------------

        records.append(
            {
                "_id": str(mark_id)
                if mark_id
                else "",

                "markId": str(mark_id)
                if mark_id
                else "",

                "reviewId": str(mark_id)
                if mark_id
                else "",

                "studentId": str(student_id)
                if student_id
                else "",

                "studentName": student_name,

                "studentCode": student_code,

                "moduleId": str(module_id)
                if module_id
                else "",

                "moduleName": module_name,

                "moduleCode": module_code,

                "teacherId": str(teacher_id)
                if teacher_id
                else "",

                "teacherName": teacher_name,

                "institutionalScore": mark.get(
                    "institutionalScore",
                    mark.get("institutional", 0),
                ),

                "industrialScore": mark.get(
                    "industrialScore",
                    mark.get("industrial", 0),
                ),

                "totalScore": mark.get(
                    "totalScore",
                    0,
                ),

                "letterGrade": mark.get(
                    "letterGrade",
                    "",
                ),

                "gradePoint": mark.get(
                    "gradePoint",
                    0,
                ),

                "status": mark.get(
                    "status",
                    "submitted",
                ),

                "updatedAt": str(
                    mark.get(
                        "updatedAt",
                        ""
                    )
                ),
            }
        )

    # ========================================================
    # STUDENT NAME A-Z
    # ========================================================

    records.sort(
        key=lambda item: (
            item.get("studentName")
            or ""
        ).lower()
    )

    return {
        "success": True,
        "count": len(records),
        "records": records,
    }

# ============================================================
# APPROVE INDIVIDUAL MARK
# ============================================================

@router.post("/{mark_id}/approve")
@require_role([UserRole.DEPARTMENT_HEAD])
async def approve_mark(
    mark_id: str,
    payload: ReviewPayload,
    current_user: User = Depends(
        get_current_active_user
    ),
):

    if not ObjectId.is_valid(mark_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid Mark ID",
        )

    department_id = get_department_id(
        current_user
    )

    mark = await marks_collection.find_one(
        {
            "_id": ObjectId(mark_id),
            "departmentId": {
                "$in": get_id_filters(
                    department_id
                )
            },
        }
    )

    if not mark:
        raise HTTPException(
            status_code=404,
            detail="Mark record not found",
        )

    await marks_collection.update_one(
        {
            "_id": ObjectId(mark_id)
        },
        {
            "$set": {
                "status": "PENDING_COMMITTEE_REVIEW",
                "deptApprovedAt": datetime.utcnow(),
                "deptApprovedBy": get_user_id(
                    current_user
                ),
                "deptComment": payload.comment,
            }
        },
    )

    return {
        "success": True,
        "message": (
            "Mark approved and sent to "
            "Committee Review"
        ),
    }

# ============================================================
# APPROVE ENTIRE LEVEL
# ============================================================

@router.post("/approve-level")
@require_role([UserRole.DEPARTMENT_HEAD])
async def approve_level_results(
    payload: LevelApprovePayload,
    current_user: User = Depends(
        get_current_active_user
    ),
):

    department_id = get_department_id(
        current_user
    )

    level_id = str(payload.levelId)

    if not department_id:
        raise HTTPException(
            status_code=403,
            detail=(
                "Department Head is not assigned "
                "to a department"
            ),
        )

    # ========================================================
    # IMPORTANT:
    # Level kun department kanaa keessa jiraachuu qaba
    # ========================================================

    level_filters = get_id_filters(level_id)

    selected_level = None

    object_level_ids = [
        value
        for value in level_filters
        if isinstance(value, ObjectId)
    ]

    if object_level_ids:

        selected_level = await levels_collection.find_one(
            {
                "_id": {
                    "$in": object_level_ids
                },
                "departmentId": {
                    "$in": get_id_filters(
                        department_id
                    )
                },
            }
        )

    if not selected_level:

        selected_level = await levels_collection.find_one(
            {
                "_id": level_id,
                "departmentId": {
                    "$in": get_id_filters(
                        department_id
                    )
                },
            }
        )

    if not selected_level:
        raise HTTPException(
            status_code=403,
            detail=(
                "This level does not belong "
                "to your department."
            ),
        )

    # ========================================================
    # MARKS LEVEL KANA QOFA
    # ========================================================

    update_result = await marks_collection.update_many(
        {
            "departmentId": {
                "$in": get_id_filters(
                    department_id
                )
            },

            "levelId": {
                "$in": get_id_filters(
                    level_id
                )
            },

            "status": {
                "$in": [
                    "submitted",
                    "SUBMITTED",
                    "APPROVED_BY_DEPT",
                    "approved_by_dept",
                ]
            },
        },
        {
            "$set": {
                "status": "PENDING_COMMITTEE_REVIEW",

                "deptApprovedAt":
                    datetime.utcnow(),

                "deptApprovedBy":
                    get_user_id(
                        current_user
                    ),

                "deptComment":
                    payload.comment,
            }
        },
    )

    # ========================================================
    # GRADE ENGINE
    # ========================================================

    results = await process_all_students_in_level(
        level_id=level_id,
        department_id=str(
            department_id
        ),
        reviewer_user_id=get_user_id(
            current_user
        ),
    )

    return {
        "success": True,

        "message": (
            "Level approved successfully and "
            "Grade Engine completed automatically!"
        ),

        "updatedMarksCount":
            update_result.modified_count,

        "processedStudentsCount":
            len(results),
    }

# ============================================================
# REJECT MARK
# ============================================================

@router.post("/{mark_id}/reject")
@require_role([UserRole.DEPARTMENT_HEAD])
async def reject_mark(
    mark_id: str,
    payload: ReviewPayload,
    current_user: User = Depends(
        get_current_active_user
    ),
):

    if not ObjectId.is_valid(mark_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid Mark ID",
        )

    department_id = get_department_id(
        current_user
    )

    mark = await marks_collection.find_one(
        {
            "_id": ObjectId(mark_id),
            "departmentId": {
                "$in": get_id_filters(
                    department_id
                )
            },
        }
    )

    if not mark:
        raise HTTPException(
            status_code=404,
            detail="Mark record not found",
        )

    await marks_collection.update_one(
        {
            "_id": ObjectId(mark_id)
        },
        {
            "$set": {
                "status": "rejected",

                "deptRejectedAt":
                    datetime.utcnow(),

                "rejectionReason":
                    payload.comment,
            }
        },
    )

    return {
        "success": True,
        "message": (
            "Mark rejected and sent back "
            "to teacher"
        ),
    }

# ============================================================
# REVIEW HISTORY
# ============================================================

@router.get("/history")
@require_role([UserRole.DEPARTMENT_HEAD])
async def department_review_history(
    current_user: User = Depends(
        get_current_active_user
    ),
):

    department_id = get_department_id(
        current_user
    )

    if not department_id:
        raise HTTPException(
            status_code=403,
            detail=(
                "Department Head is not assigned "
                "to a department"
            ),
        )

    records = []

    cursor = marks_collection.find(
        {
            "departmentId": {
                "$in": get_id_filters(
                    department_id
                )
            },

            "status": {
                "$in": [
                    MarkStatus.PENDING_COMMITTEE_REVIEW.value,
                    MarkStatus.RETURNED.value,
                    MarkStatus.REJECTED.value,
                    MarkStatus.APPROVED.value,
                ]
            },
        }
    ).sort(
        "departmentReviewedAt",
        -1,
    )

    async for mark in cursor:

        student_id = mark.get(
            "studentId"
        )

        student = await find_student_by_id(
            student_id
        )

        student_name = (
            student.get("fullName")
            or student.get("full_name")
            if student
            else "Unknown Student"
        )

        records.append(
            {
                "_id": str(
                    mark["_id"]
                ),

                "studentId":
                    str(student_id)
                    if student_id
                    else "",

                "studentName":
                    student_name,

                "moduleId":
                    str(
                        mark.get(
                            "moduleId"
                        )
                    ),

                "teacherId":
                    str(
                        mark.get(
                            "teacherId"
                        )
                    ),

                "institutionalScore":
                    mark.get(
                        "institutionalScore",
                        0,
                    ),

                "industrialScore":
                    mark.get(
                        "industrialScore",
                        0,
                    ),

                "totalScore":
                    mark.get(
                        "totalScore",
                        0,
                    ),

                "letterGrade":
                    mark.get(
                        "letterGrade"
                    ),

                "gradePoint":
                    mark.get(
                        "gradePoint"
                    ),

                "status":
                    mark.get(
                        "status"
                    ),

                "departmentReviewComment":
                    mark.get(
                        "departmentReviewComment"
                    ),

                "departmentReviewedBy": 
                    mark.get(
                        "departmentReviewedBy"
                    ),

                "departmentReviewedAt":
                    mark.get(
                        "departmentReviewedAt"
                    ),
            }
        )

    return {
        "success": True,
        "count": len(records),
        "records": records,
    }