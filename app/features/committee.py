import logging
from datetime import datetime
from typing import List, Optional, Union

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.database import (
    academic_records_collection,
    committee_history_collection,
    courses_collection,
    levels_collection,
    committee_reviews_collection,
    marks_collection,
    modules_collection,
    record_office_vaults_collection,
    students_collection,
)

from app.features.auth import User, UserRole
from app.features.marks import MarkStatus
from app.shared.auth import get_current_active_user
from app.shared.rbac import require_role

logger = logging.getLogger(__name__)

router = APIRouter()

# ==========================================================
# HELPERS
# ==========================================================

def get_id_filter(
    id_str: str,
) -> List[Union[str, ObjectId]]:
    """
    MongoDB ID string ykn ObjectId ta'uu danda'a.
    Kanaaf lamaan isaanii ilaalla.
    """

    values: List[Union[str, ObjectId]] = [
        str(id_str)
    ]

    if ObjectId.is_valid(str(id_str)):
        values.append(
            ObjectId(str(id_str))
        )

    return values

def get_user_id(
    current_user: User,
) -> str:
    return str(
        getattr(
            current_user,
            "id",
            None,
        )
        or getattr(
            current_user,
            "_id",
            current_user,
        )
    )

# ==========================================================
# STUDENT NAME RESOLVER
# ==========================================================

def get_student_full_name(
    student: dict,
) -> str:
    """
    students collection keessaa maqaa barataa barbaada.

    Database kee keessatti fakkeenya:

        _id: ObjectId(...)
        full_name: "Iyyoob"
        studentId: "CAMS-2026-83869"

    Kanaaf priority:

        1. full_name
        2. fullName
        3. name
        4. studentName
        5. first_name + middle_name + last_name
        6. firstName + middleName + lastName

    Yoo homtuu hin jirre:
        Student
    """

    # ------------------------------------------------------
    # 1. DATABASE FIELD: full_name
    # ------------------------------------------------------

    full_name = (
        student.get("full_name")
        or student.get("fullName")
        or student.get("name")
        or student.get("studentName")
    )

    if full_name:

        resolved = str(
            full_name
        ).strip()

        if resolved:

            return resolved

    # ------------------------------------------------------
    # 2. SNAKE CASE NAMES
    # ------------------------------------------------------

    first_name = str(
        student.get("first_name")
        or ""
    ).strip()

    middle_name = str(
        student.get("middle_name")
        or ""
    ).strip()

    last_name = str(
        student.get("last_name")
        or ""
    ).strip()

    snake_full_name = " ".join(
        part
        for part in [
            first_name,
            middle_name,
            last_name,
        ]
        if part
    ).strip()

    if snake_full_name:

        return snake_full_name

    # ------------------------------------------------------
    # 3. CAMEL CASE NAMES
    # ------------------------------------------------------

    first_name = str(
        student.get("firstName")
        or ""
    ).strip()

    middle_name = str(
        student.get("middleName")
        or ""
    ).strip()

    last_name = str(
        student.get("lastName")
        or ""
    ).strip()

    camel_full_name = " ".join(
        part
        for part in [
            first_name,
            middle_name,
            last_name,
        ]
        if part
    ).strip()

    if camel_full_name:

        return camel_full_name

    # ------------------------------------------------------
    # NOTHING FOUND
    # ------------------------------------------------------

    return "Student"

# ==========================================================
# FIND STUDENT BY ID
# ==========================================================

