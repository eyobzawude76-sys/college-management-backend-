from datetime import datetime

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.database import db
from app.database import (
    module_assignments_collection,
    modules_collection,
    teachers_collection,
)

from app.features.auth import User, UserRole
from app.shared.auth import get_current_active_user
from app.shared.rbac import require_role

# ============================================================
# ROUTER
# ============================================================

router = APIRouter()

# ============================================================
# SAFE ID HELPERS
#
# MongoDB keessatti ID:
#     "665abc..."       -> String
#     ObjectId("...")   -> ObjectId
#
# Lamaan isaanii akka hojjetan godha.
# ============================================================

def id_variants(value):
    """
    Given ID:
        String -> [String, ObjectId]
        ObjectId -> [ObjectId, String]

    MongoDB keessatti String fi ObjectId lamaan akka
    barbaadamuuf gargaarama.
    """

    if value is None:
        return []

    value_str = str(value)

    variants = [value_str]

    if ObjectId.is_valid(value_str):
        variants.append(ObjectId(value_str))

    # duplicate irraa qulqulleessi
    unique = []

    for item in variants:
        if item not in unique:
            unique.append(item)

    return unique

def same_id(value1, value2):
    """
    ObjectId fi String wal bira qabuuf.
    Fakkeenya:
        ObjectId("abc") == "abc"
        -> True
    """

    if value1 is None or value2 is None:
        return False

    return str(value1) == str(value2)

# ============================================================
# SCHEMAS
# ============================================================

class ModuleAssignmentCreate(BaseModel):
    moduleId: str
    teacherId: str

class ModulePinVerify(BaseModel):
    moduleId: str
    pin: str = ""

# ============================================================
# ASSIGN TEACHER TO MODULE
#
# Department Head
#       ↓
# Select Module
#       ↓
# Select Teacher
#       ↓
# Assign
#
# One module = One active teacher
# ============================================================

