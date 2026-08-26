from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from bson import ObjectId
from app.shared.hashing import hash_password as get_password_hash
from app.core.models import User
from app.core.security import decode_token

from app.database import (
    users_collection,
    teachers_collection,
    students_collection,
)

# =========================================================
# HTTP BEARER
# =========================================================

security = HTTPBearer()

# =========================================================
# GET CURRENT USER
# =========================================================

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    token = credentials.credentials

    # =====================================================
    # 1. DECODE ACCESS TOKEN
    # =====================================================

    payload = decode_token(token)

    if not payload or payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # =====================================================
    # 2. GET USER ID FROM TOKEN
    # =====================================================

    user_id = payload.get("sub")

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # =====================================================
    # 3. CONVERT TO OBJECT ID
    # =====================================================

    try:
        obj_id = ObjectId(str(user_id))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user ID format",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # =====================================================
    # 4. FIND USER
    # =====================================================

    user = await users_collection.find_one(
        {
            "_id": obj_id,
            "$or": [
                {"isDeleted": False},
                {"isDeleted": {"$exists": False}},
            ],
        }
    )

    source = "users"

    # =====================================================
    # 5. FIND TEACHER
    # =====================================================

    if not user:

        user = await teachers_collection.find_one(
            {
                "_id": obj_id,
                "$or": [
                    {"isDeleted": False},
                    {"isDeleted": {"$exists": False}},
                ],
            }
        )

        if user:
            source = "teachers"

    # =====================================================
    # 6. FIND STUDENT
    #
    # IMPORTANT:
    # Students DO NOT need to exist in users collection.
    # They are authenticated directly from students collection.
    # =====================================================

    if not user:

        user = await students_collection.find_one(
            {
                "_id": obj_id,
                "$or": [
                    {"isDeleted": False},
                    {"isDeleted": {"$exists": False}},
                ],
            }
        )

        if user:
            source = "students"

    # =====================================================
    # 7. USER NOT FOUND
    # =====================================================

    if not user:

        print("\n========== AUTH USER NOT FOUND ==========")
        print("TOKEN USER ID:", user_id)
        print("OBJECT ID    :", obj_id)
        print("=========================================\n")

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # =====================================================
    # 8. OBJECT ID -> STRING
    # =====================================================

    user["_id"] = str(user["_id"])
    user["id"] = user["_id"]

    # =====================================================
    # 9. STUDENT NORMALIZATION
    # =====================================================

    if source == "students":

        # -------------------------------------------------
        # Student role
        # -------------------------------------------------

        user["role"] = "student"

        # -------------------------------------------------
        # Full name
        # -------------------------------------------------

        if "fullName" not in user:
            user["fullName"] = user.get(
                "full_name",
                "",
            )

        # -------------------------------------------------
        # Username
        # -------------------------------------------------

        if not user.get("username"):
            user["username"] = user.get(
                "email",
                "",
            )

        # -------------------------------------------------
        # Email
        # -------------------------------------------------

        if not user.get("email"):
            user["email"] = user.get(
                "username",
                "student@college.edu",
            )

        # -------------------------------------------------
        # Status
        # -------------------------------------------------

        raw_status = user.get("status", "")

        if hasattr(raw_status, "value"):
            raw_status = raw_status.value

        user["status"] = str(
            raw_status
        ).lower()

        # -------------------------------------------------
        # Student ID
        # -------------------------------------------------

        if "studentId" not in user:
            user["studentId"] = user.get(
                "student_id",
                "",
            )

        # -------------------------------------------------
        # Department ID
        # -------------------------------------------------

        raw_department_id = (
            user.get("departmentId")
            or user.get("department_id")
        )

        if raw_department_id:
            user["departmentId"] = str(
                raw_department_id
            )

        # -------------------------------------------------
        # Current Level ID
        # -------------------------------------------------

        raw_level_id = (
            user.get("currentLevelId")
            or user.get("current_level_id")
        )

        if raw_level_id:
            user["currentLevelId"] = str(
                raw_level_id
            )

        # -------------------------------------------------
        # Course ID
        # -------------------------------------------------

        raw_course_id = (
            user.get("courseId")
            or user.get("course_id")
        )

        if raw_course_id:
            user["courseId"] = str(
                raw_course_id
            )

        # =================================================
        # IMPORTANT
        #
        # Student passwordHash may NOT exist in the
        # students document.
        #
        # User model requires it, therefore give it a
        # harmless internal value ONLY for model validation.
        #
        # This is NOT used for password verification here.
        # =================================================

        if not user.get("passwordHash"):
            user["passwordHash"] = "student-authenticated"

    # =====================================================
    # 10. NORMAL USER / TEACHER
    # =====================================================

    else:

        # -------------------------------------------------
        # Department
        # -------------------------------------------------

        raw_department_id = (
            user.get("departmentId")
            or user.get("department_id")
        )

        if raw_department_id:
            user["departmentId"] = str(
                raw_department_id
            )

        # -------------------------------------------------
        # Full name
        # -------------------------------------------------

        if "fullName" not in user:
            user["fullName"] = user.get(
                "full_name",
                "",
            )

        # -------------------------------------------------
        # Email
        # -------------------------------------------------

        if not user.get("email"):
            user["email"] = user.get(
                "username",
                "user@college.edu",
            )

        # -------------------------------------------------
        # Username
        # -------------------------------------------------

        if "username" not in user:
            user["username"] = user.get(
                "email",
                "",
            )

        # -------------------------------------------------
        # Password hash compatibility
        # -------------------------------------------------

        if not user.get("passwordHash"):
            user["passwordHash"] = (
                user.get("hashedPassword")
                or user.get("hashed_password")
                or user.get("password")
                or "hash_pwd"
            )

    # =====================================================
    # 11. CONVERT ALL OBJECT IDS
    # =====================================================

    for key, value in list(user.items()):

        if isinstance(value, ObjectId):
            user[key] = str(value)

    # =====================================================
    # 12. DEBUG
    # =====================================================

    print("\n========== AUTH USER DEBUG ==========")
    print("SOURCE        :", source)
    print("USER ID       :", user.get("id"))
    print("EMAIL         :", user.get("email"))
    print("ROLE          :", user.get("role"))
    print("STATUS        :", user.get("status"))
    print("STUDENT ID    :", user.get("studentId"))
    print("DEPARTMENT ID :", user.get("departmentId"))
    print("LEVEL ID      :", user.get("currentLevelId"))
    print("COURSE ID     :", user.get("courseId"))
    print("=====================================\n")

    # =====================================================
    # 13. RETURN USER MODEL
    # =====================================================

    return User(**user)

# =========================================================
# GET CURRENT ACTIVE USER
# =========================================================

async def get_current_active_user(
    current_user: User = Depends(get_current_user),
):

    if current_user.status not in [
        "active",
        "approved",
    ]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user",
        )

    return current_user