async def find_student_by_id(
    student_id: str,
):
    """
    Committee review keessaa studentId fudhata.

    Fakkeenya:

        committee_reviews.studentId
            ↓
        "6a7c8b096b402f0f7f390f1b"
            ↓
        students._id
            ↓
        full_name = "Iyyoob"

    String ID fi ObjectId lamaan ilaala.

    Terminal irratti lookup guutuu agarsiisa.
    """

    logger.info(
        "=================================================="
    )

    logger.info(
        "COMMITTEE STUDENT LOOKUP START"
    )

    logger.info(
        "studentId received from committee_reviews: %s",
        student_id,
    )

    # ------------------------------------------------------
    # ID FILTER
    # ------------------------------------------------------

    id_filters = get_id_filter(
        student_id
    )

    logger.info(
        "student ID filters: %s",
        id_filters,
    )

    # ------------------------------------------------------
    # FIRST LOOKUP:
    # students._id
    # ------------------------------------------------------

    logger.info(
        "Searching students_collection by _id..."
    )

    student = await students_collection.find_one(
        {
            "_id": {
                "$in": id_filters
            }
        }
    )

    logger.info(
        "LOOKUP BY students._id -> found=%s",
        bool(student),
    )

    # ------------------------------------------------------
    # SECOND LOOKUP:
    # students.studentId
    # ------------------------------------------------------

    if not student:

        logger.warning(
            "Student not found by _id."
        )

        logger.info(
            "Searching students_collection by studentId field..."
        )

        student = await students_collection.find_one(
            {
                "studentId": {
                    "$in": id_filters
                }
            }
        )

        logger.info(
            "LOOKUP BY students.studentId -> found=%s",
            bool(student),
        )

    # ------------------------------------------------------
    # RESULT
    # ------------------------------------------------------

    if student:

        resolved_name = get_student_full_name(
            student
        )

        logger.info(
            "**************** STUDENT FOUND ****************"
        )

        logger.info(
            "MongoDB _id       : %s",
            student.get("_id"),
        )

        logger.info(
            "studentId         : %s",
            student.get("studentId"),
        )

        logger.info(
            "studentNumber     : %s",
            student.get("studentNumber"),
        )

        logger.info(
            "full_name         : %s",
            student.get("full_name"),
        )

        logger.info(
            "fullName          : %s",
            student.get("fullName"),
        )

        logger.info(
            "first_name        : %s",
            student.get("first_name"),
        )

        logger.info(
            "middle_name       : %s",
            student.get("middle_name"),
        )

        logger.info(
            "last_name         : %s",
            student.get("last_name"),
        )

        logger.info(
            "RESOLVED NAME     : %s",
            resolved_name,
        )

        logger.info(
            "**************************************************"
        )

    else:

        logger.error(
            "!!!!!!!!!!!!!!!! STUDENT NOT FOUND !!!!!!!!!!!!!!!!"
        )

        logger.error(
            "studentId=%s",
            student_id,
        )

        logger.error(
            "students_collection keessatti "
            "student hin argamne.",
        )

        logger.error(
            "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
        )

    logger.info(
        "=================================================="
    )

    return student

# ==========================================================
# VALIDATE COURSE
# ==========================================================

async def validate_course(
    course_id: str,
):

    course = await courses_collection.find_one(
        {
            "_id": {
                "$in": get_id_filter(
                    course_id
                )
            },
            "isDeleted": {
                "$ne": True
            },
        }
    )

    if not course:

        raise HTTPException(
            status_code=404,
            detail="Course not found",
        )

    return course

# ==========================================================
# VALIDATE LEVEL
# ==========================================================

async def validate_level(
    level_id: str,
):

    level = await levels_collection.find_one(
        {
            "_id": {
                "$in": get_id_filter(
                    level_id
                )
            },
            "isDeleted": {
                "$ne": True
            },
        }
    )

    if not level:

        raise HTTPException(
            status_code=404,
            detail="Level not found",
        )

    return level

# ==========================================================
# PAYLOAD
# ==========================================================

class CommitteeActionPayload(
    BaseModel
):
    action: str
    notes: Optional[str] = None

# ==========================================================
# 1. COMMITTEE COURSES
# ==========================================================

@router.get("/courses")
@require_role([UserRole.COMMITTEE])
async def committee_courses(
    current_user: User = Depends(
        get_current_active_user
    ),
):

    courses = (
        await courses_collection.find(
            {
                "isDeleted": {
                    "$ne": True
                }
            }
        )
        .sort(
            "name",
            1,
        )
        .to_list(
            length=100
        )
    )

    result = []

    for course in courses:

        course_id = str(
            course["_id"]
        )

        pending_marks = (
            await marks_collection.count_documents(
                {
                    "status": MarkStatus.PENDING_COMMITTEE_REVIEW.value,
                    "isDeleted": {
                        "$ne": True
                    },
                    "courseId": {
                        "$in": get_id_filter(
                            course_id
                        )
                    },
                }
            )
        )

        result.append(
            {
                "courseId": course_id,

                "courseName": (
                    course.get("name")
                    or course.get("title")
                    or "Course"
                ),

                "courseCode": course.get(
                    "code",
                    "",
                ),

                "departmentId": str(
                    course.get(
                        "departmentId",
                        "",
                    )
                ),

                "pendingMarks": pending_marks,
            }
        )

    logger.info(
        "COMMITTEE COURSES | count=%s",
        len(result),
    )

    return result

# ==========================================================
# 2. COURSE -> LEVELS
# ==========================================================