@router.post("", status_code=status.HTTP_201_CREATED)
@require_role([UserRole.DEPARTMENT_HEAD])
async def assign_teacher(
    data: ModuleAssignmentCreate,
    current_user: User = Depends(get_current_active_user),
):

    # --------------------------------------------------------
    # Validate Module ID
    # --------------------------------------------------------

    if not ObjectId.is_valid(data.moduleId):
        raise HTTPException(
            status_code=400,
            detail="Invalid module ID",
        )

    # --------------------------------------------------------
    # Validate Teacher ID
    # --------------------------------------------------------

    if not ObjectId.is_valid(data.teacherId):
        raise HTTPException(
            status_code=400,
            detail="Invalid teacher ID",
        )

    # --------------------------------------------------------
    # Find Module
    #
    # _id yeroo hunda ObjectId ta'uu qaba.
    # Garuu departmentId fi levelId keessaa
    # String/ObjectId ta'uu danda'u.
    # --------------------------------------------------------

    module = await modules_collection.find_one(
        {
            "_id": ObjectId(data.moduleId),
            "isDeleted": {"$ne": True},
        }
    )

    if not module:
        raise HTTPException(
            status_code=404,
            detail="Module not found",
        )

    # --------------------------------------------------------
    # Department Head Ownership Check
    # --------------------------------------------------------

    user_dict = (
        current_user
        if isinstance(current_user, dict)
        else getattr(current_user, "__dict__", {})
    )

    user_department_id = (
        user_dict.get("departmentId")
        or user_dict.get("department_id")
        or getattr(current_user, "departmentId", None)
        or getattr(current_user, "department_id", None)
    )

    # --------------------------------------------------------
    # Yoo Token keessatti department ID hin jirre
    # Database irraa barbaadi
    # --------------------------------------------------------

    if not user_department_id:

        user_id_str = str(
            user_dict.get("_id")
            or user_dict.get("id")
            or getattr(current_user, "id", "")
        )

        if user_id_str:

            # User ID ObjectId ykn String ta'uu danda'a
            user_id_values = id_variants(user_id_str)

            if user_id_values:
                db_user = await db["users"].find_one(
                    {
                        "_id": {
                            "$in": user_id_values
                        }
                    }
                )

                if db_user:
                    user_department_id = (
                        db_user.get("departmentId")
                        or db_user.get("department_id")
                    )

            # ------------------------------------------------
            # Yoo users keessa illee hin argamne
            # Department Head irraa barbaadi
            # ------------------------------------------------

            if not user_department_id:

                head_values = id_variants(user_id_str)

                dept_queries = []

                for head_value in head_values:
                    dept_queries.append(
                        {"headId": head_value}
                    )
                    dept_queries.append(
                        {"head_id": head_value}
                    )

                if dept_queries:
                    dept_doc = await db["departments"].find_one(
                        {"$or": dept_queries}
                    )

                    if dept_doc:
                        user_department_id = str(
                            dept_doc["_id"]
                        )

    # --------------------------------------------------------
    # Department ID hin argamne
    # --------------------------------------------------------

    if not user_department_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Department Head is not assigned to a department",
        )

    # --------------------------------------------------------
    # Module Department ID
    #
    # departmentId / department_id
    # String ykn ObjectId ta'uu danda'a.
    # --------------------------------------------------------

    module_dept_id = (
        module.get("departmentId")
        or module.get("department_id")
    )

    if not module_dept_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Module is not assigned to a department",
        )

    # --------------------------------------------------------
    # Department Match
    # --------------------------------------------------------

    if not same_id(user_department_id, module_dept_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only assign teachers to modules in your department",
        )

    # --------------------------------------------------------
    # Find Teacher
    #
    # Teacher _id yeroo baay'ee ObjectId dha.
    # Garuu input String dha.
    # --------------------------------------------------------

    teacher_id_input = str(data.teacherId)

    teacher = None

    if ObjectId.is_valid(teacher_id_input):

        teacher = await teachers_collection.find_one(
            {
                "_id": ObjectId(teacher_id_input),
                "isDeleted": {"$ne": True},
            }
        )

    # --------------------------------------------------------
    # Yoo _id irratti hin argamne
    # email / id / userId irratti ilaali
    # --------------------------------------------------------

    if not teacher:

        teacher_query = {
            "$or": [
                {
                    "email": teacher_id_input
                },
                {
                    "id": teacher_id_input
                },
                {
                    "userId": teacher_id_input
                },
            ],
            "isDeleted": {"$ne": True},
        }

        teacher = await teachers_collection.find_one(
            teacher_query
        )

    if not teacher:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Teacher not found",
        )

    # --------------------------------------------------------
    # Teacher Department Ownership
    # --------------------------------------------------------

    teacher_department_id = (
        teacher.get("departmentId")
        or teacher.get("department_id")
    )

    if teacher_department_id:

        if not same_id(
            teacher_department_id,
            module_dept_id
        ):
            raise HTTPException(
                status_code=403,
                detail="Teacher does not belong to this department",
            )

    # --------------------------------------------------------
    # Check Existing Active Assignment
    #
    # moduleId String ykn ObjectId ta'uu danda'a.
    # Kanaaf $in fayyadamna.
    # --------------------------------------------------------

    existing = await module_assignments_collection.find_one(
        {
            "moduleId": {
                "$in": id_variants(data.moduleId)
            },
            "isActive": True,
        }
    )

    if existing:

        existing_teacher_id = (
            existing.get("teacherId")
            or existing.get("teacher_id")
        )

        if same_id(
            existing_teacher_id,
            data.teacherId
        ):
            raise HTTPException(
                status_code=400,
                detail="This teacher is already assigned to this module",
            )

        raise HTTPException(
            status_code=400,
            detail="This module already has an active teacher",
        )

    # --------------------------------------------------------
    # Module Level ID
    # --------------------------------------------------------

    module_level_id = (
        module.get("levelId")
        or module.get("level_id")
    )

    # --------------------------------------------------------
    # Create Assignment
    #
    # Existing architecture akkuma jirutti:
    # moduleId       -> String
    # teacherId      -> String
    # departmentId   -> String
    # levelId        -> String
    # --------------------------------------------------------

    assignment = {
        "moduleId": str(data.moduleId),
        "teacherId": str(teacher["_id"]),
        "departmentId": str(module_dept_id),
        "levelId": str(module_level_id) if module_level_id else None,
        "isActive": True,
        "assignedAt": datetime.utcnow(),
        "updatedAt": None,
    }

    result = await module_assignments_collection.insert_one(
        assignment
    )

    assignment["_id"] = str(result.inserted_id)

    return assignment

# ============================================================
# DEPARTMENT HEAD VIEW ASSIGNMENTS
# ============================================================

