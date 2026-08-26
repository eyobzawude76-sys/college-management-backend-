from fastapi import APIRouter
from app.features.auth import router as auth_router
from app.features.students import router as students_router
from app.features.teachers import router as teachers_router
from app.features.departments import router as departments_router
from app.features.marks import router as marks_router
from app.features.promotions import router as promotions_router
from app.features.reports import router as reports_router
from app.features.academic_records import router as academic_records_router
from app.features.committee import router as committee_router
from app.features.record_office import router as record_office_router
from app.features.modules import router as modules_router
from app.features.levels import router as levels_router
from app.features.admin import router  as admin_router
from app.features.department_review import router as department_review_router
from app.features.module_assignment import router as module_assignment_router
from app.features.grading_engine import router as grading_engine_router
api_router = APIRouter()
api_router.include_router(admin_router, prefix="/admin",tags=["Admin"])
api_router.include_router(levels_router, prefix="/levels", tags=["Levels"])
api_router.include_router(auth_router, prefix="/auth", tags=["Auth"])
api_router.include_router(students_router, prefix="/students", tags=["Students"])
api_router.include_router(teachers_router, prefix="/teachers", tags=["Teachers"])
api_router.include_router(departments_router, prefix="/departments", tags=["Departments"])
api_router.include_router(marks_router, prefix="/marks", tags=["Marks"])
api_router.include_router(promotions_router, prefix="/promotions", tags=["Promotions"])
api_router.include_router(reports_router, prefix="/reports", tags=["Reports"])
api_router.include_router(academic_records_router, prefix="/academic-records", tags=["Academic Records"])
api_router.include_router(committee_router, prefix="/committee", tags=["Committee"])
api_router.include_router(record_office_router, prefix="/record-office", tags=["Record Office"])
api_router.include_router(grading_engine_router, prefix="/grading-engine", tags=["Grading Engine"])
api_router.include_router(modules_router, prefix="/modules", tags=["Modules"])
api_router.include_router(department_review_router, prefix="/department-review", tags=["Department Review"])
api_router.include_router(module_assignment_router, prefix="/module-assignments", tags=["Module Assignment"])