@router.get(
    "/course/{course_id}/levels"
)
@require_role([UserRole.COMMITTEE])
async def committee_course_levels(
    course_id: str,
    current_user: User = Depends(
        get_current_active_user
    ),
):

    logger.info(
        "=========================================="
    )

    logger.info(
        "COMMITTEE COURSE LEVELS"
    )

    logger.info(
        "course_id from URL: %s",
        course_id,
    )

    logger.info(
        "course_id filters: %s",
        get_id_filter(
            course_id
        ),
    )

    course = await validate_course(
        course_id
    )

    logger.info(
        "FOUND COURSE: %s",
        course,
    )

    levels = (
        await levels_collection.find(
            {
                "courseId": {
                    "$in": get_id_filter(
                        course_id
                    )
                },
                "isDeleted": {
                    "$ne": True
                },
            }
        )
        .sort(
            "levelNumber",
            1,
        )
        .to_list(
            length=100
        )
    )

    logger.info(
        "FOUND LEVEL COUNT: %s",
        len(levels),
    )

    for level in levels:

        logger.info(
            "LEVEL FOUND | _id=%s | courseId=%s | levelNumber=%s | description=%s",
            level.get("_id"),
            level.get("courseId"),
            level.get("levelNumber"),
            level.get("description"),
        )

    result = []

    for level in levels:

        level_id = str(
            level["_id"]
        )

        pending_marks = (
            await marks_collection.count_documents(
                {
                    "levelId": {
                        "$in": get_id_filter(
                            level_id
                        )
                    },
                    "status": MarkStatus.PENDING_COMMITTEE_REVIEW.value,
                    "isDeleted": {
                        "$ne": True
                    },
                }
            )
        )

        student_reviews = (
            await committee_reviews_collection.find(
                {
                    "levelId": {
                        "$in": get_id_filter(
                            level_id
                        )
                    }
                }
            ).to_list(
                length=None
            )
        )

        result.append(
            {
                "levelId": level_id,

                "courseId": str(
                    level.get(
                        "courseId",
                        course_id,
                    )
                ),

                "departmentId": str(
                    level.get(
                        "departmentId",
                        "",
                    )
                ),

                "levelNumber": level.get(
                    "levelNumber",
                    "N/A",
                ),

                "description": level.get(
                    "description",
                    "",
                ),

                "totalMarks": pending_marks,

                "studentCount": len(
                    student_reviews
                ),
            }
        )

    logger.info(
        "FINAL LEVEL RESPONSE: %s",
        result,
    )

    logger.info(
        "=========================================="
    )

    return {
        "courseId": str(
            course["_id"]
        ),

        "courseName": (
            course.get("name")
            or course.get(
                "title",
                "",
            )
        ),

        "courseCode": course.get(
            "code",
            "",
        ),

        "levels": result,
    }

# ==========================================================
# 3. STATISTICS
# ==========================================================

@router.get("/statistics")
@require_role([UserRole.COMMITTEE])
async def committee_statistics(
    current_user: User = Depends(
        get_current_active_user
    ),
):

    pending = (
        await marks_collection.count_documents(
            {
                "status": MarkStatus.PENDING_COMMITTEE_REVIEW.value,
                "isDeleted": {
                    "$ne": True
                },
            }
        )
    )

    approved = (
        await marks_collection.count_documents(
            {
                "status": MarkStatus.APPROVED.value,
                "isDeleted": {
                    "$ne": True
                },
            }
        )
    )

    returned = (
        await marks_collection.count_documents(
            {
                "status": MarkStatus.RETURNED.value,
                "isDeleted": {
                    "$ne": True
                },
            }
        )
    )

    rejected = (
        await marks_collection.count_documents(
            {
                "status": MarkStatus.REJECTED.value,
                "isDeleted": {
                    "$ne": True
                },
            }
        )
    )

    return {
        "pendingReviews": pending,
        "approvedMarks": approved,
        "returnedMarks": returned,
        "rejectedMarks": rejected,
    }

# ==========================================================
# 4. LEVEL STUDENTS
# ==========================================================

