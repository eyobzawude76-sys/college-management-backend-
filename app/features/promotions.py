from datetime import datetime
from typing import Optional, List

from bson import ObjectId

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status
)

from pydantic import BaseModel, Field
from datetime import datetime
from typing import List

from bson import ObjectId

from fastapi import (
    APIRouter,
    Depends,
    HTTPException
)

from pydantic import BaseModel

from app.database import (
    students_collection,
    users_collection,
    levels_collection,
    academic_records_collection,
    record_office_vaults_collection,
    promotions_collection,
)

from app.features.auth import User, UserRole
from app.shared.auth import get_current_active_user
from app.shared.rbac import require_role

from app.database import (
    levels_collection,
    students_collection,
    promotions_collection,
    academic_records_collection,
    record_office_vaults_collection,
)


from app.features.auth import User, UserRole
from app.shared.auth import get_current_active_user
from app.shared.rbac import require_role



router = APIRouter(
    prefix="/promotions",
    tags=["Promotions"]
)

router = APIRouter(
    prefix="/promotions",
    tags=["Promotions"]
)

# ==========================================================
# Schema
# ==========================================================


class BatchPromoteRequest(BaseModel):

    student_ids: List[str] = Field(
        ...,
        alias="studentIds"
    )


    class Config:
        populate_by_name = True





class PromotionAction(BaseModel):

    action: str





# ==========================================================
# ObjectId Validation
# ==========================================================


def validate_object_id(value: str):

    if not ObjectId.is_valid(value):

        raise HTTPException(
            status_code=400,
            detail="Invalid ObjectId"
        )

    return ObjectId(value)





# ==========================================================
# Get Academic Record
# ==========================================================


async def get_academic_record(
    student_id: str,
    level_id: str
):

    record = await academic_records_collection.find_one({

        "studentId": student_id,

        "levelId": level_id

    })


    if not record:

        raise HTTPException(

            status_code=404,

            detail="Academic record not found"

        )



    failed_modules = record.get(
        "failedModules",
        0
    )


    gpa = record.get(
        "gpa",
        0
    )



    if failed_modules > 0:

        raise HTTPException(

            status_code=400,

            detail="Student has failed modules"

        )



    if gpa < 2.0:

        raise HTTPException(

            status_code=400,

            detail="GPA below promotion requirement"

        )



    return record





# ==========================================================
# Validate Record Office Vault
# ==========================================================


async def get_locked_vault(
    student_id: str,
    level_id: str
):


    vault = await record_office_vaults_collection.find_one({

        "studentId": student_id,

        "levelId": level_id,

        "committeeApproved": True,

        "isLocked": True

    })



    if not vault:

        raise HTTPException(

            status_code=400,

            detail=
            "Committee approval or locked vault missing"

        )


    return vault





# ==========================================================
# Find Current And Next Level
# ==========================================================


async def get_levels(
    current_level_id: str
):


    current_level = await levels_collection.find_one({

        "_id":
        validate_object_id(
            current_level_id
        )

    })


    if not current_level:

        raise HTTPException(

            status_code=404,

            detail="Current level not found"

        )



    next_level = await levels_collection.find_one({

        "departmentId":
            current_level["departmentId"],


        "levelNumber":
            current_level["levelNumber"] + 1,


        "isDeleted":
            False

    })



    return current_level, next_level





# ==========================================================
# Promotion History Builder
# ==========================================================


def create_promotion_history(

    student_id: str,

    previous_level_id: str,

    next_level_id: Optional[str],

    action: str,

    record: dict,

    vault: dict,

    current_user: User

):


    return {


        "studentId":

            student_id,



        "previousLevelId":

            previous_level_id,



        "nextLevelId":

            next_level_id,



        "action":

            action,



        "gpa":

            record.get(
                "gpa",
                0
            ),



        "cgpa":

            record.get(
                "cgpa",
                record.get("gpa",0)
            ),



        "average":

            record.get(
                "average",
                0
            ),



        "passedModules":

            record.get(
                "passedModules",
                0
            ),



        "failedModules":

            record.get(
                "failedModules",
                0
            ),



        "recordVaultId":

            str(vault["_id"]),



        "committeeApproved":

            True,



        "committeeApprovedBy":

            vault.get(
                "committeeApprovedBy"
            ),



        "committeeApprovedAt":

            vault.get(
                "committeeApprovedAt"
            ),



        "processedBy":

            str(current_user.id),



        "createdAt":

            datetime.utcnow()

    }
