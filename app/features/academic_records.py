from datetime import datetime
from typing import List, Optional
from bson import ObjectId

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.database import (
    academic_records_collection,
    marks_collection,
    students_collection,
    modules_collection,
    levels_collection,
)

from app.features.auth import User, UserRole
from app.shared.auth import get_current_active_user
from app.shared.rbac import require_role


router = APIRouter()
 




class AcademicRecord(BaseModel):

    id: Optional[str] = Field(
        None,
        alias="_id"
    )

    studentId: str
    levelId: str
    levelNumber: int

    modules: List[dict]

    totalCreditHours: int
    totalMarks: float
    averageMark: float

    finalStatus: str

    academicYear: str

    recordedBy: str
    recordedAt: datetime

    status: str = "active"

    createdAt: datetime


    class Config:
        populate_by_name = True





@router.post(
    "/process-level/{student_id}",
    status_code=status.HTTP_201_CREATED
)
@require_role([
    UserRole.RECORD_OFFICE,
    UserRole.ADMIN
])
async def process_level_record(
    student_id:str,
    current_user:User = Depends(get_current_active_user)
):


    student = await students_collection.find_one({
        "_id":ObjectId(student_id)
    })


    if not student:
        raise HTTPException(
            404,
            "Student not found"
        )



    level_id = student.get(
        "currentLevelId"
    )


    if not level_id:
        raise HTTPException(
            400,
            "Level not assigned"
        )



    marks = await marks_collection.find({
        "studentId":student_id,
        "status":"approved"
    }).to_list(None)



    if not marks:

        raise HTTPException(
            400,
            "No approved marks"
        )



    modules=[]

    total_credit=0
    total_score=0



    for mark in marks:


        module = await modules_collection.find_one({
            "_id":ObjectId(
                mark["moduleId"]
            )
        })


        if not module:
            continue



        if str(module["levelId"]) != str(level_id):
            continue



        score = mark.get(
            "mark",
            0
        )


        modules.append({

            "moduleId":str(module["_id"]),

            "moduleName":
            module["moduleName"],

            "creditHour":
            module["creditHour"],

            "mark":
            score

        })



        total_credit += module["creditHour"]

        total_score += (
            score *
            module["creditHour"]
        )



    average = (
        total_score / total_credit
        if total_credit
        else 0
    )



    level = await levels_collection.find_one({
        "_id":ObjectId(level_id)
    })



    record={

        "studentId":student_id,

        "levelId":str(level_id),

        "levelNumber":
        level.get("levelNumber",0)
        if level else 0,


        "modules":modules,

        "totalCreditHours":
        total_credit,


        "totalMarks":
        total_score,


        "averageMark":
        round(average,2),


        "finalStatus":
        "COMPLETED",


        "academicYear":
        f"{datetime.utcnow().year}",


        "recordedBy":
        str(current_user.id),


        "recordedAt":
        datetime.utcnow(),


        "status":
        "active",


        "createdAt":
        datetime.utcnow()

    }



    result = await academic_records_collection.insert_one(
        record
    )


    record["_id"] = str(
        result.inserted_id
    )


    return record