@router.get(
    "/level/{level_id}/students"
)
@require_role([UserRole.COMMITTEE])
async def level_students(
    level_id: str,
    current_user: User = Depends(
        get_current_active_user
    ),
):

    logger.info(
        "=================================================="
    )

    logger.info(
        "COMMITTEE LEVEL STUDENTS"
    )

    logger.info(
        "level_id from URL: %s",
        level_id,
    )

    level = await validate_level(
        level_id
    )

    logger.info(
        "LEVEL FOUND: _id=%s | courseId=%s | departmentId=%s | levelNumber=%s",
        level.get("_id"),
        level.get("courseId"),
        level.get("departmentId"),
        level.get("levelNumber"),
    )

    # ------------------------------------------------------
    # COMMITTEE REVIEWS
    # ------------------------------------------------------

    reviews = (
        await committee_reviews_collection.find(
            {
                "levelId": {
                    "$in": get_id_filter(
                        level_id
                    )
                },

                "status": {
                    "$in": [
                        "READY_FOR_COMMITTEE",
                        "FINALIZED",
                    ]
                },
            }
        )
        .sort(
            "fullName",
            1,
        )
        .to_list(
            length=500
        )
    )

    logger.info(
        "COMMITTEE REVIEWS FOUND: %s",
        len(reviews),
    )

    response = []

    for review in reviews:

        # --------------------------------------------------
        # STUDENT ID FROM REVIEW
        # --------------------------------------------------

        raw_student_id = review.get(
            "studentId"
        )

        student_id = (
            str(raw_student_id)
            if raw_student_id
            else ""
        )

        logger.info(
            "------------------------------------------"
        )

        logger.info(
            "PROCESSING COMMITTEE REVIEW"
        )

        logger.info(
            "review studentId raw=%s",
            raw_student_id,
        )

        logger.info(
            "review studentId string=%s",
            student_id,
        )

        if not student_id:

            logger.warning(
                "SKIP REVIEW: studentId is missing"
            )

            continue

        # --------------------------------------------------
        # STUDENT LOOKUP
        # --------------------------------------------------

        student = await find_student_by_id(
            student_id
        )

        if not student:

            logger.error(
                "SKIP STUDENT: student not found | studentId=%s",
                student_id,
            )

            continue

        # --------------------------------------------------
        # RESOLVE REAL STUDENT NAME
        # --------------------------------------------------

        resolved_full_name = (
            get_student_full_name(
                student
            )
        )

        logger.info(
            "FINAL STUDENT NAME | ID=%s | NAME=%s",
            student_id,
            resolved_full_name,
        )

        # --------------------------------------------------
        # RESOLVE STUDENT NUMBER
        # --------------------------------------------------

        student_number = str(
            student.get(
                "studentId"
            )
            or student.get(
                "studentNumber"
            )
            or review.get(
                "studentNumber",
                "N/A",
            )
        )

        # --------------------------------------------------
        # MODULES
        # --------------------------------------------------

        modules = review.get(
            "modules",
            []
        )

        enriched_modules = []

        for module in modules:

            module_id = str(
                module.get(
                    "moduleId",
                    ""
                )
            )

            module_doc = None

            if module_id:

                module_doc = (
                    await modules_collection.find_one(
                        {
                            "_id": {
                                "$in": get_id_filter(
                                    module_id
                                )
                            },

                            "isDeleted": {
                                "$ne": True
                            },
                        }
                    )
                )

            # --------------------------------------------------
            # MARK ID
            # --------------------------------------------------

            mark_id = str(
                module.get(
                    "markId",
                    ""
                )
                or ""
            )

            # --------------------------------------------------
            # FIND MARK IF markId EMPTY
            # --------------------------------------------------

            if not mark_id and module_id:

                mark_doc = (
                    await marks_collection.find_one(
                        {
                            "studentId": {
                                "$in": get_id_filter(
                                    student_id
                                )
                            },

                            "levelId": {
                                "$in": get_id_filter(
                                    level_id
                                )
                            },

                            "moduleId": {
                                "$in": get_id_filter(
                                    module_id
                                )
                            },

                            "isDeleted": {
                                "$ne": True
                            },
                        }
                    )
                )

                if mark_doc:

                    mark_id = str(
                        mark_doc.get(
                            "_id",
                            ""
                        )
                    )

                    logger.info(
                        "MARK FOUND | studentId=%s | moduleId=%s | markId=%s",
                        student_id,
                        module_id,
                        mark_id,
                    )

            # --------------------------------------------------
            # MODULE NAME
            # --------------------------------------------------

            module_name = (
                module.get(
                    "moduleName"
                )
                or (
                    module_doc.get(
                        "moduleName"
                    )
                    if module_doc
                    else None
                )
                or (
                    module_doc.get(
                        "name"
                    )
                    if module_doc
                    else None
                )
                or "Module"
            )

            # --------------------------------------------------
            # CREDIT HOUR
            # --------------------------------------------------

            credit_hour = (
                module.get(
                    "creditHour"
                )
                or (
                    module_doc.get(
                        "creditHour",
                        1,
                    )
                    if module_doc
                    else 1
                )
                or 1
            )

            # --------------------------------------------------
            # SCORES
            # --------------------------------------------------

            institutional_score = float(
                module.get(
                    "institutionalScore",
                    module.get(
                        "institutional",
                        0,
                    ),
                )
                or 0
            )

            industrial_score = float(
                module.get(
                    "industrialScore",
                    module.get(
                        "industrial",
                        0,
                    ),
                )
                or 0
            )

            total_score = float(
                module.get(
                    "totalScore",
                    0,
                )
                or 0
            )

            # --------------------------------------------------
            # ENRICHED MODULE
            # --------------------------------------------------

            enriched_modules.append(
                {
                    **module,

                    "markId": mark_id,

                    "moduleId": module_id,

                    "moduleName": module_name,

                    "creditHour": float(
                        credit_hour
                    ),

                    "institutionalScore": (
                        institutional_score
                    ),

                    "industrialScore": (
                        industrial_score
                    ),

                    "totalScore": (
                        total_score
                    ),

                    "grade": module.get(
                        "grade"
                    ),

                    "gradePoint": module.get(
                        "gradePoint"
                    ),

                    "qualityPoint": module.get(
                        "qualityPoint"
                    ),

                    "status": module.get(
                        "status"
                    ),
                }
            )

        # --------------------------------------------------
        # MARK STATUS
        # --------------------------------------------------

        pending_count = (
            await marks_collection.count_documents(
                {
                    "studentId": {
                        "$in": get_id_filter(
                            student_id
                        )
                    },

                    "levelId": {
                        "$in": get_id_filter(
                            level_id
                        )
                    },

                    "status": (
                        MarkStatus.PENDING_COMMITTEE_REVIEW.value
                    ),

                    "isDeleted": {
                        "$ne": True
                    },
                }
            )
        )

        approved_count = (
            await marks_collection.count_documents(
                {
                    "studentId": {
                        "$in": get_id_filter(
                            student_id
                        )
                    },

                    "levelId": {
                        "$in": get_id_filter(
                            level_id
                        )
                    },

                    "status": (
                        MarkStatus.APPROVED.value
                    ),

                    "isDeleted": {
                        "$ne": True
                    },
                }
            )
        )

        total_marks = (
            await marks_collection.count_documents(
                {
                    "studentId": {
                        "$in": get_id_filter(
                            student_id
                        )
                    },

                    "levelId": {
                        "$in": get_id_filter(
                            level_id
                        )
                    },

                    "isDeleted": {
                        "$ne": True
                    },
                }
            )
        )

        # --------------------------------------------------
        # FINALIZED
        # --------------------------------------------------

        is_finalized = (
            review.get(
                "status"
            )
            == "FINALIZED"
        )

        # --------------------------------------------------
        # RESPONSE
        # --------------------------------------------------

        response.append(
            {
                "studentId": student_id,

                "studentNumber": student_number,

                # IMPORTANT:
                # students_collection irraa dhufa
                "fullName": resolved_full_name,

                "departmentId": str(
                    student.get(
                        "departmentId",
                        "",
                    )
                ),

                "courseId": str(
                    level.get(
                        "courseId",
                        "",
                    )
                ),

                "levelId": level_id,

                "gpa": float(
                    review.get(
                        "gpa",
                        0.0,
                    )
                    or 0
                ),

                "passedModules": review.get(
                    "passedModules",
                    0,
                ),

                "failedModules": review.get(
                    "failedModules",
                    0,
                ),

                "totalModules": review.get(
                    "totalModules",
                    len(
                        enriched_modules
                    ),
                ),

                "totalCredits": review.get(
                    "totalCredits",
                    0,
                ),

                "totalQualityPoints": review.get(
                    "totalQualityPoints",
                    0,
                ),

                "isPromoted": review.get(
                    "isPromoted",
                    False,
                ),

                "committeeRecommendation": (
                    review.get(
                        "committeeRecommendation",
                        {},
                    )
                ),

                "pendingMarks": pending_count,

                "approvedMarks": approved_count,

                "totalMarks": total_marks,

                "readyForFinalize": (
                    pending_count == 0
                    and not is_finalized
                ),

                "isFinalized": is_finalized,

                "status": review.get(
                    "status",
                    "READY_FOR_COMMITTEE",
                ),

                "modules": enriched_modules,
            }
        )

    logger.info(
        "FINAL COMMITTEE STUDENT RESPONSE COUNT: %s",
        len(response),
    )

    logger.info(
        "=================================================="
    )

    return response