# ==========================================================
# EXECUTE PROMOTION
# Committee + Record Office + Promotion Workflow
# ==========================================================


@router.post(
    "/execute/{student_id}",
    status_code=status.HTTP_200_OK
)
@require_role([
    UserRole.ADMIN,
    UserRole.ADMIN
])
async def execute_promotion(

    student_id: str,

    payload: PromotionAction,

    current_user: User =
    Depends(get_current_active_user)

):


    # ======================================================
    # Validate Student ID
    # ======================================================

    student_object_id = validate_object_id(
        student_id
    )



    student = await students_collection.find_one({

        "_id":
            student_object_id

    })


    if not student:

        raise HTTPException(

            status_code=404,

            detail="Student not found"

        )




    current_level_id = str(

        student.get(
            "currentLevelId"
        )

    )



    if not current_level_id:

        raise HTTPException(

            status_code=400,

            detail="Student level not assigned"

        )




    # ======================================================
    # 1. Academic Record Check
    # ======================================================


    record = await get_academic_record(

        student_id,

        current_level_id

    )





    # ======================================================
    # 2. Committee + Record Office Vault Check
    # ======================================================


    vault = await get_locked_vault(

        student_id,

        current_level_id

    )





    # ======================================================
    # 3. Find Current And Next Level
    # ======================================================


    current_level, next_level = await get_levels(

        current_level_id

    )




    action = payload.action.lower()



    promotion_status = None

    next_level_id = None





    # ======================================================
    # PROMOTE
    # ======================================================


    if action == "promote":



        if not next_level:

            raise HTTPException(

                status_code=400,

                detail=
                "No next level available. Student should graduate"

            )



        await students_collection.update_one(

            {
                "_id":
                student_object_id
            },


            {
                "$set":
                {

                    "currentLevelId":

                        str(next_level["_id"]),


                    "status":

                        "approved",


                    "updatedAt":

                        datetime.utcnow()

                }

            }

        )



        promotion_status = "PROMOTED"


        next_level_id = str(

            next_level["_id"]

        )





    # ======================================================
    # GRADUATE
    # ======================================================


    elif action == "graduate":



        if next_level:

            raise HTTPException(

                status_code=400,

                detail=
                "Student still has next level"

            )



        await students_collection.update_one(

            {
                "_id":
                student_object_id
            },


            {
                "$set":
                {

                    "status":

                        "graduated",


                    "updatedAt":

                        datetime.utcnow()

                }

            }

        )



        promotion_status = "GRADUATED"

        next_level_id = None





    # ======================================================
    # REPEAT
    # ======================================================


    elif action == "repeat":



        await students_collection.update_one(

            {
                "_id":
                student_object_id
            },


            {
                "$set":
                {

                    "status":

                        "repeat",


                    "updatedAt":

                        datetime.utcnow()

                }

            }

        )



        promotion_status = "REPEAT"


        next_level_id = current_level_id





    else:


        raise HTTPException(

            status_code=400,

            detail=
            "Invalid action. Use promote, graduate or repeat"

        )






    # ======================================================
    # Save Promotion History
    # ======================================================


    history = create_promotion_history(

        student_id,

        current_level_id,

        next_level_id,

        promotion_status,

        record,

        vault,

        current_user

    )



    await promotions_collection.insert_one(

        history

    )






    # ======================================================
    # Update Academic Record History
    # ======================================================


    await academic_records_collection.update_one(

        {
            "_id":
            record["_id"]
        },


        {
            "$set":
            {

                "promotionStatus":

                    promotion_status,


                "processedAt":

                    datetime.utcnow(),


                "processedBy":

                    str(current_user.id)

            }

        }

    )






    return {


        "success":

            True,



        "message":

            f"Student {promotion_status.lower()} successfully",



        "studentId":

            student_id,



        "previousLevel":

            current_level.get(
                "levelNumber"
            ),



        "nextLevel":

            next_level.get(
                "levelNumber"
            )
            if next_level else None,



        "gpa":

            record.get(
                "gpa",
                0
            ),



        "cgpa":

            record.get(
                "cgpa",
                record.get("gpa",0)
            ),



        "status":

            promotion_status

    }
