from fastapi import APIRouter, Depends
from app.features.auth import User
from app.shared.auth import get_current_active_user
from app.database import students_collection, marks_collection

router = APIRouter(prefix="/analytics", tags=["Analytics"])

@router.get("/dashboard-stats")
async def get_dashboard_stats(
    current_user: User = Depends(get_current_active_user)
):
    total_students = await students_collection.count_documents({})
    
    pipeline_status = [
        {"$group": {"_id": "$status", "count": {"$sum": 1}}}
    ]
    status_counts = await marks_collection.aggregate(pipeline_status).to_list(length=None)
    
    pipeline_dept = [
        {"$match": {"status": "approved"}},
        {"$lookup": {
            "from": "students",
            "localField": "studentId",
            "foreignField": "_id",
            "as": "student"
        }},
        {"$unwind": "$student"},
        {"$lookup": {
            "from": "departments",
            "localField": "student.departmentId",
            "foreignField": "_id",
            "as": "dept"
        }},
        {"$unwind": "$dept"},
        {"$group": {
            "_id": "$dept.name",
            "averageMark": {"$avg": "$mark"}
        }}
    ]
    dept_stats = await marks_collection.aggregate(pipeline_dept).to_list(length=None)
    
    return {
        "totalStudents": total_students,
        "statusCounts": status_counts,
        "departmentAverages": dept_stats
    }