# ==========================================================
# 5. GET ONE STUDENT MARKS
# ==========================================================

@router.get(
    "/student/{student_id}/level/{level_id}/marks"
)
@require_role([UserRole.COMMITTEE])
async def student_level_marks(
    student_id: str,
    level_id: str,
    current_user: User = Depends(
        get_current_active_user
    ),
):

    logger.info(
        "=================================================="
    )

    logger.info(
        "COMMITTEE SINGLE STUDENT MARKS"
    )

    logger.info(
        "student_id=%s | level_id=%s",
        student_id,
        level_id,
    )

    await validate_level(
        level_id
    )

    student = await find_student_by_id(
        student_id
    )

    if not student:

        raise HTTPException(
            status_code=404,
            detail="Student not found",
        )

    marks = (
        await marks_collection.find(
            {
                "studentId": {
                    "$in": get_id_filter(
                        student_id
                    )
                },

                "levelId": {
                    "$in": get_id_filter(
                        level_id
                    )
                },

                "isDeleted": {
                    "$ne": True
                },
            }
        )
        .sort(
            "createdAt",
            1,
        )
        .to_list(
            length=500
        )
    )

    logger.info(
        "STUDENT MARK COUNT: %s",
        len(marks),
    )

    result = []

    for mark in marks:

        module_id = str(
            mark.get(
                "moduleId",
                ""
            )
        )

        module = (
            await modules_collection.find_one(
                {
                    "_id": {
                        "$in": get_id_filter(
                            module_id
                        )
                    },

                    "isDeleted": {
                        "$ne": True
                    },
                }
            )
            if module_id
            else None
        )

        result.append(
            {
                "markId": str(
                    mark["_id"]
                ),

                "studentId": student_id,

                "moduleId": module_id,

                "moduleName": (
                    (
                        module.get(
                            "moduleName"
                        )
                        or module.get(
                            "name"
                        )
                        or "Module"
                    )
                    if module
                    else "Module"
                ),

                "creditHour": (
                    module.get(
                        "creditHour",
                        1,
                    )
                    if module
                    else 1
                ),

                "institutionalScore": float(
                    mark.get(
                        "institutionalScore",
                        mark.get(
                            "institutional",
                            0,
                        ),
                    )
                    or 0
                ),

                "industrialScore": float(
                    mark.get(
                        "industrialScore",
                        mark.get(
                            "industrial",
                            0,
                        ),
                    )
                    or 0
                ),

                "totalScore": float(
                    mark.get(
                        "totalScore",
                        0,
                    )
                    or 0
                ),

                "grade": mark.get(
                    "grade"
                ),

                "gradePoint": mark.get(
                    "gradePoint"
                ),

                "qualityPoint": mark.get(
                    "qualityPoint"
                ),

                "status": mark.get(
                    "status"
                ),

                "teacherId": str(
                    mark.get(
                        "teacherId",
                        "",
                    )
                ),

                "committeeNotes": mark.get(
                    "committeeNotes"
                ),
            }
        )

    full_name = get_student_full_name(
        student
    )

    student_number = str(
        student.get(
            "studentId"
        )
        or student.get(
            "studentNumber"
        )
        or "N/A"
    )

    logger.info(
        "SINGLE STUDENT RESPONSE | studentId=%s | studentNumber=%s | fullName=%s",
        student_id,
        student_number,
        full_name,
    )

    logger.info(
        "=================================================="
    )

    return {
        "studentId": student_id,

        "studentNumber": student_number,

        "fullName": full_name,

        "levelId": level_id,

        "marks": result,
    }

