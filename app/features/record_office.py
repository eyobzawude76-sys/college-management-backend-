from datetime import datetime
from typing import Optional, List

from bson import ObjectId

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.database import (
    record_office_vaults_collection,
    students_collection,
    users_collection,
    levels_collection,
    courses_collection,
    departments_collection,
    committee_reviews_collection,
)

from app.features.auth import User, UserRole
from app.shared.auth import get_current_active_user
from app.shared.rbac import require_role

router = APIRouter()
   


# ==========================================================
# Constants
# ==========================================================

FINALIZED_STATUS = "FINALIZED"

# ==========================================================
# Record Vault Model
# ==========================================================

class RecordVault(BaseModel):

    id: Optional[str] = Field(
        None,
        alias="_id",
    )

    studentId: str

    levelId: str

    gpa: float

    transcriptData: List[dict]

    # Committee information
    committeeApproved: bool = False

    committeeApprovedBy: Optional[str] = None

    committeeApprovedAt: Optional[datetime] = None

    # Record Office
    approvedBy: Optional[str] = None

    lockedAt: Optional[datetime] = None

    isLocked: bool = False

    createdAt: datetime = Field(
        default_factory=datetime.utcnow,
    )

    class Config:
        populate_by_name = True

# ==========================================================
# Helper: ObjectId validation
# ==========================================================

def valid_object_id(value: str) -> bool:
    return ObjectId.is_valid(value)

# ==========================================================
# Helper: Convert MongoDB ID
# ==========================================================

def string_id(value) -> Optional[str]:

    if value is None:
        return None

    return str(value)

# ==========================================================
# Student View Transcript
# Student can see own finalized records
# ==========================================================

@router.get(
    "/my-transcript"
)
@require_role([
    UserRole.STUDENT
])
async def my_transcript(
    current_user: User = Depends(
        get_current_active_user
    ),
):

    student = await students_collection.find_one({
        "userId": ObjectId(current_user.id)
    })

    if not student:

        raise HTTPException(
            status_code=404,
            detail="Student profile not found",
        )

    student_object_id = str(
        student["_id"]
    )

    records = await committee_reviews_collection.find({
        "studentId": student_object_id,
        "status": FINALIZED_STATUS,
    }).to_list(None)

    result = []

    for record in records:

        record["_id"] = str(
            record["_id"]
        )

        result.append(record)

    return result

# ==========================================================
# Record Office Directory
#
# IMPORTANT:
# Only committee_reviews.status == FINALIZED
# ==========================================================