# ==========================================================
# Promoter Dashboard - Pending Promotion Students
# Committee Approved + Record Office Vault Locked
# ==========================================================


@router.get("/pending")
@require_role([
    UserRole.ADMIN,
    UserRole.RECORD_OFFICE
])
async def pending_promotion_students(

    current_user: User =
    Depends(get_current_active_user)

):


    result = []



    # ------------------------------------------------------
    # Find locked transcripts
    # ------------------------------------------------------

    vaults = record_office_vaults_collection.find({

        "committeeApproved": True,

        "isLocked": True

    })



    async for vault in vaults:



        student = await students_collection.find_one({

            "_id":
            ObjectId(
                vault["studentId"]
            )

        })



        if not student:

            continue




        # --------------------------------------------------
        # Academic Record
        # --------------------------------------------------

        record = await academic_records_collection.find_one({

            "studentId":
            vault["studentId"],


            "levelId":
            vault["levelId"]

        })



        if not record:

            continue





        # --------------------------------------------------
        # Current Level
        # --------------------------------------------------

        level = await levels_collection.find_one({

            "_id":
            ObjectId(
                vault["levelId"]
            )

        })



        if not level:

            continue






        # --------------------------------------------------
        # Student User Information
        # --------------------------------------------------

        user = await users_collection.find_one({

            "_id":
            ObjectId(
                student["userId"]
            )

        })



        if not user:

            continue





        result.append({


            "studentId":

                str(student["_id"]),



            "studentNumber":

                student.get(
                    "studentId"
                ),




            "fullName":

                user.get(
                    "fullName"
                ),




            "email":

                user.get(
                    "email"
                ),





            "currentLevel":

                level.get(
                    "levelNumber"
                ),





            "levelId":

                str(level["_id"]),





            "gpa":

                record.get(
                    "gpa",
                    0
                ),




            "cgpa":

                record.get(
                    "cgpa",
                    record.get(
                        "gpa",
                        0
                    )
                ),





            "committeeApproved":

                vault.get(
                    "committeeApproved",
                    False
                ),




            "vaultLocked":

                vault.get(
                    "isLocked",
                    False
                ),





            "vaultId":

                str(
                    vault["_id"]
                ),




            "academicStatus":

                record.get(
                    "academicStatus"
                )


        })




    return result
@router.get("/students")
@require_role([
    UserRole.ADMIN,
    UserRole.RECORD_OFFICE
])
async def promotion_students(
    current_user:User =
    Depends(get_current_active_user)
):

    result=[]


    cursor = students_collection.find({

        "status":"approved"

    })


    async for student in cursor:


        level_id = str(
            student.get(
                "currentLevelId"
            )
        )


        record = await academic_records_collection.find_one({

            "studentId":
            str(student["_id"]),


            "levelId":
            level_id

        })


        if not record:
            continue



        user = await users_collection.find_one({

            "_id":
            ObjectId(
                student["userId"]
            )

        })


        result.append({

            "_id":
            str(student["_id"]),


            "studentId":
            student.get(
                "studentId"
            ),


            "fullName":
            user.get(
                "fullName"
            )
            if user else "Unknown",


            "levelId":
            level_id,


            "gpa":
            record.get(
                "gpa",
                0
            ),


            "cgpa":
            record.get(
                "cgpa",
                record.get("gpa",0)
            )

        })



    return result
@router.get("/student/{student_id}")
@require_role([
    UserRole.ADMIN,
    UserRole.RECORD_OFFICE
])
async def promotion_student_detail(

    student_id:str,

    current_user:User =
    Depends(get_current_active_user)

):


    if not ObjectId.is_valid(student_id):

        raise HTTPException(
            400,
            "Invalid student id"
        )



    student = await students_collection.find_one({

        "_id":
        ObjectId(student_id)

    })


    if not student:

        raise HTTPException(
            404,
            "Student not found"
        )



    level_id = str(
        student["currentLevelId"]
    )


    record = await academic_records_collection.find_one({

        "studentId":
        student_id,


        "levelId":
        level_id

    })



    vault = await record_office_vaults_collection.find_one({

        "studentId":
        student_id,


        "levelId":
        level_id

    })



    level = await levels_collection.find_one({

        "_id":
        ObjectId(level_id)

    })



    user = await users_collection.find_one({

        "_id":
        ObjectId(
            student["userId"]
        )

    })



    return {


        "studentId":
        student_id,


        "studentNumber":
        student.get("studentId"),


        "fullName":
        user.get("fullName"),


        "levelNumber":
        level.get("levelNumber"),


        "gpa":
        record.get("gpa",0),


        "cgpa":
        record.get("cgpa",0),


        "average":
        record.get("average",0),


        "failedModules":
        record.get("failedModules",0),



        "committeeApproved":
        record.get(
            "committeeApproved",
            False
        ),


        "vaultLocked":
        vault.get(
            "isLocked",
            False
        )
        if vault else False

    }