# ==========================================================
# 6. COMMITTEE MARK ACTION
# ==========================================================

@router.post(
    "/marks/{mark_id}/action"
)
@require_role([UserRole.COMMITTEE])
async def committee_action(
    mark_id: str,
    payload: CommitteeActionPayload,
    current_user: User = Depends(
        get_current_active_user
    ),
):

    if not ObjectId.is_valid(
        mark_id
    ):

        raise HTTPException(
            status_code=400,
            detail="Invalid Mark ID",
        )

    mark = await marks_collection.find_one(
        {
            "_id": ObjectId(
                mark_id
            )
        }
    )

    if not mark:

        raise HTTPException(
            status_code=404,
            detail="Mark not found",
        )

    if (
        mark.get("status")
        == MarkStatus.APPROVED.value
    ):

        raise HTTPException(
            status_code=409,
            detail=(
                "This mark has already been approved "
                "and cannot be edited."
            ),
        )

    if (
        mark.get("status")
        != MarkStatus.PENDING_COMMITTEE_REVIEW.value
    ):

        raise HTTPException(
            status_code=409,
            detail=(
                "Only marks pending committee review "
                "can be reviewed."
            ),
        )

    action = (
        payload.action
        .lower()
        .strip()
    )

    if action not in [
        "approve",
        "reject",
        "return",
    ]:

        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid action. "
                "Use approve, reject or return."
            ),
        )

    new_status = (
        MarkStatus.APPROVED.value
        if action == "approve"
        else MarkStatus.REJECTED.value
        if action == "reject"
        else MarkStatus.RETURNED.value
    )

    now = datetime.utcnow()

    user_id_str = get_user_id(
        current_user
    )

    update_result = (
        await marks_collection.update_one(
            {
                "_id": ObjectId(
                    mark_id
                ),

                "status": (
                    MarkStatus.PENDING_COMMITTEE_REVIEW.value
                ),
            },
            {
                "$set": {
                    "status": new_status,

                    "committeeReviewedBy": (
                        user_id_str
                    ),

                    "committeeReviewedAt": now,

                    "committeeNotes": (
                        payload.notes
                    ),

                    "updatedAt": now,
                }
            },
        )
    )

    if (
        update_result.modified_count
        == 0
    ):

        raise HTTPException(
            status_code=409,
            detail=(
                "Mark was already reviewed "
                "or could not be updated."
            ),
        )

    await committee_history_collection.insert_one(
        {
            "markId": mark_id,

            "studentId": str(
                mark.get(
                    "studentId",
                    "",
                )
            ),

            "moduleId": str(
                mark.get(
                    "moduleId",
                    "",
                )
            ),

            "levelId": str(
                mark.get(
                    "levelId",
                    "",
                )
            ),

            "action": action.upper(),

            "notes": payload.notes,

            "committeeUserId": (
                user_id_str
            ),

            "createdAt": now,
        }
    )

    return {
        "success": True,

        "message": (
            f"Mark successfully {action}ed"
        ),

        "markId": mark_id,

        "status": new_status,
    }

