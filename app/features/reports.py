from fastapi import APIRouter, HTTPException
from bson import ObjectId

from app.database import (
    courses_collection,
    levels_collection,
    students_collection,
)

router = APIRouter()
   

# =========================================================
# GET COURSES
# PUBLIC REPORT
# =========================================================

@router.get("/courses")
async def get_report_courses():

    courses = await courses_collection.find(
        {
            "isDeleted": False
        },
        {
            "_id": 1,
            "name": 1,
            "code": 1,
        }
    ).sort(
        "name",
        1
    ).to_list(None)

    return {
        "courses": [
            {
                "courseId": str(course["_id"]),
                "name": course.get(
                    "name",
                    ""
                ),
                "code": course.get(
                    "code",
                    ""
                ),
            }
            for course in courses
        ]
    }

# =========================================================
# GET LEVELS BY COURSE
# PUBLIC REPORT
# =========================================================

@router.get(
    "/courses/{course_id}/levels"
)
async def get_course_levels(
    course_id: str
):

    levels = await levels_collection.find(
        {
            "courseId": course_id,
            "isDeleted": False,
        },
        {
            "_id": 1,
            "courseId": 1,
            "departmentId": 1,
            "levelNumber": 1,
            "description": 1,
        }
    ).sort(
        "levelNumber",
        1
    ).to_list(None)

    return {
        "levels": [
            {
                "levelId": str(level["_id"]),
                "courseId": level.get(
                    "courseId",
                    ""
                ),
                "departmentId": level.get(
                    "departmentId",
                    ""
                ),
                "levelNumber": level.get(
                    "levelNumber"
                ),
                "description": level.get(
                    "description",
                    f"Level {level.get('levelNumber', '')}"
                ),
            }
            for level in levels
        ]
    }

# =========================================================
# GET STUDENTS BY COURSE + LEVEL
# PUBLIC REPORT
# =========================================================

@router.get(
    "/courses/{course_id}/levels/{level_id}/students"
)
async def get_students_by_course_level(
    course_id: str,
    level_id: str
):

    # -----------------------------------------------------
    # Validate ObjectId
    # -----------------------------------------------------

    try:

        level_object_id = ObjectId(
            level_id
        )

    except Exception:

        raise HTTPException(
            status_code=400,
            detail="Invalid level ID"
        )

    # -----------------------------------------------------
    # Make sure level belongs to selected course
    # -----------------------------------------------------

    level = await levels_collection.find_one(
        {
            "_id": level_object_id,
            "courseId": course_id,
            "isDeleted": False,
        }
    )

    if not level:

        raise HTTPException(
            status_code=404,
            detail="Level not found for selected course"
        )

    # -----------------------------------------------------
    # Get students
    # -----------------------------------------------------

    students = await students_collection.find(
        {
            "currentLevelId": level_id,
            "status": {
                "$in": [
                    "approved",
                    "active",
                    "graduated",
                ]
            }
        },
        {
            "_id": 1,
            "studentId": 1,
            "full_name": 1,
            "status": 1,
        }
    ).sort(
        "studentId",
        1
    ).to_list(None)

    result = []

    for student in students:

        status = student.get(
            "status",
            ""
        )

        if status in [
            "approved",
            "active",
        ]:

            display_status = "Active"

        elif status == "graduated":

            display_status = "Graduated"

        else:

            display_status = status

        result.append({

            "id": str(
                student["_id"]
            ),

            "studentId": student.get(
                "studentId",
                ""
            ),

            "studentName": student.get(
                "full_name",
                ""
            ),

            "status": display_status,

        })

    return {

        "courseId": course_id,

        "levelId": level_id,

        "levelNumber": level.get(
            "levelNumber"
        ),

        "students": result,

        "studentCount": len(result),

    }