@router.get("")
@require_role([UserRole.DEPARTMENT_HEAD])
async def get_department_assignments(
    current_user: User = Depends(get_current_active_user),
):

    # --------------------------------------------------------
    # Get Department ID safely
    # --------------------------------------------------------

    user_dict = (
        current_user
        if isinstance(current_user, dict)
        else getattr(current_user, "__dict__", {})
    )

    department_id = (
        user_dict.get("departmentId")
        or user_dict.get("department_id")
        or getattr(current_user, "departmentId", None)
        or getattr(current_user, "department_id", None)
    )

    if not department_id:
        return []

    # --------------------------------------------------------
    # String/ObjectId lamaan support
    # --------------------------------------------------------

    query = {
        "departmentId": {
            "$in": id_variants(department_id)
        },
        "isActive": True,
    }

    response = []

    cursor = module_assignments_collection.find(
        query
    ).sort(
        "assignedAt",
        -1
    )

    async for item in cursor:

        # ----------------------------------------------------
        # Module ID
        # ----------------------------------------------------

        module_id = (
            item.get("moduleId")
            or item.get("module_id")
        )

        module = None

        if module_id:

            module = await modules_collection.find_one(
                {
                    "_id": {
                        "$in": id_variants(module_id)
                    },
                    "isDeleted": {"$ne": True},
                }
            )

        # ----------------------------------------------------
        # Teacher ID
        # ----------------------------------------------------

        teacher_id = (
            item.get("teacherId")
            or item.get("teacher_id")
        )

        teacher = None

        if teacher_id:

            teacher = await teachers_collection.find_one(
                {
                    "_id": {
                        "$in": id_variants(teacher_id)
                    },
                    "isDeleted": {"$ne": True},
                }
            )

        # ----------------------------------------------------
        # Teacher hin argamne assignment tokko qofa
        # skip godhi.
        # API guutuu 404 hin godhin.
        # ----------------------------------------------------

        if not teacher:
            continue

        response.append(
            {
                "_id": str(item["_id"]),

                "moduleId": (
                    str(module_id)
                    if module_id is not None
                    else ""
                ),

                "teacherId": (
                    str(teacher_id)
                    if teacher_id is not None
                    else ""
                ),

                "departmentId": (
                    str(
                        item.get("departmentId")
                        or item.get("department_id")
                    )
                    if (
                        item.get("departmentId")
                        or item.get("department_id")
                    )
                    else ""
                ),

                "levelId": (
                    str(
                        item.get("levelId")
                        or item.get("level_id")
                    )
                    if (
                        item.get("levelId")
                        or item.get("level_id")
                    )
                    else ""
                ),

                "moduleName": (
                    module.get("name")
                    if module
                    else ""
                ),

                "moduleCode": (
                    module.get("code")
                    if module
                    else ""
                ),

                "creditHour": (
                    module.get("creditHour", 3)
                    if module
                    else 3
                ),

                "teacherName": (
                    teacher.get("fullName")
                    or teacher.get("full_name")
                    or teacher.get("name")
                    or ""
                ),

                "assignedAt": item.get(
                    "assignedAt"
                ),

                "isActive": item.get(
                    "isActive",
                    True
                ),
            }
        )

    return response

# ============================================================
# TEACHER MODULES (NO PIN REQUIRED)
# ============================================================

@router.get("/teacher")
@require_role([
    UserRole.TEACHER,
    "teacher",
    "TEACHER"
])
async def get_teacher_modules(
    current_user: User = Depends(get_current_active_user),
):

    # --------------------------------------------------------
    # Current User
    # --------------------------------------------------------

    user_dict = (
        current_user
        if isinstance(current_user, dict)
        else getattr(current_user, "__dict__", {})
    )

    user_id_str = str(
        user_dict.get("_id")
        or user_dict.get("id")
        or getattr(current_user, "id", "")
    )

    user_email = (
        user_dict.get("email")
        or getattr(current_user, "email", None)
    )

    # --------------------------------------------------------
    # Find Teacher
    #
    # Teacher:
    #   _id
    #   userId
    #   id
    #   email
    #
    # keessaa kamiyyuu ta'uu danda'a.
    # --------------------------------------------------------

    teacher_conditions = []

    if user_id_str:

        # _id
        if ObjectId.is_valid(user_id_str):
            teacher_conditions.append(
                {
                    "_id": ObjectId(user_id_str)
                }
            )

        # String fields
        teacher_conditions.extend(
            [
                {
                    "userId": user_id_str
                },
                {
                    "id": user_id_str
                },
            ]
        )

    if user_email:
        teacher_conditions.append(
            {
                "email": user_email
            }
        )

    teacher = None

    if teacher_conditions:

        teacher = await teachers_collection.find_one(
            {
                "$or": teacher_conditions,
                "isDeleted": {"$ne": True},
            }
        )

    # --------------------------------------------------------
    # Teacher ID
    # --------------------------------------------------------

    teacher_ids = []

    if teacher:

        teacher_ids.extend(
            id_variants(teacher.get("_id"))
        )

        if teacher.get("userId"):
            teacher_ids.extend(
                id_variants(teacher.get("userId"))
            )

        if teacher.get("id"):
            teacher_ids.extend(
                id_variants(teacher.get("id"))
            )

    else:

        teacher_ids.extend(
            id_variants(user_id_str)
        )

    # --------------------------------------------------------
    # Remove duplicates
    # --------------------------------------------------------

    unique_teacher_ids = []

    for teacher_id in teacher_ids:
        if teacher_id not in unique_teacher_ids:
            unique_teacher_ids.append(
                teacher_id
            )

    if not unique_teacher_ids:
        return []

    # --------------------------------------------------------
    # Find Assignments
    #
    # teacherId String/ObjectId lamaan support.
    # --------------------------------------------------------

    cursor = module_assignments_collection.find(
        {
            "$or": [
                {
                    "teacherId": {
                        "$in": unique_teacher_ids
                    }
                },
                {
                    "teacher_id": {
                        "$in": unique_teacher_ids
                    }
                },
            ],
            "isActive": True,
        }
    )

    response = []

    # --------------------------------------------------------
    # Loop Assignments
    # --------------------------------------------------------

    async for assignment in cursor:

        module_id = (
            assignment.get("moduleId")
            or assignment.get("module_id")
        )

        if not module_id:
            continue

        # ----------------------------------------------------
        # Find Module
        # _id ObjectId ykn String ta'uu danda'a.
        # ----------------------------------------------------

        module = await modules_collection.find_one(
            {
                "_id": {
                    "$in": id_variants(module_id)
                },
                "isDeleted": {"$ne": True},
            }
        )

        if not module:
            continue

        # ----------------------------------------------------
        # Module Department
        # ----------------------------------------------------

        module_department_id = (
            module.get("departmentId")
            or module.get("department_id")
        )

        # ----------------------------------------------------
        # Module Level
        # ----------------------------------------------------

        module_level_id = (
            module.get("levelId")
            or module.get("level_id")
        )

        response.append(
            {
                "_id": str(module["_id"]),

                "moduleId": str(
                    module["_id"]
                ),

                "moduleCode": module.get(
                    "code",
                    ""
                ),

                "moduleName": module.get(
                    "name",
                    ""
                ),

                "creditHour": module.get(
                    "creditHour",
                    3
                ),

                "departmentId": (
                    str(module_department_id)
                    if module_department_id
                    else ""
                ),

                "levelId": (
                    str(module_level_id)
                    if module_level_id
                    else ""
                ),

                "assignedAt": assignment.get(
                    "assignedAt"
                ),

                "isAssigned": True,

                "isPinRequired": False,
            }
        )

    return response