# ==========================================================
# 7. CHECK STUDENT READY
# ==========================================================

async def check_student_ready(
    student_id: str,
    level_id: str,
) -> bool:

    pending_marks = (
        await marks_collection.count_documents(
            {
                "studentId": {
                    "$in": get_id_filter(
                        student_id
                    )
                },

                "levelId": {
                    "$in": get_id_filter(
                        level_id
                    )
                },

                "status": (
                    MarkStatus.PENDING_COMMITTEE_REVIEW.value
                ),

                "isDeleted": {
                    "$ne": True
                },
            }
        )
    )

    return pending_marks == 0

# ==========================================================
# 8. FINALIZE LEVEL
# ==========================================================

@router.post(
    "/finalize-level/{level_id}"
)
@require_role([UserRole.COMMITTEE])
async def finalize_level(
    level_id: str,
    current_user: User = Depends(
        get_current_active_user
    ),
):

    level = await validate_level(
        level_id
    )

    course_id = str(
        level.get(
            "courseId",
            ""
        )
    )

    reviews = (
        await committee_reviews_collection.find(
            {
                "levelId": {
                    "$in": get_id_filter(
                        level_id
                    )
                },

                "status": (
                    "READY_FOR_COMMITTEE"
                ),
            }
        )
        .to_list(
            length=None
        )
    )

    if not reviews:

        raise HTTPException(
            status_code=400,
            detail=(
                "No student reviews found to "
                "finalize for this level."
            ),
        )

    now = datetime.utcnow()

    user_id_str = get_user_id(
        current_user
    )

    finalized = 0
    skipped = 0

    for review in reviews:

        student_id = str(
            review.get(
                "studentId",
                ""
            )
        )

        if not student_id:

            skipped += 1

            logger.warning(
                "FINALIZE SKIPPED: studentId missing"
            )

            continue

        ready = await check_student_ready(
            student_id,
            level_id,
        )

        if not ready:

            skipped += 1

            logger.warning(
                "FINALIZE SKIPPED: pending marks | studentId=%s",
                student_id,
            )

            continue

        student = await find_student_by_id(
            student_id
        )

        if not student:

            skipped += 1

            continue

        student_name = (
            get_student_full_name(
                student
            )
        )

        student_number = str(
            student.get(
                "studentId"
            )
            or student.get(
                "studentNumber"
            )
            or "N/A"
        )

        summary = {

            "studentId": student_id,

            "studentNumber": student_number,

            "fullName": student_name,

            "departmentId": str(
                student.get(
                    "departmentId",
                    "",
                )
            ),

            "courseId": course_id,

            "levelId": level_id,

            "gpa": review.get(
                "gpa",
                0,
            ),

            "passedModules": review.get(
                "passedModules",
                0,
            ),

            "failedModules": review.get(
                "failedModules",
                0,
            ),

            "totalModules": review.get(
                "totalModules",
                0,
            ),

            "totalCredits": review.get(
                "totalCredits",
                0,
            ),

            "totalQualityPoints": review.get(
                "totalQualityPoints",
                0,
            ),

            "isPromoted": review.get(
                "isPromoted",
                False,
            ),

            "committeeRecommendation": (
                review.get(
                    "committeeRecommendation",
                    {},
                )
            ),

            "modules": review.get(
                "modules",
                [],
            ),
        }

        # ==================================================
        # ACADEMIC RECORD
        # ==================================================

        await academic_records_collection.update_one(
            {
                "studentId": student_id,

                "levelId": level_id,
            },

            {
                "$set": {
                    **summary,

                    "status": (
                        "READY_FOR_RECORD_OFFICE"
                    ),

                    "committeeApproved": True,

                    "committeeApprovedBy": (
                        user_id_str
                    ),

                    "committeeApprovedAt": now,

                    "isLocked": True,

                    "updatedAt": now,
                },

                "$setOnInsert": {
                    "createdAt": now,
                },
            },

            upsert=True,
        )

        # ==================================================
        # RECORD OFFICE VAULT
        # ==================================================

        await record_office_vaults_collection.update_one(
            {
                "studentId": student_id,

                "levelId": level_id,
            },

            {
                "$set": {
                    **summary,

                    "userId": str(
                        student.get(
                            "userId",
                            "",
                        )
                    ),

                    "committeeApproved": True,

                    "committeeApprovedBy": (
                        user_id_str
                    ),

                    "committeeApprovedAt": now,

                    "isLocked": True,

                    "updatedAt": now,
                },

                "$setOnInsert": {
                    "createdAt": now,
                },
            },

            upsert=True,
        )

        # ==================================================
        # COMMITTEE REVIEW -> FINALIZED
        # ==================================================

        await committee_reviews_collection.update_one(
            {
                "studentId": student_id,

                "levelId": level_id,

                "status": (
                    "READY_FOR_COMMITTEE"
                ),
            },

            {
                "$set": {
                    "status": "FINALIZED",

                    "committeeFinalized": True,

                    "committeeFinalizedBy": (
                        user_id_str
                    ),

                    "committeeFinalizedAt": now,

                    "updatedAt": now,
                }
            },
        )

        # ==================================================
        # MARKS -> LOCK
        # ==================================================

        await marks_collection.update_many(
            {
                "studentId": {
                    "$in": get_id_filter(
                        student_id
                    )
                },

                "levelId": {
                    "$in": get_id_filter(
                        level_id
                    )
                },

                "status": {
                    "$in": [
                        MarkStatus.APPROVED.value,
                    ]
                },

                "isDeleted": {
                    "$ne": True
                },
            },

            {
                "$set": {
                    "isLocked": True,

                    "finalizedAt": now,

                    "finalizedBy": (
                        user_id_str
                    ),

                    "updatedAt": now,
                }
            },
        )

        # ==================================================
        # HISTORY
        # ==================================================

        await committee_history_collection.insert_one(
            {
                "studentId": student_id,

                "levelId": level_id,

                "courseId": course_id,

                "action": "FINALIZE_LEVEL",

                "committeeUserId": (
                    user_id_str
                ),

                "createdAt": now,
            }
        )

        finalized += 1

        logger.info(
            "LEVEL FINALIZED | studentId=%s | studentName=%s | levelId=%s",
            student_id,
            student_name,
            level_id,
        )

    return {

        "success": True,

        "courseId": course_id,

        "levelId": level_id,

        "finalizedStudents": finalized,

        "skippedStudents": skipped,

        "message": (
            "Committee finalized the level. "
            "Approved academic records were sent "
            "to Record Office Vault and locked."
        ),
    }

# ==========================================================
# 9. COMMITTEE HISTORY
# ==========================================================

@router.get("/history")
@require_role([UserRole.COMMITTEE])
async def committee_history(
    current_user: User = Depends(
        get_current_active_user
    ),
):

    records = []

    cursor = (
        committee_history_collection.find(
            {}
        )
        .sort(
            "createdAt",
            -1,
        )
    )

    async for item in cursor:

        item["_id"] = str(
            item["_id"]
        )

        if item.get("studentId"):

            item["studentId"] = str(
                item["studentId"]
            )

        if item.get("moduleId"):

            item["moduleId"] = str(
                item["moduleId"]
            )

        if item.get("levelId"):

            item["levelId"] = str(
                item["levelId"]
            )

        records.append(
            item
        )

    return records