@router.get(
    "/directory"
)
@require_role([
    UserRole.RECORD_OFFICE
])
async def student_directory(
    current_user: User = Depends(
        get_current_active_user
    ),
):

    result = []

    # ------------------------------------------------------
    # FINALIZED committee records ONLY
    # ------------------------------------------------------

    cursor = committee_reviews_collection.find({
        "status": FINALIZED_STATUS
    })

    async for review in cursor:

        student_id = review.get(
            "studentId"
        )

        if not student_id:
            continue

        # --------------------------------------------------
        # Find student
        # --------------------------------------------------

        student = None

        if valid_object_id(student_id):

            student = await students_collection.find_one({
                "_id": ObjectId(student_id)
            })

        if not student:

            student = await students_collection.find_one({
                "studentId": student_id
            })

        if not student:
            continue

        # --------------------------------------------------
        # Find user
        # --------------------------------------------------

        user = None

        user_id = student.get(
            "userId"
        )

        if user_id and valid_object_id(
            str(user_id)
        ):

            user = await users_collection.find_one({
                "_id": ObjectId(
                    str(user_id)
                )
            })

        # --------------------------------------------------
        # Department
        # --------------------------------------------------

        department = None

        department_id = student.get(
            "departmentId"
        )

        if department_id:

            if valid_object_id(
                str(department_id)
            ):

                department = await departments_collection.find_one({
                    "_id": ObjectId(
                        str(department_id)
                    )
                })

            if not department:

                department = await departments_collection.find_one({
                    "departmentId": str(
                        department_id
                    )
                })

        # --------------------------------------------------
        # Course
        #
        # Your student document has departmentId,
        # and course document has departmentId.
        # --------------------------------------------------

        course = None

        if department_id:

            if valid_object_id(
                str(department_id)
            ):

                course = await courses_collection.find_one({
                    "departmentId": ObjectId(
                        str(department_id)
                    ),
                    "isDeleted": {
                        "$ne": True
                    }
                })

            if not course:

                course = await courses_collection.find_one({
                    "departmentId": str(
                        department_id
                    ),
                    "isDeleted": {
                        "$ne": True
                    }
                })

        # --------------------------------------------------
        # Level
        # --------------------------------------------------

        level = None

        level_id = review.get(
            "levelId"
        )

        if not level_id:

            level_id = student.get(
                "currentLevelId"
            )

        if level_id:

            if valid_object_id(
                str(level_id)
            ):

                level = await levels_collection.find_one({
                    "_id": ObjectId(
                        str(level_id)
                    )
                })

            if not level:

                level = await levels_collection.find_one({
                    "levelId": str(
                        level_id
                    )
                })

        # --------------------------------------------------
        # Full Name
        #
        # Your students collection uses full_name.
        # --------------------------------------------------

        full_name = (
            student.get("full_name")
            or student.get("fullName")
            or (
                user.get("fullName")
                if user
                else None
            )
            or (
                user.get("full_name")
                if user
                else None
            )
            or review.get("fullName")
            or "Unknown"
        )

        # --------------------------------------------------
        # Level name
        # --------------------------------------------------

        level_name = None

        if level:

            level_name = (
                level.get("name")
                or level.get("title")
                or level.get("levelName")
                or level.get("levelNumber")
            )

        if not level_name:

            level_name = review.get(
                "levelId"
            )

        # --------------------------------------------------
        # Department name
        # --------------------------------------------------

        department_name = None

        if department:

            department_name = (
                department.get("name")
                or department.get("title")
                or department.get("departmentName")
            )

        if not department_name:

            department_name = (
                review.get("departmentName")
                or "Unknown"
            )

        # --------------------------------------------------
        # Course name
        # --------------------------------------------------

        course_name = None

        if course:

            course_name = (
                course.get("title")
                or course.get("name")
                or course.get("courseName")
            )

        if not course_name:

            course_name = (
                review.get("courseName")
                or "Unknown"
            )

        # --------------------------------------------------
        # Add student to directory
        # --------------------------------------------------

        result.append({

            "_id": str(
                student["_id"]
            ),

            "studentId": str(
                student["_id"]
            ),

            "studentNumber": (
                student.get("studentId")
                or review.get("studentNumber")
            ),

            "fullName": full_name,

            "email": (
                user.get("email")
                if user
                else student.get("email")
            ),

            "departmentId": string_id(
                department_id
            ),

            "departmentName": department_name,

            "courseId": (
                str(course["_id"])
                if course
                else None
            ),

            "courseName": course_name,

            "levelId": string_id(
                level_id
            ),

            "levelName": level_name,

            "committeeStatus": FINALIZED_STATUS,

            "overallStatus": review.get(
                "overallStatus"
            ),

            "gpa": review.get(
                "gpa"
            ),

            "reviewId": str(
                review["_id"]
            ),

            "committeeFinalized": review.get(
                "committeeFinalized",
                True,
            ),

            "committeeFinalizedAt": review.get(
                "committeeFinalizedAt"
            ),
        })

    # ------------------------------------------------------
    # A-Z sorting
    # ------------------------------------------------------

    result.sort(
        key=lambda item: (
            item.get("fullName")
            or ""
        ).lower()
    )

    return result

# ==========================================================
# Record Office Student Detail
#
# FINALIZED records ONLY
# ==========================================================