# ============================================================
# VERIFY MODULE PIN
# BYPASS - AUTO ACCESS
# ============================================================

@router.post("/verify-pin")
@require_role([
    UserRole.TEACHER,
    "teacher",
    "TEACHER"
])
async def verify_module_pin(
    data: ModulePinVerify,
    current_user: User = Depends(get_current_active_user),
):

    return {
        "success": True,
        "message": "Access granted successfully",
        "moduleId": data.moduleId,
        "accessGranted": True,
        "verifiedAt": datetime.utcnow(),
    }

# ============================================================
# DEACTIVATE MODULE ASSIGNMENT
# ============================================================

@router.delete("/{assignment_id}")
@require_role([UserRole.DEPARTMENT_HEAD])
async def deactivate_assignment(
    assignment_id: str,
    current_user: User = Depends(get_current_active_user),
):

    # --------------------------------------------------------
    # Validate Assignment ID
    # --------------------------------------------------------

    if not ObjectId.is_valid(assignment_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid assignment ID",
        )

    # --------------------------------------------------------
    # Find Assignment
    # --------------------------------------------------------

    assignment = await module_assignments_collection.find_one(
        {
            "_id": ObjectId(assignment_id),
            "isActive": True,
        }
    )

    if not assignment:
        raise HTTPException(
            status_code=404,
            detail="Active assignment not found",
        )

    # --------------------------------------------------------
    # Current User Department
    # --------------------------------------------------------

    user_dict = (
        current_user
        if isinstance(current_user, dict)
        else getattr(current_user, "__dict__", {})
    )

    user_department_id = (
        user_dict.get("departmentId")
        or user_dict.get("department_id")
        or getattr(current_user, "departmentId", None)
        or getattr(current_user, "department_id", None)
    )

    if not user_department_id:
        raise HTTPException(
            status_code=403,
            detail="Department Head is not assigned to a department",
        )

    # --------------------------------------------------------
    # Assignment Department
    # --------------------------------------------------------

    assignment_department_id = (
        assignment.get("departmentId")
        or assignment.get("department_id")
    )

    if not same_id(
        user_department_id,
        assignment_department_id
    ):
        raise HTTPException(
            status_code=403,
            detail="You can only manage assignments in your department",
        )

    # --------------------------------------------------------
    # Deactivate
    # --------------------------------------------------------

    await module_assignments_collection.update_one(
        {
            "_id": ObjectId(assignment_id),
            "isActive": True,
        },
        {
            "$set": {
                "isActive": False,
                "updatedAt": datetime.utcnow(),
                "deactivatedAt": datetime.utcnow(),
            }
        },
    )

    return {
        "success": True,
        "message": "Teacher assignment deactivated successfully",
        "assignmentId": assignment_id,
    }