@router.post("/execute/{student_id}")
@require_role([
    UserRole.ADMIN,
    UserRole.RECORD_OFFICE
])
async def execute_promotion(

    student_id:str,

    action:str,


    current_user:User =
    Depends(get_current_active_user)

):


    student = await students_collection.find_one({

        "_id":
        ObjectId(student_id)

    })


    if not student:

        raise HTTPException(
            404,
            "Student not found"
        )



    level_id = str(
        student["currentLevelId"]
    )



    record = await academic_records_collection.find_one({

        "studentId":
        student_id,


        "levelId":
        level_id

    })



    if not record:

        raise HTTPException(
            400,
            "Academic record missing"
        )



    vault = await record_office_vaults_collection.find_one({

        "studentId":
        student_id,


        "levelId":
        level_id,


        "isLocked":
        True

    })


    if not vault:

        raise HTTPException(

            400,

            "Record Office vault not locked"

        )



    current_level = await levels_collection.find_one({

        "_id":
        ObjectId(level_id)

    })



    next_level = await levels_collection.find_one({

        "departmentId":
        current_level["departmentId"],


        "levelNumber":
        current_level["levelNumber"] + 1

    })



    status=None



    if action=="promote":


        if not next_level:

            raise HTTPException(
                400,
                "Student should graduate"
            )



        await students_collection.update_one(

            {
                "_id":
                ObjectId(student_id)
            },


            {
                "$set":{

                    "currentLevelId":
                    str(next_level["_id"]),


                    "updatedAt":
                    datetime.utcnow()

                }

            }

        )


        status="PROMOTED"



    elif action=="graduate":


        await students_collection.update_one(

            {
                "_id":
                ObjectId(student_id)
            },


            {

                "$set":{

                    "status":
                    "graduated",


                    "updatedAt":
                    datetime.utcnow()

                }

            }

        )


        status="GRADUATED"




    elif action=="repeat":


        status="REPEAT"



    else:


        raise HTTPException(
            400,
            "Invalid action"
        )




    await promotions_collection.insert_one({

        "studentId":
        student_id,


        "previousLevelId":
        level_id,


        "nextLevelId":
        str(next_level["_id"])
        if next_level else None,


        "action":
        status,


        "gpa":
        record.get("gpa",0),


        "cgpa":
        record.get("cgpa",0),


        "processedBy":
        str(current_user.id),


        "createdAt":
        datetime.utcnow()

    })



    return {


        "success":True,


        "status":
        status,


        "message":
        "Promotion completed successfully"

    }
@router.get("/history/{student_id}")
@require_role([
    UserRole.ADMIN,
    UserRole.RECORD_OFFICE
])
async def promotion_history(

    student_id:str,

    current_user:User =
    Depends(get_current_active_user)

):


    history = await promotions_collection.find({

        "studentId":
        student_id

    }).sort(
        "createdAt",
        -1
    ).to_list(None)



    for item in history:

        item["_id"] = str(
            item["_id"]
        )


    return history
@router.get("/statistics")
@require_role([
    UserRole.ADMIN,
    UserRole.RECORD_OFFICE
])
async def promotion_statistics(

    current_user:User =
    Depends(get_current_active_user)

):


    promoted = await promotions_collection.count_documents({

        "action":
        "PROMOTED"

    })


    graduated = await promotions_collection.count_documents({

        "action":
        "GRADUATED"

    })


    repeat = await promotions_collection.count_documents({

        "action":
        "REPEAT"

    })


    return {

        "promoted":
        promoted,


        "graduated":
        graduated,


        "repeat":
        repeat

    }