@router.get(
    "/students/{student_id}"
)
@require_role([
    UserRole.RECORD_OFFICE,
    UserRole.ADMIN
])
async def student_detail(
    student_id: str,
    current_user: User = Depends(
        get_current_active_user
    ),
):

    # ------------------------------------------------------
    # Find student
    # ------------------------------------------------------

    student = None

    if valid_object_id(student_id):

        student = await students_collection.find_one({
            "_id": ObjectId(student_id)
        })

    if not student:

        student = await students_collection.find_one({
            "studentId": student_id
        })

    if not student:

        raise HTTPException(
            status_code=404,
            detail="Student not found",
        )

    mongo_student_id = str(
        student["_id"]
    )

    # ------------------------------------------------------
    # IMPORTANT:
    # FINALIZED ONLY
    # ------------------------------------------------------

    reviews = await committee_reviews_collection.find({
        "studentId": mongo_student_id,
        "status": FINALIZED_STATUS,
    }).sort(
        "createdAt",
        -1,
    ).to_list(None)

    # ------------------------------------------------------
    # If studentId inside committee review uses
    # studentNumber instead of MongoDB _id
    # ------------------------------------------------------

    if not reviews:

        reviews = await committee_reviews_collection.find({
            "studentId": student.get(
                "studentId"
            ),
            "status": FINALIZED_STATUS,
        }).sort(
            "createdAt",
            -1,
        ).to_list(None)

    if not reviews:

        raise HTTPException(
            status_code=404,
            detail=(
                "No FINALIZED committee record "
                "found for this student"
            ),
        )

    review = reviews[0]

    # ------------------------------------------------------
    # User
    # ------------------------------------------------------

    user = None

    user_id = student.get(
        "userId"
    )

    if user_id and valid_object_id(
        str(user_id)
    ):

        user = await users_collection.find_one({
            "_id": ObjectId(
                str(user_id)
            )
        })

    # ------------------------------------------------------
    # Department
    # ------------------------------------------------------

    department = None

    department_id = (
        student.get("departmentId")
        or review.get("departmentId")
    )

    if department_id:

        if valid_object_id(
            str(department_id)
        ):

            department = await departments_collection.find_one({
                "_id": ObjectId(
                    str(department_id)
                )
            })

        if not department:

            department = await departments_collection.find_one({
                "departmentId": str(
                    department_id
                )
            })

    # ------------------------------------------------------
    # Course
    # ------------------------------------------------------

    course = None

    if department_id:

        if valid_object_id(
            str(department_id)
        ):

            course = await courses_collection.find_one({
                "departmentId": ObjectId(
                    str(department_id)
                ),
                "isDeleted": {
                    "$ne": True
                }
            })

        if not course:

            course = await courses_collection.find_one({
                "departmentId": str(
                    department_id
                ),
                "isDeleted": {
                    "$ne": True
                }
            })

    # ------------------------------------------------------
    # Level
    # ------------------------------------------------------

    level_id = (
        review.get("levelId")
        or student.get("currentLevelId")
    )

    level = None

    if level_id:

        if valid_object_id(
            str(level_id)
        ):

            level = await levels_collection.find_one({
                "_id": ObjectId(
                    str(level_id)
                )
            })

        if not level:

            level = await levels_collection.find_one({
                "levelId": str(
                    level_id
                )
            })

    # ------------------------------------------------------
    # Student name
    # ------------------------------------------------------

    full_name = (
        student.get("full_name")
        or student.get("fullName")
        or (
            user.get("fullName")
            if user
            else None
        )
        or (
            user.get("full_name")
            if user
            else None
        )
        or review.get("fullName")
        or "Unknown"
    )

    # ------------------------------------------------------
    # Department name
    # ------------------------------------------------------

    department_name = (
        department.get("name")
        if department
        else None
    )

    if not department_name:

        department_name = (
            review.get("departmentName")
            or "Unknown"
        )

    # ------------------------------------------------------
    # Course name
    # ------------------------------------------------------

    course_name = (
        course.get("title")
        if course
        else None
    )

    if not course_name and course:

        course_name = course.get(
            "name"
        )

    if not course_name:

        course_name = (
            review.get("courseName")
            or "Unknown"
        )

    # ------------------------------------------------------
    # Level name
    # ------------------------------------------------------

    level_name = None

    if level:

        level_name = (
            level.get("name")
            or level.get("title")
            or level.get("levelName")
        )

        if not level_name:

            level_number = level.get(
                "levelNumber"
            )

            if level_number is not None:

                level_name = (
                    f"Level {level_number}"
                )

    if not level_name:

        level_name = (
            review.get("levelName")
            or "Unknown"
        )

    # ------------------------------------------------------
    # Modules
    # ------------------------------------------------------

    modules = []

    for module in review.get(
        "modules",
        []
    ):

        modules.append({

            "moduleId": module.get(
                "moduleId"
            ),

            "moduleName": module.get(
                "moduleName"
            ),

            "creditHour": module.get(
                "creditHour",
                0
            ),

            "institutional": module.get(
                "institutional"
            ),

            "industrial": module.get(
                "industrial"
            ),

            "totalScore": module.get(
                "totalScore"
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

            "markAvailable": module.get(
                "markAvailable",
                True,
            ),
        })

    # ------------------------------------------------------
    # Return complete Record Office detail
    # ------------------------------------------------------

    return {

        "studentInformation": {

            "studentId": mongo_student_id,

            "studentNumber": (
                student.get("studentId")
                or review.get("studentNumber")
            ),

            "fullName": full_name,

            "email": (
                user.get("email")
                if user
                else student.get("email")
            ),

            "departmentId": string_id(
                department_id
            ),

            "departmentName": department_name,

            "courseId": (
                str(course["_id"])
                if course
                else None
            ),

            "courseName": course_name,

            "levelId": string_id(
                level_id
            ),

            "levelName": level_name,
        },

        "committee": {

            "status": FINALIZED_STATUS,

            "committeeFinalized": review.get(
                "committeeFinalized",
                True,
            ),

            "committeeFinalizedAt": review.get(
                "committeeFinalizedAt"
            ),

            "committeeFinalizedBy": review.get(
                "committeeFinalizedBy"
            ),

            "overallStatus": review.get(
                "overallStatus"
            ),

            "committeeRecommendation": review.get(
                "committeeRecommendation"
            ),
        },

        "academicSummary": {

            "gpa": review.get(
                "gpa",
                0
            ),

            "totalCredits": review.get(
                "totalCredits",
                0
            ),

            "totalModules": review.get(
                "totalModules",
                0
            ),

            "passedModules": review.get(
                "passedModules",
                0
            ),

            "failedModules": review.get(
                "failedModules",
                0
            ),

            "totalQualityPoints": review.get(
                "totalQualityPoints",
                0
            ),

            "overallStatus": review.get(
                "overallStatus"
            ),
        },

        "modules": modules,

        "reviewId": str(
            review["_id"]
        ),
    }

# ==========================================================
# Record Office Dashboard
#
# FINALIZED records waiting for Record Office lock
# ==========================================================

@router.get(
    "/pending"
)
@require_role([
    UserRole.RECORD_OFFICE
])
async def pending_records(
    current_user: User = Depends(
        get_current_active_user
    ),
):

    result = []

    cursor = committee_reviews_collection.find({
        "status": FINALIZED_STATUS
    })

    async for review in cursor:

        student_id = review.get(
            "studentId"
        )

        if not student_id:
            continue

        student = None

        if valid_object_id(student_id):

            student = await students_collection.find_one({
                "_id": ObjectId(student_id)
            })

        if not student:

            student = await students_collection.find_one({
                "studentId": student_id
            })

        if not student:
            continue

        # --------------------------------------------------
        # Check if already locked
        # --------------------------------------------------

        existing_vault = await record_office_vaults_collection.find_one({

            "studentId": str(
                student["_id"]
            ),

            "levelId": str(
                review.get("levelId")
            ),

            "isLocked": True,
        })

        if existing_vault:

            continue

        result.append({

            "reviewId": str(
                review["_id"]
            ),

            "studentId": str(
                student["_id"]
            ),

            "studentNumber": (
                student.get("studentId")
                or review.get("studentNumber")
            ),

            "fullName": (
                student.get("full_name")
                or student.get("fullName")
                or review.get("fullName")
                or "Unknown"
            ),

            "levelId": review.get(
                "levelId"
            ),

            "gpa": review.get(
                "gpa",
                0
            ),

            "overallStatus": review.get(
                "overallStatus"
            ),

            "committeeStatus": FINALIZED_STATUS,
        })

    result.sort(
        key=lambda item: (
            item.get("fullName")
            or ""
        ).lower()
    )

    return result

# ==========================================================
# Review Queue
# FINALIZED records only
# ==========================================================

@router.get(
    "/review-queue"
)
@require_role([
    UserRole.RECORD_OFFICE
])
async def record_review_queue(
    current_user: User = Depends(
        get_current_active_user
    ),
):

    result = []

    cursor = committee_reviews_collection.find({
        "status": FINALIZED_STATUS
    })

    async for item in cursor:

        item["_id"] = str(
            item["_id"]
        )

        result.append(item)

    return result

# ==========================================================
# Create Official Record
#
# FINALIZED committee record -> Record Office Vault
# ==========================================================

@router.post(
    "/create/{review_id}"
)
@require_role([
    UserRole.RECORD_OFFICE
])
async def create_official_record(
    review_id: str,
    current_user: User = Depends(
        get_current_active_user
    ),
):

    if not ObjectId.is_valid(
        review_id
    ):

        raise HTTPException(
            status_code=400,
            detail="Invalid committee review id",
        )

    # ------------------------------------------------------
    # FINALIZED ONLY
    # ------------------------------------------------------

    review = await committee_reviews_collection.find_one({
        "_id": ObjectId(review_id),
        "status": FINALIZED_STATUS,
    })

    if not review:

        raise HTTPException(
            status_code=404,
            detail=(
                "FINALIZED committee record "
                "not found"
            ),
        )

    student_id = review.get(
        "studentId"
    )

    level_id = review.get(
        "levelId"
    )

    if not student_id or not level_id:

        raise HTTPException(
            status_code=400,
            detail=(
                "Student ID and Level ID "
                "are required"
            ),
        )

    # ------------------------------------------------------
    # Prevent duplicate vault
    # ------------------------------------------------------

    existing = await record_office_vaults_collection.find_one({

        "studentId": str(student_id),

        "levelId": str(level_id),
    })

    if existing:

        return {

            "success": True,

            "message": (
                "Official record already exists"
            ),

            "vaultId": str(
                existing["_id"]
            ),

            "isLocked": existing.get(
                "isLocked",
                False
            ),
        }

    # ------------------------------------------------------
    # Create official snapshot
    # ------------------------------------------------------

    vault_document = {

        "studentId": str(
            student_id
        ),

        "levelId": str(
            level_id
        ),

        "gpa": review.get(
            "gpa",
            0
        ),

        "transcriptData": review.get(
            "modules",
            []
        ),

        # Committee snapshot
        "committeeApproved": True,

        "committeeApprovedBy": review.get(
            "committeeFinalizedBy"
        ),

        "committeeApprovedAt": review.get(
            "committeeFinalizedAt"
        ),

        "committeeStatus": FINALIZED_STATUS,

        # Record Office
        "approvedBy": None,

        "lockedAt": None,

        "isLocked": False,

        "createdAt": datetime.utcnow(),

        # Additional official summary
        "studentNumber": review.get(
            "studentNumber"
        ),

        "fullName": review.get(
            "fullName"
        ),

        "overallStatus": review.get(
            "overallStatus"
        ),

        "totalCredits": review.get(
            "totalCredits",
            0
        ),

        "totalModules": review.get(
            "totalModules",
            0
        ),

        "passedModules": review.get(
            "passedModules",
            0
        ),

        "failedModules": review.get(
            "failedModules",
            0
        ),

        "totalQualityPoints": review.get(
            "totalQualityPoints",
            0
        ),
    }

    insert_result = (
        await record_office_vaults_collection.insert_one(
            vault_document
        )
    )

    return {

        "success": True,

        "message": (
            "Official record created successfully"
        ),

        "vaultId": str(
            insert_result.inserted_id
        ),

        "committeeStatus": FINALIZED_STATUS,

        "isLocked": False,
    }

# ==========================================================
# Lock Transcript
# Record Office Final Lock
# ==========================================================

@router.post(
    "/lock/{vault_id}"
)
@require_role([
    UserRole.RECORD_OFFICE
])
async def lock_transcript(
    vault_id: str,
    current_user: User = Depends(
        get_current_active_user
    ),
):

    if not ObjectId.is_valid(
        vault_id
    ):

        raise HTTPException(
            status_code=400,
            detail="Invalid vault id",
        )

    vault = await record_office_vaults_collection.find_one({
        "_id": ObjectId(vault_id)
    })

    if not vault:

        raise HTTPException(
            status_code=404,
            detail="Transcript vault not found",
        )

    # ------------------------------------------------------
    # Must come from FINALIZED committee record
    # ------------------------------------------------------

    if vault.get(
        "committeeStatus"
    ) != FINALIZED_STATUS:

        raise HTTPException(
            status_code=400,
            detail=(
                "Committee FINALIZED status required"
            ),
        )

    if vault.get(
        "isLocked"
    ) is True:

        raise HTTPException(
            status_code=400,
            detail="Transcript already locked",
        )

    await record_office_vaults_collection.update_one(

        {
            "_id": ObjectId(vault_id)
        },

        {
            "$set": {

                "isLocked": True,

                "approvedBy": str(
                    current_user.id
                ),

                "lockedAt": datetime.utcnow(),

            }
        },
    )

    return {

        "success": True,

        "message": (
            "Transcript locked successfully"
        ),

        "vaultId": vault_id,

    }

# ==========================================================
# Lock Vault
# Same final locking workflow
# ==========================================================

@router.post(
    "/vault/{vault_id}/lock"
)
@require_role([
    UserRole.RECORD_OFFICE
])
async def lock_vault(
    vault_id: str,
    current_user: User = Depends(
        get_current_active_user
    ),
):

    if not ObjectId.is_valid(
        vault_id
    ):

        raise HTTPException(
            status_code=400,
            detail="Invalid vault id",
        )

    vault = await record_office_vaults_collection.find_one({
        "_id": ObjectId(vault_id)
    })

    if not vault:

        raise HTTPException(
            status_code=404,
            detail="Vault not found",
        )

    if vault.get(
        "committeeStatus"
    ) != FINALIZED_STATUS:

        raise HTTPException(
            status_code=400,
            detail=(
                "Committee FINALIZED status required"
            ),
        )

    if vault.get(
        "isLocked"
    ) is True:

        raise HTTPException(
            status_code=400,
            detail="Already locked",
        )

    await record_office_vaults_collection.update_one(

        {
            "_id": ObjectId(vault_id)
        },

        {
            "$set": {

                "isLocked": True,

                "approvedBy": str(
                    current_user.id
                ),

                "lockedAt": datetime.utcnow(),

            }
        },
    )

    return {

        "success": True,

        "message": (
            "Transcript locked successfully"
        ),

        "vaultId": vault_id,

    }

# ==========================================================
# View All Vaults
# ==========================================================

@router.get(
    "/vaults"
)
@require_role([
    UserRole.RECORD_OFFICE,
    UserRole.ADMIN
])
async def get_vaults(
    current_user: User = Depends(
        get_current_active_user
    ),
):

    result = []

    cursor = record_office_vaults_collection.find({})

    async for vault in cursor:

        vault["_id"] = str(
            vault["_id"]
        )

        result.append(vault)

    return result

# ==========================================================
# View Student Transcript
# FINALIZED committee record only
# ==========================================================

@router.get(
    "/transcripts/{student_id}"
)
@require_role([
    UserRole.RECORD_OFFICE,
    UserRole.ADMIN
])
async def student_transcripts(
    student_id: str,
    current_user: User = Depends(
        get_current_active_user
    ),
):

    # ------------------------------------------------------
    # Student can be MongoDB _id or studentNumber
    # ------------------------------------------------------

    student = None

    if valid_object_id(student_id):

        student = await students_collection.find_one({
            "_id": ObjectId(student_id)
        })

    if not student:

        student = await students_collection.find_one({
            "studentId": student_id
        })

    if not student:

        raise HTTPException(
            status_code=404,
            detail="Student not found",
        )

    mongo_student_id = str(
        student["_id"]
    )

    records = await committee_reviews_collection.find({

        "studentId": {
            "$in": [
                mongo_student_id,
                student.get("studentId")
            ]
        },

        "status": FINALIZED_STATUS,

    }).to_list(None)

    for record in records:

        record["_id"] = str(
            record["_id"]
        )

    return records

# ==========================================================
# Check Locked Vault
# ==========================================================

@router.get(
    "/vault/check/{student_id}/{level_id}"
)
@require_role([
    UserRole.ADMIN,
    UserRole.RECORD_OFFICE
])
async def check_locked_vault(
    student_id: str,
    level_id: str,
    current_user: User = Depends(
        get_current_active_user
    ),
):

    vault = await record_office_vaults_collection.find_one({

        "studentId": student_id,

        "levelId": level_id,

        "isLocked": True,

    })

    return {

        "locked": (
            True
            if vault
            else False
        ),

        "vaultId": (
            str(vault["_id"])
            if vault
            else None
        ),
    }